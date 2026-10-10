from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from src.tender_pricing.pdf_overlay import (
    PRICE_CELL_INNER_MARGIN,
    eligible_overlay_positions,
    map_price_cells,
    write_mapping_json,
    write_overlay_prototype,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PDF = PROJECT_ROOT / "BKP_244_LV_Lueftung_260804.pdf"
PRICED_POSITIONS = PROJECT_ROOT / "outputs" / "phase2_full" / "priced_positions.json"


class PdfOverlayPrototypeTests(unittest.TestCase):
    def setUp(self) -> None:
        if not SOURCE_PDF.exists() or not PRICED_POSITIONS.exists():
            self.skipTest("Phase 8E PDF overlay fixtures are not available.")
        try:
            import pdfplumber  # noqa: F401
            import pypdf  # noqa: F401
            import reportlab  # noqa: F401
        except ModuleNotFoundError as exc:
            self.skipTest(f"PDF overlay dependencies are unavailable: {exc.name}")
        self.rows = json.loads(PRICED_POSITIONS.read_text(encoding="utf-8"))

    def test_overlay_eligibility_excludes_supplier_and_review_rows(self) -> None:
        eligible = eligible_overlay_positions(self.rows, {107, 169})

        ids = {row["lv_id"] for row in eligible}
        self.assertIn("PDF107-01", ids)
        self.assertIn("PDF169-01", ids)
        self.assertNotIn("PDF107-04", ids)
        self.assertNotIn("PDF169-04", ids)
        self.assertTrue(all(row["status"] == "calculated" for row in eligible))

    def test_mapping_flags_duplicate_source_line_without_guessing(self) -> None:
        eligible = eligible_overlay_positions(self.rows, {79})
        mappings = map_price_cells(SOURCE_PDF, eligible, {79})

        by_id = {mapping.lv_id: mapping for mapping in mappings}
        self.assertEqual(by_id["PDF079-01"].placement_status, "mapped")
        self.assertEqual(by_id["PDF079-03"].placement_status, "ambiguous_line_match")
        self.assertIsNone(by_id["PDF079-03"].position_total_chf)

    def test_mapped_text_boxes_are_inset_inside_price_cells(self) -> None:
        eligible = eligible_overlay_positions(self.rows, {78, 107})
        mappings = map_price_cells(SOURCE_PDF, eligible, {78, 107})

        mapped = [mapping for mapping in mappings if mapping.placement_status == "mapped"]
        self.assertGreater(len(mapped), 0)
        for mapping in mapped:
            self.assertIsNotNone(mapping.unit_price_cell_bbox)
            self.assertIsNotNone(mapping.total_price_cell_bbox)
            self.assertIsNotNone(mapping.unit_price_text_bbox)
            self.assertIsNotNone(mapping.total_price_text_bbox)
            self.assertGreaterEqual(
                mapping.unit_price_text_bbox["x0"],
                mapping.unit_price_cell_bbox["x0"] + PRICE_CELL_INNER_MARGIN,
            )
            self.assertLessEqual(
                mapping.unit_price_text_bbox["x1"],
                mapping.unit_price_cell_bbox["x1"] - PRICE_CELL_INNER_MARGIN,
            )
            self.assertGreaterEqual(
                mapping.total_price_text_bbox["x0"],
                mapping.total_price_cell_bbox["x0"] + PRICE_CELL_INNER_MARGIN,
            )
            self.assertLessEqual(
                mapping.total_price_text_bbox["x1"],
                mapping.total_price_cell_bbox["x1"] - PRICE_CELL_INNER_MARGIN,
            )

    def test_overlay_pdf_preserves_selected_page_count_and_mapping_values(self) -> None:
        temp_dir = Path(tempfile.mkdtemp(prefix=".pdf-overlay-test-", dir=PROJECT_ROOT))
        try:
            eligible = eligible_overlay_positions(self.rows, {78})
            mappings = map_price_cells(SOURCE_PDF, eligible, {78})
            output_pdf = temp_dir / "prototype.pdf"
            mapping_json = temp_dir / "mapping.json"

            write_overlay_prototype(source_pdf=SOURCE_PDF, output_pdf=output_pdf, mappings=mappings, pages=[78])
            write_mapping_json(mapping_json, mappings, [78])

            from pypdf import PdfReader

            self.assertEqual(len(PdfReader(str(output_pdf)).pages), 1)
            payload = json.loads(mapping_json.read_text(encoding="utf-8"))
            mapped = {row["lv_id"]: row for row in payload["mappings"]}
            self.assertEqual(mapped["PDF078-06"]["unit_price_chf"], 161.25)
            self.assertEqual(mapped["PDF078-06"]["position_total_chf"], 806.26)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
