from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PdfTable:
    page_number: int
    rows: tuple[tuple[str, ...], ...]
    bbox: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class PdfPageText:
    page_number: int
    text: str
    structured_text: str | None = None
    tables: tuple[PdfTable, ...] = ()
    extraction_backend: str = "pdfplumber"


def extract_pdf_text_pages(
    pdf_path: Path,
    page_numbers: list[int] | None = None,
    backend: str = "pdfplumber",
) -> list[PdfPageText]:
    if backend not in {"pdfplumber", "docling", "hybrid"}:
        raise ValueError(f"Unsupported PDF extraction backend: {backend}")
    if backend == "docling":
        return extract_docling_pages(pdf_path, page_numbers)

    pages = _extract_pdfplumber_pages(pdf_path, page_numbers)
    if backend == "pdfplumber":
        return pages
    try:
        docling_pages = {
            page.page_number: page
            for page in extract_docling_pages(
                pdf_path,
                page_numbers,
                mode=os.getenv("TENDER_DOCLING_MODE", "standard").strip().lower(),
                extract_tables=_env_flag("TENDER_DOCLING_TABLES"),
            )
        }
    except Exception:
        # Hybrid extraction is deliberately fail-open: existing uploads remain usable.
        return pages
    return [
        PdfPageText(
            page_number=page.page_number,
            text=page.text,
            structured_text=docling_pages.get(page.page_number).text if page.page_number in docling_pages else None,
            tables=docling_pages.get(page.page_number).tables if page.page_number in docling_pages else (),
            extraction_backend="hybrid" if page.page_number in docling_pages else "pdfplumber_fallback",
        )
        for page in pages
    ]


def _extract_pdfplumber_pages(
    pdf_path: Path,
    page_numbers: list[int] | None = None,
) -> list[PdfPageText]:
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "PDF extraction requires pdfplumber. Use the bundled Codex Python runtime "
            "or install pdfplumber in the active environment."
        ) from exc

    selected = set(page_numbers) if page_numbers else None
    pages: list[PdfPageText] = []
    with pdfplumber.open(pdf_path) as document:
        for index, page in enumerate(document.pages, start=1):
            if selected is not None and index not in selected:
                continue
            text = page.extract_text(x_tolerance=1, y_tolerance=3, layout=False) or ""
            pages.append(PdfPageText(page_number=index, text=text))
    return pages


def extract_docling_pages(
    pdf_path: Path,
    page_numbers: list[int] | None = None,
    *,
    mode: str = "standard",
    extract_tables: bool = False,
) -> list[PdfPageText]:
    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import NativePdfPipelineOptions, PdfPipelineOptions
        from docling.document_converter import DocumentConverter, NativePdfFormatOption, PdfFormatOption
        from docling_core.types.doc import TableItem
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("Docling PDF extraction requires the optional docling dependency.") from exc

    if mode == "standard":
        options = PdfPipelineOptions()
        options.do_ocr = False
        options.do_table_structure = extract_tables
        options.generate_page_images = False
        options.generate_picture_images = False
        format_option: Any = PdfFormatOption(pipeline_options=options)
    elif mode == "native":
        if extract_tables:
            raise ValueError("Docling native mode does not provide table recognition.")
        options = NativePdfPipelineOptions(
            generate_page_images=False,
            generate_picture_images=False,
            parser_threads=2,
        )
        format_option = NativePdfFormatOption(pipeline_options=options)
    else:
        raise ValueError(f"Unsupported Docling mode: {mode}")

    selected = set(page_numbers) if page_numbers else None
    page_range = (min(selected), max(selected)) if selected else (1, 2**31 - 1)
    result = DocumentConverter(format_options={InputFormat.PDF: format_option}).convert(
        pdf_path,
        page_range=page_range,
    )
    text_by_page: dict[int, list[str]] = {}
    tables_by_page: dict[int, list[PdfTable]] = {}
    for item, _level in result.document.iterate_items():
        provenance = getattr(item, "prov", None) or []
        if not provenance:
            continue
        page_number = int(provenance[0].page_no)
        if selected is not None and page_number not in selected:
            continue
        if isinstance(item, TableItem):
            rows = tuple(
                tuple(cell.text.strip() for cell in row)
                for row in item.data.grid
                if any(cell.text.strip() for cell in row)
            )
            if rows:
                bbox = _docling_bbox(provenance[0].bbox)
                tables_by_page.setdefault(page_number, []).append(PdfTable(page_number, rows, bbox))
                text_by_page.setdefault(page_number, []).extend(
                    " ".join(cell for cell in row if cell).strip() for row in rows
                )
            continue
        text = str(getattr(item, "text", "")).strip()
        if text:
            text_by_page.setdefault(page_number, []).append(text)

    page_numbers_found = sorted(set(text_by_page) | set(tables_by_page))
    return [
        PdfPageText(
            page_number=page_number,
            text="\n".join(text_by_page.get(page_number, [])),
            tables=tuple(tables_by_page.get(page_number, [])),
            extraction_backend=f"docling_{mode}",
        )
        for page_number in page_numbers_found
    ]


def _docling_bbox(bbox: Any) -> tuple[float, float, float, float] | None:
    if bbox is None:
        return None
    return (float(bbox.l), float(bbox.t), float(bbox.r), float(bbox.b))


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}

