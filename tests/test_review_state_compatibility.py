from __future__ import annotations

import unittest
from pathlib import Path

from src.tender_pricing.data_loading import load_project_data
from src.tender_pricing.pdf_ingestion import PdfPageText
from src.tender_pricing.position_parser import parse_page_positions
from src.tender_pricing.review_state import _position_from_row, apply_position_review

ROOT = Path(__file__).resolve().parents[1]


class ReviewStateCompatibilityTests(unittest.TestCase):
    def test_parser_record_types_round_trip_through_review_reconstruction(self):
        fixtures = {
            'tender_position': 'Zuluft - Tellerventil\nGrösse Ø 10 cm Stk 5',
            'labour_service': 'Servicearbeiten Std. 21',
            'tender_position_missing_quantity': 'Zuluftgerät 1-1 Stk',
            'component_list_row': 'Bauteilliste Lüftung\nAuflistung der Kanalformstücke\nStk KZ Formteil\n2 BA Bogen asymmetrisch 236 612 300 90',
        }
        for expected_type, text in fixtures.items():
            with self.subTest(record_type=expected_type):
                position, = parse_page_positions(PdfPageText(1, text))
                self.assertEqual(position.record_type, expected_type)
                reconstructed = _position_from_row(position.to_dict())
                self.assertEqual(reconstructed, position)

    def test_explicit_source_record_type_survives_edited_unit(self):
        position, = parse_page_positions(PdfPageText(1, 'Servicearbeiten Std. 21'))
        row = {**position.to_dict(), 'unit': 'pc'}
        self.assertEqual(_position_from_row(row).record_type, 'labour_service')

    def test_legacy_record_type_uses_original_unit_with_parser_semantics(self):
        for text, expected in [('Grösse Ø 10 cm Stk 5', 'tender_position'), ('Servicearbeiten Std. 21', 'labour_service')]:
            with self.subTest(text=text):
                position, = parse_page_positions(PdfPageText(1, text))
                row = position.to_dict()
                row.pop('record_type')
                row['unit'] = 'pc'
                self.assertEqual(_position_from_row(row).record_type, expected)
                self.assertNotIn('record_type', row)

    def test_legacy_review_recalculates_without_adding_record_type_to_payload(self):
        position, = parse_page_positions(PdfPageText(1, 'Zuluft - Tellerventil\nGrösse Ø 10 cm Stk 5'))
        row = {**position.to_dict(), 'matched_product_id': 'P-AIR-001', 'status': 'calculated'}
        row.pop('record_type')
        result = apply_position_review(row, {'quantity': 10}, load_project_data(ROOT))
        self.assertEqual(result['status'], 'calculated')
        self.assertTrue(result['pricing_authorized'])
        self.assertEqual(result['quantity'], 10)
        self.assertEqual(result['accepted_direct_position_cost_chf'], result['direct_position_cost_chf'])
        self.assertNotIn('record_type', result)
        self.assertNotIn('record_type', row)


if __name__ == '__main__':
    unittest.main()
