from pathlib import Path
import unittest
from unittest.mock import patch

from src.tender_pricing.pdf_ingestion import PdfPageText, extract_pdf_text_pages


class DoclingFallbackTests(unittest.TestCase):
    def test_hybrid_falls_back_to_pdfplumber_when_docling_fails(self) -> None:
        expected = [PdfPageText(page_number=1, text="Stk. 2")]
        with (
            patch(
                "src.tender_pricing.pdf_ingestion._extract_pdfplumber_pages",
                return_value=expected,
            ),
            patch(
                "src.tender_pricing.pdf_ingestion.extract_docling_pages",
                side_effect=RuntimeError("Docling unavailable"),
            ),
        ):
            actual = extract_pdf_text_pages(Path("fixture.pdf"), backend="hybrid")

        self.assertEqual(actual, expected)

    def test_pdfplumber_backend_never_imports_or_calls_docling(self) -> None:
        expected = [PdfPageText(page_number=1, text="Std. 21")]
        with (
            patch(
                "src.tender_pricing.pdf_ingestion._extract_pdfplumber_pages",
                return_value=expected,
            ),
            patch("src.tender_pricing.pdf_ingestion.extract_docling_pages") as docling,
        ):
            actual = extract_pdf_text_pages(Path("fixture.pdf"), backend="pdfplumber")

        self.assertEqual(actual, expected)
        docling.assert_not_called()

    def test_hybrid_keeps_pdfplumber_text_and_adds_docling_structure(self) -> None:
        primary = [PdfPageText(page_number=1, text="primary")]
        structured = [
            PdfPageText(page_number=1, text="structured", extraction_backend="docling_standard")
        ]
        with (
            patch(
                "src.tender_pricing.pdf_ingestion._extract_pdfplumber_pages",
                return_value=primary,
            ),
            patch(
                "src.tender_pricing.pdf_ingestion.extract_docling_pages",
                return_value=structured,
            ),
        ):
            actual = extract_pdf_text_pages(Path("fixture.pdf"), backend="hybrid")

        self.assertEqual(actual[0].text, "primary")
        self.assertEqual(actual[0].structured_text, "structured")
        self.assertEqual(actual[0].extraction_backend, "hybrid")


if __name__ == "__main__":
    unittest.main()
