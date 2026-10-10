from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PdfPageText:
    page_number: int
    text: str


def extract_pdf_text_pages(
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

