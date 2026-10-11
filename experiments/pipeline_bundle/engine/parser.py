"""Tender PDF parser for Swiss BKP/NPK-style Leistungsverzeichnis (LV) documents.

Turns the full multi-page tender into structured position rows:
    position_id, system, section, source_page, title, description, quantity, unit,
    dn_mm, w_mm, h_mm, l_mm, airflow_m3h, manufacturer_hint, model_hint, raw_line, context

Two kinds of pages carry priceable content:
  * LV pages   ("Pos. Gegenstand Mass- ..." header, system name in footer .docx path)
  * Bauteilliste pages (NOVA component lists with duct lengths in mm and fitting counts)
Every other page is classified (conditions, schedule, plan list, ...) for traceability.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field, asdict

import pdfplumber

# --------------------------------------------------------------------------- regexes
NUM = r"\d[\d'’`]*(?:[.,]\d+)?"
QTY_RE = re.compile(
    rf"^(?P<pre>.*?)\s*(?<![\w.])(?P<unit>Stk\.?|Stück|m2|m²|m|lm|Std\.?|kg|psch|LE)\s+(?P<qty>{NUM})\s*[.…]*\s*$"
)
QTY_MISSING_RE = re.compile(r"^(?P<pre>[A-Za-zÄÖÜäöü].*?(?:[^\d\s]|\d-\d))\s+(?P<unit>Stk\.?|m2)\s*[.…]*\s*$")
MANDAYS_RE = re.compile(rf"^(?P<qty>{NUM})\s+Mann\s*Tage\b")
SECTION_RE = re.compile(r"^(?P<letter>[A-F])\s+(?P<name>[A-ZÄÖÜ][A-ZÄÖÜ ,.\-]{3,})$")
FOOTER_RE = re.compile(r"\\(?P<code>244\.\d\d)\s+(?P<name>[^\\]+?)\.docx", re.I)
HEADER_SYS_RE = re.compile(r"Oberglatt\s+(?P<code>244\.\d\d)\s+(?P<name>.+?)\s+Seite\s+\d+", re.I)
DIA_RE = re.compile(rf"(?:[Øø]\s*(?P<a>{NUM})\s*(?:cm)?|(?P<b>{NUM})\s*[Øø]\s*cm)")
DIMS_RE = re.compile(rf"(?P<w>{NUM})\s*[x×]\s*(?P<h>{NUM})(?:\s*[x×]\s*(?P<l>{NUM}))?\s*(?P<u>cm|mm)?")
AIRFLOW_RE = re.compile(rf"(?:Luftmenge|Luftvolumenstrom)\s*:?\s*(?P<v>{NUM})\s*m3/h", re.I)
FAB_RE = re.compile(r"^Fabrikat\s*(?:z\.\s*B\.?)?\s*(?P<v>.+)$", re.I)
TYP_RE = re.compile(r"^Typ\s*(?:z\.\s*B\.?)?\s*(?P<v>.+)$", re.I)

SPEC_PREFIXES = (
    "fabrikat", "typ ", "typ:", "material", "farbe", "grösse", "grosse", "mod.", "cm ", "mm ",
    "___", "luftmenge", "b x h", "offert", "oder gleich", "qualitätsstufe", "dämpfung", "druckverlust",
    "kulissen", "anzahl", "spaltbreite", "63 125", "-", "für lüftungskanäle", "abmessungen", "zubehör",
    "bemerkungen", "schallleistungspegel", "bestehend", "gewicht", "max.", "einbringung", "anordnung",
    "sockel", "b =", "h =", "l =", "leistung", "spannung", "drehzahl",
)
EQUIP_TITLE_RE = re.compile(r"^[A-ZÄÖÜ][\wäöüÄÖÜ\-]+(?:\s+[\wäöüÄÖÜ\-]+)*\s+\d+-\d+$")

UNIT_MAP = {"stk": "pc", "stk.": "pc", "stück": "pc", "m": "m", "lm": "m", "m2": "m2", "m²": "m2",
            "std": "h", "std.": "h", "kg": "kg", "psch": "LS", "le": "LS"}

SYSTEM_NAMES = {
    "244.01": "244.01 LA01 Nebenräume UG",
    "244.02": "244.02 LA02 Essenräume EG",
    "244.03": "244.03 LA03 Küche / Abwaschen EG",
    "244.04": "244.04 LA04 Schulzimmer OG",
    "244.05": "244.05 LA05 Turnhalle",
    "244.06": "244.06 Montagesystem Flachdach",
}
SECTION_NAMES = {"A": "A Apparate", "B": "B Kanäle", "C": "C Armaturen und Instrumente",
                 "D": "D Regulierung", "E": "E Montage, Dienstleistungen", "F": "F Dämmungen"}


def to_float(s: str | None) -> float | None:
    if s is None:
        return None
    s = s.replace("'", "").replace("’", "").replace("`", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


@dataclass
class Position:
    position_id: str = ""
    system: str = ""
    section: str = ""
    source_page: int = 0
    source_kind: str = "LV"          # LV | Bauteilliste
    title: str = ""
    description: str = ""
    quantity: float | None = None
    unit: str = ""
    dn_mm: float | None = None
    w_mm: float | None = None
    h_mm: float | None = None
    l_mm: float | None = None
    airflow_m3h: float | None = None
    manufacturer_hint: str = ""
    model_hint: str = ""
    component_code: str = ""         # Bauteilliste code (R-R, L, BGE ...)
    angle_deg: float | None = None
    raw_line: str = ""
    context: str = ""
    notes: list = field(default_factory=list)


# --------------------------------------------------------------------------- helpers
def _system_from_page(text: str) -> str | None:
    m = FOOTER_RE.search(text)
    if m:
        return SYSTEM_NAMES.get(m.group("code"), f"{m.group('code')} {m.group('name')}")
    m = HEADER_SYS_RE.search(text.split("\n", 1)[0])
    if m:
        return SYSTEM_NAMES.get(m.group("code"), f"{m.group('code')} {m.group('name')}")
    return None


def classify_page(text: str) -> str:
    first = text.strip().split("\n", 1)[0] if text.strip() else ""
    if "Pos. Gegenstand" in text[:400]:
        return "LV positions"
    if first.startswith("Bauteilliste"):
        return "Component list (Bauteilliste)"
    if "KOSTENZUSAMMENSTELLUNG" in text[:300]:
        return "Cost summary form"
    if re.search(r"\bTage\s+(Mon|Die|Mit|Don|Fre)\b", text):
        return "Construction schedule"
    if "Planliste" in text[:200]:
        return "Plan list"
    if "Inhaltsverzeichnis" in text[:200] or "Ausschreibung und Angebot" in text[:600]:
        return "Cover / index"
    if not text.strip():
        return "Blank / drawing"
    return "Conditions & information"


def _is_spec_line(line: str) -> bool:
    l = line.lower().strip()
    return l.startswith(SPEC_PREFIXES) or bool(re.match(r"^[\d.\s/x×-]+$", l))


def _pick_title(block: list[str], fallback: str) -> str:
    for ln in block:
        if not _is_spec_line(ln) and len(ln) > 3 and not re.match(r"^\d+\s", ln) and (not ln[:1].islower() or ln.startswith("wie vorbeschrieben")):
            return ln.strip()
    return fallback.strip() or (block[0].strip() if block else "")


def _dims_from(text: str, prefer_cm: bool = True):
    """Return (w,h,l) in mm from a 'B x H (x L)' expression."""
    m = None
    for m in DIMS_RE.finditer(text):
        pass
    if not m:
        return None
    w, h, l = to_float(m.group("w")), to_float(m.group("h")), to_float(m.group("l"))
    unit = m.group("u")
    if unit is None:
        unit = "cm" if re.search(r"\bcm\b", text) else ("mm" if re.search(r"\bmm\b", text) else None)
    if unit is None:
        unit = "mm" if max(v for v in (w, h, l) if v) >= 100 else "cm"
    f = 10.0 if unit == "cm" else 1.0
    return (w * f if w else None, h * f if h else None, l * f if l else None)


def _extract_sizes(pos: Position, line: str, block: list[str]):
    ctx = "\n".join(block)
    pre = QTY_RE.match(line).group("pre") if QTY_RE.match(line) else line
    # 1) diameter on the quantity line itself
    m = DIA_RE.search(pre)
    if m:
        v = to_float(m.group("a") or m.group("b"))
        pos.dn_mm = v * 10 if v and v < 100 else v
    # 2) rectangular dims on the quantity line
    if pos.dn_mm is None and re.search(r"\d\s*[x×]\s*\d", pre):
        d = _dims_from(pre)
        if d:
            pos.w_mm, pos.h_mm, pos.l_mm = d
    # 3) table rows  ("TVR-D 12.5 60 200 150", "....... 250 100 150", "100 10 28.5x20.5 27")
    if pos.dn_mm is None and pos.w_mm is None:
        hdr_dn = re.search(r"Mod\.\s+DN", ctx)
        nums = [to_float(x) for x in re.findall(NUM, re.sub(r"^[A-Za-z][\w\-]*\s+", "", pre.replace(".......", "")))]
        nums = [n for n in nums if n is not None]
        unit_cm = bool(re.search(r"^\s*cm\b", ctx, re.M))
        if hdr_dn and nums:
            v = nums[0]
            pos.dn_mm = v * 10 if (unit_cm and v < 100) else v
        elif "Ø" in ctx and "Länge" in ctx and len(nums) >= 2:   # compact silencer table: length, Ø
            pos.l_mm, pos.dn_mm = nums[0] * 10, nums[1] * 10
    # 4) fall back to block-level dims (e.g. "B x H x L 40 x 30 x 125 cm")
    if pos.dn_mm is None and pos.w_mm is None:
        for ln in block:
            if re.search(r"B\s*x\s*H", ln) and re.search(r"\d\s*[x×]\s*\d", ln):
                d = _dims_from(ln)
                if d:
                    pos.w_mm, pos.h_mm, pos.l_mm = d
                    break
    if pos.dn_mm is None and pos.w_mm is None:
        m = DIA_RE.search(ctx)
        if m:
            v = to_float(m.group("a") or m.group("b"))
            pos.dn_mm = v * 10 if v and v < 100 else v
    m = AIRFLOW_RE.search(ctx)
    if m:
        pos.airflow_m3h = to_float(m.group("v"))
    for ln in block:
        if not pos.manufacturer_hint and (mm := FAB_RE.match(ln.strip())):
            v = mm.group("v").strip(" .")
            pos.manufacturer_hint = "" if set(v) <= {"."} else v
        if not pos.model_hint and (mm := TYP_RE.match(ln.strip())):
            v = mm.group("v").strip(" .")
            pos.model_hint = "" if set(v) <= {"."} else v


# --------------------------------------------------------------------------- LV pages
def _parse_lv_page(lines, page_no, system, state, out):
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith(("Pos. Gegenstand", "Gattg.", "H:\\", "SH Erlenstrasse")):
            continue
        if re.match(r"^244\.\d+\s+[A-Z]", line):           # system banner e.g. "244.01 LA NEBENRÄUME"
            state["block"] = []
            continue
        if "KOSTENZUSAMMENSTELLUNG" in line:
            state["stop_page"] = True
            break
        sm = SECTION_RE.match(line)
        if sm and sm.group("letter") + " " in line[:2] and line.isupper():
            state["section"] = SECTION_NAMES.get(sm.group("letter"), line)
            state["block"], state["last_qty"] = [], False
            continue
        if line.lower().startswith(("total", "zwischentotal")):
            state["block"], state["last_qty"] = [], False
            continue

        in_a = state["section"].startswith("A")
        eq = state.get("equip")
        if in_a and eq is not None and eq.airflow_m3h is None and (am := AIRFLOW_RE.search(line)):
            eq.airflow_m3h = to_float(am.group("v"))
        if in_a and EQUIP_TITLE_RE.match(line):          # heading without unit, e.g. "Zuluftgerät 4-1"
            pos = Position(system=system, section=state["section"], source_page=page_no, raw_line=line,
                           title=line, description=line, quantity=None, unit="pc", component_code="EQUIPMENT")
            pos.notes.append("quantity blank in tender")
            out.append(pos)
            state["equip"], state["block"], state["last_qty"] = pos, [line], True
            continue

        qm = QTY_RE.match(line)
        md = MANDAYS_RE.match(line)
        qmiss = None if (qm or md) else QTY_MISSING_RE.match(line)
        if qm or md or qmiss:
            pre = (qm or qmiss).group("pre").strip() if (qm or qmiss) else line
            # accessory lines inside equipment descriptions ("1 Leerteil Stk. 1", "- TW-1 ... 1 Stk")
            sub_component = in_a and not EQUIP_TITLE_RE.match(pre)
            is_equipment = in_a and bool(EQUIP_TITLE_RE.match(pre))
            if is_equipment:
                state["block"] = []
            block = list(state["block"]) if state["block"] else []
            title = _pick_title(block, pre) if block else pre
            pos = Position(system=system, section=state["section"], source_page=page_no, raw_line=line)
            if md:
                pos.quantity, pos.unit = to_float(md.group("qty")), "manday"
                title = "Montagezeit (Mann-Tage)"
            elif qm:
                pos.quantity, pos.unit = to_float(qm.group("qty")), UNIT_MAP.get(qm.group("unit").lower(), qm.group("unit"))
            else:
                pos.quantity, pos.unit = None, UNIT_MAP.get(qmiss.group("unit").lower(), "pc")
                pos.notes.append("quantity blank in tender")
            pos.title = title
            size_txt = pre if pre and pre != title else ""
            pos.description = (title + (" – " + size_txt if size_txt and size_txt not in title else "")).strip()
            pos.context = "\n".join(block[:40] + [line])
            if sub_component:
                pos.notes.append("sub-component of equipment above")
                pos.component_code = "SUBCOMPONENT"
            elif in_a:
                pos.component_code = "EQUIPMENT"
                state["equip"] = pos
            _extract_sizes(pos, line, block + ([pre] if not block else []))
            out.append(pos)
            if not block:
                state["block"] = [pre]
            state["last_qty"] = True
            continue
        if state["last_qty"]:
            state["block"] = []
        state["block"].append(line)
        state["last_qty"] = False


# --------------------------------------------------------------------------- Bauteilliste pages
BTL_LINE = re.compile(r"^(?P<q>\d+)(?P<code>R-R|LT|L|BA|BS|RS|SR|UA|US|ATE|BGE|DRE|MFA|USE|[A-Z]{1,4}(?:-[A-Z])?)\s+(?P<rest>.+)$")


def _parse_bauteilliste(lines, page_no, system, out):
    mode = None  # 'len' or 'count'
    for raw in lines:
        line = raw.strip()
        if re.match(r"^l\s*KZ", line):
            mode = "len"; continue
        if re.match(r"^Stk\s*KZ", line):
            mode = "count"; continue
        m = BTL_LINE.match(line)
        if not m or mode is None:
            continue
        q = float(m.group("q"))
        code = m.group("code")
        rest = m.group("rest")
        name = re.match(r"^([A-Za-zÄÖÜäöüß°\s\-]+?)(?=\s+\d|$)", rest)
        name = name.group(1).strip() if name else rest
        nums = [to_float(x) for x in re.findall(r"\d+(?:\.\d+)?", rest[len(name):])]
        pos = Position(system=system, section="B Kanäle", source_page=page_no, source_kind="Bauteilliste",
                       raw_line=line, component_code=code, context=line)
        if mode == "len":
            length_m = q / 1000.0
            if code == "R-R" and nums:
                pos.dn_mm = nums[0]
                pos.quantity, pos.unit = round(length_m, 2), "m"
                pos.title = f"Wickelfalzrohr DN{int(nums[0])}"
                pos.description = f"Spiral-seam circular duct DN{int(nums[0])}, {length_m:.2f} m"
            elif code in ("L", "LT") and len(nums) >= 2:
                a, b = nums[0], nums[1]
                area = 2 * (a + b) / 1000.0 * length_m
                pos.w_mm, pos.h_mm = a, b
                pos.quantity, pos.unit = round(area, 2), "m2"
                pos.title = f"{name} {int(a)}x{int(b)}"
                pos.description = f"Rectangular duct {int(a)}x{int(b)} mm, {length_m:.2f} m run → {area:.2f} m² surface"
            else:
                continue
        else:
            pos.quantity, pos.unit = q, "pc"
            pos.title = f"{name} " + " ".join(str(int(n)) for n in nums if n is not None)
            pos.description = f"Duct fitting: {pos.title.strip()}"
            if code in ("BGE",) and nums:
                pos.dn_mm = nums[0]
                pos.angle_deg = nums[-1] if len(nums) > 1 else None
            elif code in ("ATE", "MFA", "USE", "DRE", "SR") and nums:
                pos.dn_mm = nums[0]
            elif len(nums) >= 2:
                pos.w_mm, pos.h_mm = nums[0], nums[1]
                if len(nums) >= 4:
                    pos.angle_deg = nums[-1]
        out.append(pos)


# --------------------------------------------------------------------------- public API
def parse_tender(pdf_bytes: bytes, progress=None):
    """Parse the full tender. Returns (positions: list[dict], page_index: list[dict])."""
    positions: list[Position] = []
    page_index = []
    current_system = None
    state = {"section": "", "block": [], "last_qty": False, "system": None}
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        n = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            kind = classify_page(text)
            sys_here = _system_from_page(text) if kind == "LV positions" else None
            if sys_here:
                if sys_here != state["system"]:
                    state.update(section="", block=[], last_qty=False, system=sys_here, equip=None)
                current_system = sys_here
            lines = text.split("\n")
            before = len(positions)
            if kind == "LV positions":
                state["stop_page"] = False
                _parse_lv_page(lines[1:], i + 1, current_system or "unassigned", state, positions)
            elif kind.startswith("Component list"):
                state["block"], state["last_qty"] = [], False
                _parse_bauteilliste(lines, i + 1, current_system or "unassigned", positions)
            page_index.append({"page": i + 1, "kind": kind, "system": sys_here or (current_system if kind.startswith("Component") else ""),
                               "positions_found": len(positions) - before})
            if progress:
                progress((i + 1) / n)
    rows = []
    for k, p in enumerate(positions, 1):
        p.position_id = f"P{k:04d}"
        d = asdict(p)
        d["notes"] = "; ".join(p.notes)
        rows.append(d)
    return rows, page_index
