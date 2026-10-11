"""STEP 2 — Docling front-end + LLM schema mapping. LV pages only (locked scope).

    positions = extract_positions(pdf_bytes, llm=..., config=...)

Two paths:
  * primary   Docling (layout + TableFormer) -> page text/tables -> LLM maps the page
              into structured position records.
  * fallback  the deterministic regex parser in ``engine/parser.py`` (LV pages only).

The fallback keeps the step usable when Docling is absent, the LLM key is missing,
or a call fails. Every row records which path produced it in ``extractor``.

Output rows use the SAME schema as ``engine/parser.py`` so the pricing engine
(step 4) consumes them unchanged.
"""
from __future__ import annotations

import json
import os
import tempfile
import time

from .config import ExtractConfig, LLMConfig
from .llm import LLMError, build_llm, parse_json_response

# Unit map mirrors engine/parser.py so output is drop-in compatible.
UNIT_MAP = {
    "stk": "pc", "stk.": "pc", "stück": "pc", "st": "pc", "st.": "pc",
    "m": "m", "lm": "m", "m2": "m2", "m²": "m2", "m3": "m3", "m³": "m3",
    "std": "h", "std.": "h", "h": "h", "kg": "kg", "psch": "LS", "le": "LS",
    "mt": "manday", "mann tag": "manday", "manntag": "manday",
}

POSITION_KEYS = [
    "position_id", "system", "section", "source_page", "source_kind", "title", "description",
    "quantity", "unit", "dn_mm", "w_mm", "h_mm", "l_mm", "airflow_m3h", "manufacturer_hint",
    "model_hint", "component_code", "angle_deg", "raw_line", "context", "notes", "extractor",
]


class ExtractorError(RuntimeError):
    pass


EXTRACT_SYSTEM = (
    "You extract line items (Positionen) from a Swiss BKP-244 ventilation tender "
    "(Leistungsverzeichnis). You return ONLY JSON. You never invent or recompute a "
    "quantity: if a number is not written in the document you return null."
)

EXTRACT_USER = """Extract every tender position from the LV pages below.

For EACH position return an object with these keys:
  source_page    int    - the page number printed in the text as [PAGE n]
  section        str    - the section letter+name (e.g. "A Apparate", "B Kanäle")
  description    str    - the full item description as written (original language)
  quantity       float  - copied exactly from the document; null if absent
  unit           str    - one of pc, m, m2, m3, h, kg, LS, manday
  dn_mm          float  - nominal diameter in mm, else null
  w_mm           float  - width  in mm, else null
  h_mm           float  - height in mm, else null
  l_mm           float  - length in mm, else null
  airflow_m3h    float  - air volume in m3/h, else null

Rules:
- Quantities MUST be copied verbatim. Never sum, scale or infer a quantity.
- Convert units: Stk/Stk. -> pc ; m²/m2 -> m2 ; m³/m3 -> m3 ; Std -> h ; Mann-Tage -> manday.
- Convert cm to mm for dn/w/h/l (multiply by 10).
- Ignore totals, headers, footers, section banners and boilerplate.
- If a page has no positions, contribute nothing for it.

TENDER PAGES:
{pages}

Reply with JSON only: {{"positions": [ ... ]}}
"""


# --------------------------------------------------------------------------- Docling
def docling_pages(pdf_bytes: bytes, ocr: bool = False, table_mode: str = "accurate",
                  page_range: tuple[int, int] | None = None):
    """Convert a PDF with Docling and return [{'page': n, 'text': str}, ...].

    ``page_range`` limits conversion to (first_page, last_page), 1-based inclusive.
    Docling is slow on large tenders (minutes for ~200 pages), so use it to convert
    in chunks or to smoke-test the front-end quickly.

    Isolated here so a Docling API change only touches this function.
    """
    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
        from docling.document_converter import DocumentConverter, PdfFormatOption
    except ImportError as e:  # Docling not installed
        raise ExtractorError(
            "Docling is not installed. `pip install docling`, or run with "
            "ExtractConfig(use_docling=False) to use the regex fallback."
        ) from e

    opts = PdfPipelineOptions()
    opts.do_ocr = ocr
    opts.do_table_structure = True
    opts.table_structure_options.mode = (
        TableFormerMode.ACCURATE if table_mode == "accurate" else TableFormerMode.FAST
    )
    conv = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    try:
        tmp.write(pdf_bytes)
        tmp.close()
        kwargs = {"page_range": page_range} if page_range else {}
        doc = conv.convert(tmp.name, **kwargs).document
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    pages = []
    for n in sorted(doc.pages.keys()):
        try:
            text = doc.export_to_text(page_no=n)
        except TypeError:                      # older/newer signature
            text = doc.export_to_markdown(page_no=n)
        pages.append({"page": int(n), "text": text or ""})
    return pages


# --------------------------------------------------------------------------- page helpers
def classify_page(text: str) -> str:
    """Same classification rule as engine/parser.py — duplicated to stay standalone."""
    first = text.strip().split("\n", 1)[0] if text.strip() else ""
    if "Pos. Gegenstand" in text[:400]:
        return "LV positions"
    if first.startswith("Bauteilliste"):
        return "Component list (Bauteilliste)"
    if "KOSTENZUSAMMENSTELLUNG" in text[:300]:
        return "Cost summary form"
    if "Planliste" in text[:200]:
        return "Plan list"
    if "Inhaltsverzeichnis" in text[:200] or "Ausschreibung und Angebot" in text[:600]:
        return "Cover / index"
    if not text.strip():
        return "Blank / drawing"
    return "Conditions & information"


def _system_from_page(text: str) -> str:
    """System code from the footer .docx path or the header, e.g. '244.01'."""
    import re
    m = re.search(r"\\(?:244\.\d\d)\s+[^\\]+?\.docx", text, re.I)
    if not m:
        m = re.search(r"Oberglatt\s+(244\.\d\d)\s+[^\n]+?Seite\s+\d+", text, re.I)
        return m.group(1) if m else ""
    return m.group(0)[1:7].replace("\\", "").strip()[:6]


def _to_float(v):
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace("'", "").replace("’", "").replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def _norm_unit(u) -> str:
    if not u:
        return ""
    return UNIT_MAP.get(str(u).strip().lower(), str(u).strip())


# --------------------------------------------------------------------------- fallback
def regex_positions(pdf_bytes: bytes, only_lv: bool = True):
    """Deterministic fallback: the existing regex parser, optionally LV-only."""
    try:
        from engine.parser import parse_tender
    except ImportError as e:
        raise ExtractorError(
            "regex fallback needs engine/parser.py on the path (or use Docling)"
        ) from e
    rows, pages = parse_tender(pdf_bytes)
    if only_lv:
        rows = [dict(r, extractor="regex") for r in rows if r.get("source_kind") == "LV"]
    else:
        rows = [dict(r, extractor="regex") for r in rows]
    return rows, pages


# --------------------------------------------------------------------------- LLM path
def _pages_block(batch) -> str:
    return "\n\n".join(f"[PAGE {p['page']}]\n{p['text']}" for p in batch)


def _coerce_position(raw: dict, page_systems: dict) -> dict | None:
    desc = str(raw.get("description") or "").strip()
    if not desc:
        return None
    page = int(raw.get("source_page") or 0)
    return {
        "position_id": "",
        "system": page_systems.get(page, ""),
        "section": str(raw.get("section") or "").strip(),
        "source_page": page,
        "source_kind": "LV",
        "title": desc.split("–")[0].strip()[:200],
        "description": desc,
        "quantity": _to_float(raw.get("quantity")),
        "unit": _norm_unit(raw.get("unit")),
        "dn_mm": _to_float(raw.get("dn_mm")),
        "w_mm": _to_float(raw.get("w_mm")),
        "h_mm": _to_float(raw.get("h_mm")),
        "l_mm": _to_float(raw.get("l_mm")),
        "airflow_m3h": _to_float(raw.get("airflow_m3h")),
        "manufacturer_hint": "",
        "model_hint": "",
        "component_code": "",
        "angle_deg": None,
        "raw_line": desc,
        "context": desc,
        "notes": "",
        "extractor": "docling+llm",
    }


def extract_positions(pdf_bytes: bytes, llm=None, config: ExtractConfig | None = None,
                      llm_config: LLMConfig | None = None, progress=None) -> list[dict]:
    """STEP 2. PDF bytes -> list of position dicts (LV pages only by default)."""
    cfg = config or ExtractConfig()
    llm = llm if llm is not None else build_llm(llm_config)

    pages = None
    if cfg.use_docling:
        try:
            pages = docling_pages(pdf_bytes, ocr=cfg.docling_ocr, table_mode=cfg.docling_table_mode)
        except ExtractorError:
            pages = None
        except Exception:                      # noqa: BLE001 - any Docling failure -> fallback
            pages = None

    if pages is None or not cfg.use_llm:
        rows, _ = regex_positions(pdf_bytes, only_lv=cfg.only_lv_pages)
        _renumber(rows)
        return rows

    # keep only LV pages (locked scope)
    lv = [p for p in pages if classify_page(p["text"]) == "LV positions"]
    if not lv:
        rows, _ = regex_positions(pdf_bytes, only_lv=cfg.only_lv_pages)
        _renumber(rows)
        return rows

    page_systems = {p["page"]: _system_from_page(p["text"]) for p in lv}
    out: list[dict] = []
    total = len(lv)
    step = max(1, cfg.pages_per_call)

    for i in range(0, total, step):
        batch = lv[i:i + step]
        try:
            reply = llm.complete_json(
                EXTRACT_SYSTEM,
                EXTRACT_USER.format(pages=_pages_block(batch)),
                tag="extract",
            )
            items = reply.get("positions", reply if isinstance(reply, list) else [])
        except LLMError:
            items = []
        for raw in items:
            if isinstance(raw, dict):
                row = _coerce_position(raw, page_systems)
                if row:
                    out.append(row)
        if progress:
            progress(min(1.0, (i + step) / total))

    # If the LLM produced nothing usable, fall back rather than return an empty run.
    if not out:
        rows, _ = regex_positions(pdf_bytes, only_lv=cfg.only_lv_pages)
        _renumber(rows)
        return rows

    _renumber(out)
    return out


def _renumber(rows) -> None:
    for k, r in enumerate(rows, 1):
        r["position_id"] = f"P{k:04d}"
