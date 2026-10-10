from __future__ import annotations

import unittest
from pathlib import Path

from scripts.reconcile_phase_b2 import read_rows, evaluate_inventory, reference_comparison
from src.tender_pricing.data_loading import load_project_data
from src.tender_pricing.pdf_ingestion import extract_pdf_text_pages, PdfPageText
from src.tender_pricing.position_parser import parse_lv_positions, parse_page_positions
from src.tender_pricing.product_matching import classify_position

ROOT = Path(__file__).resolve().parents[1]


class PhaseB2MatchingTests(unittest.TestCase):
    def classify(self, text):
        data = load_project_data(ROOT)
        return [classify_position(p, {r['product_id']: r for r in data['catalog']},
                                 {r['install_code']: r for r in data['productivity']}, data['parameters'])
                for p in parse_page_positions(PdfPageText(1, text))]

    def test_local_insulation_thickness_does_not_inherit_previous_variant(self):
        rows = self.classify('Thermische Aussendämmung 30/5\naus 30 mm Mineralwolle\nmit Alu-Folie m2 52\nThermische Aussendämmung 60/10\naus 60 mm Mineralwolle\nmit Alu-Folie m2 12')
        self.assertEqual([r['matched_product_id'] for r in rows], ['P-INS-001', 'P-INS-002'])
        self.assertTrue(all(r['status'] == 'calculated' for r in rows))
        self.assertTrue(all('material_cost_chf' not in r for r in rows))

    def test_local_tvr_variants_with_shared_context(self):
        rows = self.classify('Typ TVR-D\nMod. DN Vmin Vmax\ncm m3/h m3/h Pa\nTVR-D 12.5 60 200 150 Stk 10\nTVR-D 16 120 400 150 Stk 6\nTVR-D 20 180 600 150 Stk 12')
        self.assertEqual([r['matched_product_id'] for r in rows], ['P-VAV-003', 'P-VAV-004', 'P-VAV-005'])

    def test_round_seal_local_geometry_wins_over_previous_rectangular_row(self):
        rows = self.classify('Durchdringungen EI30\nAbmessungen B x H (mm)\n300 x 200 Stk 4\nDurchdringungen durch Wände\nfür runde Rohre EI30\nGrösse 16 Ø cm Stk 8')
        self.assertEqual([r['matched_product_id'] for r in rows], ['P-FIR-002', 'P-FIR-003'])
        self.assertTrue(all(r['status'] == 'calculated' for r in rows))

    def test_mismatch_safety_is_preserved(self):
        row = self.classify('Abluft - Tellerventil\nGrösse Ø 12.5 cm Stk 6')[0]
        self.assertEqual(row['status'], 'review_required')
        self.assertIn('diameter_mismatch', {f['code'] for f in row['conflict_flags']})

    def test_identical_dimension_lines_do_not_turn_expansion_sleeve_into_fire_damper(self):
        rows = self.classify('Brandschutzklappe EI 90-S\nTyp FKRS-EU\nGrösse 10 Ø cm Stk 4\nEinseitig Dehnungsmanschette mit Potentialausgleich\nPVC beschichtetes Polyestergewebe\nGrösse 10 Ø cm Stk 4')
        self.assertEqual(rows[0]['matched_product_id'], 'P-FIR-001')
        self.assertIsNone(rows[1]['matched_product_id'])

    def test_all_reference_primary_products_and_source_supported_statuses(self):
        data = load_project_data(ROOT)
        pages = sorted({int(r['source_page']) for r in data['examples']})
        try:
            positions = parse_lv_positions(extract_pdf_text_pages(ROOT / 'BKP_244_LV_Lueftung_260804.pdf', pages))
        except RuntimeError as error:
            self.skipTest(str(error))
        corrected = [r for r in read_rows(ROOT / 'outputs/phase8h_extraction_correction/corrected_candidates.jsonl') if r['pdf_page'] in pages]
        excluded = [r for r in read_rows(ROOT / 'outputs/phase8h_extraction_correction/excluded_false_positives.jsonl') if r['pdf_page'] in pages]
        results = evaluate_inventory(corrected, excluded, positions, data)
        comparisons = reference_comparison(data, results)
        self.assertEqual(len(comparisons), 22)
        exceptions = {'LV0009': 'model_length_conflict', 'LV0021': 'quantity_basis_requires_confirmation'}
        for row in comparisons:
            with self.subTest(reference=row['reference_id']):
                self.assertEqual(row['actual_product_id'], row['expected_product_id'])
                if row['reference_id'] in exceptions:
                    self.assertEqual(row['actual_status'], 'review_required')
                    self.assertIn(exceptions[row['reference_id']], {f['code'] for f in row['conflicts']})
                else:
                    self.assertEqual(row['actual_status'], row['expected_status'])
                self.assertIsNotNone(row['source_line'])
        for row in results:
            self.assertNotIn('direct_position_cost_chf', row)
            self.assertFalse(row['pricing_authorized'])


if __name__ == '__main__':
    unittest.main()
