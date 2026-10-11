from __future__ import annotations

import json
import io
import shutil
import tempfile
import unittest
from pathlib import Path

from src.tender_pricing.pdf_overlay import (
    PRICE_CELL_INNER_MARGIN,
    TEXT_SIZE,
    eligible_overlay_positions,
    map_price_cells,
    write_mapping_json,
    write_overlay_prototype,
    extract_line_boxes,
    _line_match_score,
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

    def test_multiple_positions_cannot_share_one_price_row(self) -> None:
        row = eligible_overlay_positions(self.rows, {78})[0]
        duplicate = {**row, "lv_id": "DUPLICATE-ROW"}

        mappings = map_price_cells(SOURCE_PDF, [row, duplicate], {78})

        self.assertEqual(
            {mapping.placement_status for mapping in mappings},
            {"ambiguous_cell_collision"},
        )
        self.assertTrue(all(mapping.position_total_chf is None for mapping in mappings))

    def test_oversized_price_is_skipped_instead_of_clipped(self) -> None:
        row = eligible_overlay_positions(self.rows, {78})[0].copy()
        row["accepted_direct_position_cost_chf"] = 999999999999.99
        row["direct_position_cost_chf"] = 999999999999.99
        mapping, = map_price_cells(SOURCE_PDF, [row], {78})
        self.assertEqual(mapping.placement_status, "price_text_does_not_fit")
        self.assertIsNone(mapping.unit_price_chf)

    def test_mapped_text_boxes_are_inset_inside_price_cells(self) -> None:
        eligible = eligible_overlay_positions(self.rows, {78, 107})
        mappings = map_price_cells(SOURCE_PDF, eligible, {78, 107})

        mapped = [mapping for mapping in mappings if mapping.placement_status == "mapped"]
        self.assertGreater(len(mapped), 0)
        for mapping in mapped:
            self.assertGreaterEqual(mapping.font_size, 7.0)
            self.assertLessEqual(mapping.font_size, TEXT_SIZE)
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
            self.assertGreaterEqual(
                mapping.unit_price_text_bbox["y0"],
                mapping.unit_price_cell_bbox["y0"],
            )
            self.assertLessEqual(
                mapping.unit_price_text_bbox["y1"],
                mapping.unit_price_cell_bbox["y1"],
            )
            self.assertGreaterEqual(
                mapping.total_price_text_bbox["y0"],
                mapping.total_price_cell_bbox["y0"],
            )
            self.assertLessEqual(
                mapping.total_price_text_bbox["y1"],
                mapping.total_price_cell_bbox["y1"],
            )

    def test_overlay_adapts_to_source_text_near_nine_to_ten_points(self) -> None:
        eligible = eligible_overlay_positions(self.rows, {78})
        mappings = map_price_cells(SOURCE_PDF, eligible, {78})

        mapped = [mapping for mapping in mappings if mapping.placement_status == "mapped"]
        self.assertGreater(len(mapped), 0)
        self.assertTrue(all(9.0 <= mapping.font_size <= 10.0 for mapping in mapped))

    def test_smaller_source_text_produces_a_smaller_overlay_font(self) -> None:
        from reportlab.pdfgen import canvas

        row = eligible_overlay_positions(self.rows, {78})[0]
        temp_dir = Path(tempfile.mkdtemp(prefix=".pdf-overlay-font-test-", dir=PROJECT_ROOT))
        try:
            path = temp_dir / "small-text.pdf"
            pdf = canvas.Canvas(str(path))
            for x in (440.2, 488.3, 562.0):
                pdf.line(x, 40, x, 800)
            pdf.setFont("Helvetica", 8)
            pdf.drawString(40, 700, row["source_line"])
            pdf.save()

            mapping, = map_price_cells(path, [{**row, "source_page": 1}], {1})

            self.assertEqual(mapping.placement_status, "mapped")
            self.assertLess(mapping.font_size, TEXT_SIZE)
            self.assertGreaterEqual(mapping.font_size, 7.0)
            self.assertLessEqual(mapping.font_size, 8.0)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_adjacent_rows_use_their_own_source_baselines(self) -> None:
        eligible = eligible_overlay_positions(self.rows, {78})
        mappings = {mapping.lv_id: mapping for mapping in map_price_cells(SOURCE_PDF, eligible, {78})}

        first = mappings["PDF078-06"]
        second = mappings["PDF078-07"]
        self.assertEqual(first.placement_status, "mapped")
        self.assertEqual(second.placement_status, "mapped")
        self.assertAlmostEqual(first.baseline_y, 147.24, places=2)
        self.assertAlmostEqual(second.baseline_y, 135.24, places=2)
        self.assertAlmostEqual(first.baseline_y - second.baseline_y, 12.0, places=2)
        self.assertEqual(first.position_total_chf, 806.26)
        self.assertEqual(second.position_total_chf, 1038.90)

    def test_line_boxes_preserve_pdf_text_matrix_geometry(self) -> None:
        import pdfplumber

        with pdfplumber.open(SOURCE_PDF) as document:
            lines = extract_line_boxes(document.pages[77])
        row = next(line for line in lines if "Stk 5" in line.text and "10 cm" in line.text)

        self.assertAlmostEqual(row.font_size, 10.02, places=2)
        self.assertAlmostEqual(row.baseline_y, 147.24, places=2)
        self.assertAlmostEqual(row.pdf_y0, 145.1358, places=3)
        self.assertAlmostEqual(row.pdf_y1, 155.1558, places=3)

    def test_missing_price_column_geometry_is_not_replaced_with_fixed_coordinates(self) -> None:
        from reportlab.pdfgen import canvas

        row = eligible_overlay_positions(self.rows, {78})[0]
        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer)
        pdf.drawString(40, 700, row["source_line"])
        pdf.save()
        temp_dir = Path(tempfile.mkdtemp(prefix=".pdf-overlay-geometry-test-", dir=PROJECT_ROOT))
        try:
            path = temp_dir / "borderless.pdf"
            path.write_bytes(buffer.getvalue())
            mapping, = map_price_cells(path, [{**row, "source_page": 1}], {1})
            self.assertEqual(mapping.placement_status, "price_columns_not_found")
            self.assertIsNone(mapping.unit_price_right_x)
            self.assertIsNone(mapping.total_price_right_x)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_rotated_page_is_left_unmodified_without_validated_transform(self) -> None:
        from pypdf import PdfReader, PdfWriter
        from reportlab.pdfgen import canvas

        row = eligible_overlay_positions(self.rows, {78})[0]
        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer)
        for x in (440.2, 488.3, 562.0):
            pdf.line(x, 40, x, 800)
        pdf.drawString(40, 700, row["source_line"])
        pdf.save()
        temp_dir = Path(tempfile.mkdtemp(prefix=".pdf-overlay-rotation-test-", dir=PROJECT_ROOT))
        try:
            source = temp_dir / "source.pdf"
            rotated = temp_dir / "rotated.pdf"
            source.write_bytes(buffer.getvalue())
            reader = PdfReader(str(source))
            writer = PdfWriter()
            writer.add_page(reader.pages[0].rotate(90))
            with rotated.open("wb") as output:
                writer.write(output)

            mapping, = map_price_cells(rotated, [{**row, "source_page": 1}], {1})
            self.assertEqual(mapping.placement_status, "unsupported_page_rotation")
            self.assertIsNone(mapping.position_total_chf)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_nonzero_media_box_origin_is_left_blank(self) -> None:
        from pypdf import PdfReader, PdfWriter
        from reportlab.pdfgen import canvas

        row = eligible_overlay_positions(self.rows, {78})[0]
        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer)
        for x in (440.2, 488.3, 562.0):
            pdf.line(x, 40, x, 800)
        pdf.drawString(40, 700, row["source_line"])
        pdf.save()
        temp_dir = Path(tempfile.mkdtemp(prefix=".pdf-overlay-origin-test-", dir=PROJECT_ROOT))
        try:
            source = temp_dir / "source.pdf"
            shifted = temp_dir / "shifted.pdf"
            source.write_bytes(buffer.getvalue())
            reader = PdfReader(str(source))
            page = reader.pages[0]
            page.mediabox.lower_left = (10, 20)
            writer = PdfWriter()
            writer.add_page(page)
            with shifted.open("wb") as output:
                writer.write(output)

            mapping, = map_price_cells(shifted, [{**row, "source_page": 1}], {1})
            self.assertEqual(mapping.placement_status, "unsupported_page_coordinate_system")
            self.assertIsNone(mapping.position_total_chf)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

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

    def test_row_anchor_is_not_tied_to_german_unit_word(self) -> None:
        self.assertGreaterEqual(
            _line_match_score('Grösse Ø 10 cm Stück 5', 'Grösse Ø 10 cm pcs 5', 5),
            60,
        )
        self.assertEqual(
            _line_match_score('Grösse Ø 10 cm Stück 5', 'Grösse Ø 10 cm pcs 6', 5),
            0,
        )
        self.assertEqual(
            _line_match_score('mit Alu-Folie, gestiftet m2 52', 'mit Alu-Folie, gestiftet', 52),
            0,
        )


if __name__ == "__main__":
    unittest.main()
