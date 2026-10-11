from pathlib import Path
import unittest

from src.tender_pricing.data_loading import load_project_data
from src.tender_pricing.pdf_ingestion import PdfPageText, extract_pdf_text_pages
from src.tender_pricing.position_parser import parse_page_positions
from src.tender_pricing.product_matching import classify_position
from src.tender_pricing.ai_matching_experiment import (
    FakeAIProvider,
    build_position_input,
    retrieve_catalogue_candidates,
    run_ai_matching_case,
)


ROOT = Path(__file__).resolve().parents[1]


class ParserMatcherImprovementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = load_project_data(ROOT)
        cls.catalog = {r['product_id']: r for r in data['catalog']}
        cls.productivity = {r['install_code']: r for r in data['productivity']}
        cls.parameters = data['parameters']
        cls.examples = data['examples']

    def classify(self, text):
        return [classify_position(p, self.catalog, self.productivity, self.parameters)
                for p in parse_page_positions(PdfPageText(110, text))]

    def test_decimal_comma_selects_exact_valve_diameter(self):
        row = self.classify('Zuluft - Tellerventil\nGr\u00f6sse \u00d8 12,5 cm Stk 6')[0]
        self.assertEqual(row['matched_product_id'], 'P-AIR-002')
        self.assertEqual(row['status'], 'calculated')
        self.assertEqual(row['technical_attributes']['diameters'][0]['value_mm'], 125)
        self.assertIn('12,5', row['original_description'])

    def test_quantity_is_not_a_valve_diameter(self):
        row = self.classify('Zuluft - Tellerventil\nStk 10')[0]
        self.assertNotEqual(row['status'], 'calculated')

    def test_pressure_and_flow_are_not_controller_diameters(self):
        for line in ('VFC 8 40-100 250 Stk 12', 'VFC 12.5 250 50 Stk 2'):
            with self.subTest(line=line):
                row = self.classify('Einkanal-Volumenstromregler\nTyp VFC\nMod. DN V DP\ncm m3/h Pa\n' + line)[0]
                self.assertIsNone(row['matched_product_id'])

    def test_supported_controller_requires_local_diameter_evidence(self):
        row = self.classify('Einkanal-Volumenstromregler\nTyp VFC\nDN250 Stk 2')[0]
        self.assertEqual(row['matched_product_id'], 'P-CAV-001')
        self.assertEqual(row['status'], 'calculated')

    def test_german_controls_are_review_candidates_only(self):
        for term, product in (('Kanaltemperaturf\u00fchler', 'P-CTL-002'),
                              ('Druckdifferenzf\u00fchler', 'P-CTL-001'),
                              ('Volumenstromf\u00fchler', 'P-CTL-004')):
            with self.subTest(term=term):
                row = self.classify(term + ' Stk. 6')[0]
                self.assertEqual(row['matched_product_id'], product)
                self.assertEqual(row['status'], 'review_required')
                self.assertLess(row['match_confidence'], 0.85)

    def test_replacement_character_in_hvac_sensor_terms_is_repaired_narrowly(self):
        cases = (
            ('Kanaltemperaturf�hler Stk 6', 'P-CTL-002'),
            ('Druckdifferenzf�hler Stk 2', 'P-CTL-001'),
        )
        for text, expected_product in cases:
            with self.subTest(text=text):
                row = self.classify(text)[0]
                self.assertEqual(row['matched_product_id'], expected_product)
                self.assertEqual(row['status'], 'review_required')

    def test_ai_candidate_retrieval_uses_local_family_not_cumulative_context(self):
        position = build_position_input({
            'lv_id': 'DE-CONTROL-1',
            'source_page': 82,
            'source_language': 'de',
            'original_description': (
                'Brandschutzklappe EI90 Stk 1 vorherige Position '
                'Kanaltemperaturf�hler Stk 6'
            ),
            'source_line': 'Kanaltemperaturf�hler Stk 6',
            'quantity': 6,
            'unit': 'pc',
            'technical_attributes': {},
            'status': 'insufficient_information',
        })
        candidates = retrieve_catalogue_candidates(
            position, list(self.catalog.values()), max_candidates=5
        )

        self.assertEqual(candidates[0]['product_id'], 'P-CTL-002')
        self.assertNotIn('P-FIR-001', {row['product_id'] for row in candidates})

    def test_combined_sensor_and_switch_are_not_generic_transmitters(self):
        for term in ('Kanaltemperatur- und Feuchtef\u00fchler', 'Druckw\u00e4chter', 'Frostschutzw\u00e4chter, 2-Punkt'):
            with self.subTest(term=term):
                row = self.classify(term + ' Stk 6')[0]
                self.assertIsNone(row['matched_product_id'])

    def test_unsupported_local_component_family_does_not_inherit_prior_context(self):
        cases = (
            'Drehantrieb AC/DC 24 V Stk 2\nKanalrauchmelder Stk 1',
            'Lüftungsrohr Ø 250 mm Stk 4\nVerbindungsmanschette Stk 2',
            'Ventilator 10500 m3/h Stk 1\nLeerteil Stk 1',
        )
        for text in cases:
            with self.subTest(text=text):
                row = self.classify(text)[-1]
                self.assertIsNone(row['matched_product_id'])
                self.assertEqual(row['status'], 'insufficient_information')

    def test_adjacent_voltage_is_preserved_without_inheriting_other_device(self):
        rows = self.classify('Drehantrieb, 20 Nm, Stk. 2\nAC/DC 24 V, Auf/Zu, 3-Punkt, 150 s, IP54\nDrehantrieb, 5 Nm Stk. 1\nAC 230 V, Auf/Zu')
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['matched_product_id'], 'P-CTL-003')
        self.assertEqual(rows[0]['status'], 'review_required')
        self.assertIn('AC/DC 24 V', rows[0]['evidence'])
        self.assertIsNone(rows[1]['matched_product_id'])
        self.assertNotIn('24 V', rows[1]['original_description'])
        self.assertEqual(rows[0]['source_line'], 'Drehantrieb, 20 Nm, Stk. 2')
        self.assertEqual(rows[0]['source_page'], 110)

    def test_missing_actuator_voltage_is_not_invented(self):
        self.assertIsNone(self.classify('Drehantrieb, 20 Nm, Stk. 2')[0]['matched_product_id'])

    def test_fire_rating_alone_does_not_identify_fire_damper(self):
        row = self.classify('Brandschutzmanschette EI 90 Stk 2')[0]
        self.assertNotEqual(row['status'], 'calculated')

    def test_actual_page_110_controls_preserve_source_and_remain_review_only(self):
        page = extract_pdf_text_pages(ROOT / 'BKP_244_LV_Lueftung_260804.pdf', [110])[0]
        rows = [classify_position(p, self.catalog, self.productivity, self.parameters)
                for p in parse_page_positions(page)]
        actuator = next(r for r in rows if r['source_line'].startswith('Drehantrieb, 20'))
        self.assertEqual(actuator['matched_product_id'], 'P-CTL-003')
        self.assertIn('AC/DC 24 V', actuator['original_description'])
        self.assertEqual(actuator['status'], 'review_required')
        self.assertEqual(actuator['source_page'], 110)
        combined = next(r for r in rows if r['source_line'].startswith('Kanaltemperatur-'))
        self.assertIsNone(combined['matched_product_id'])

    def test_french_semantic_retrieval_is_catalogue_bounded_and_dimension_aware(self):
        position = build_position_input({
            'lv_id': 'FR-1',
            'source_page': 1,
            'source_language': 'fr',
            'original_description': 'Bouche de soufflage en plastique DN125',
            'source_line': 'Bouche de soufflage DN125 pièces 6',
            'quantity': 6,
            'unit': 'pc',
            'technical_attributes': {'diameters': [{'value_mm': 125}]},
            'status': 'insufficient_information',
        })
        candidates = retrieve_catalogue_candidates(position, list(self.catalog.values()), max_candidates=5)
        self.assertEqual(candidates[0]['product_id'], 'P-AIR-002')
        self.assertTrue({row['product_id'] for row in candidates} <= set(self.catalog))

    def test_semantic_exact_technical_match_can_calculate(self):
        row = self.classify('Bouche de soufflage DN125 pièces 6')[0]
        self.assertEqual(row['matched_product_id'], 'P-AIR-002')
        self.assertEqual(row['match_method'], 'multilingual_exact_technical_match')
        self.assertEqual(row['status'], 'calculated')

    def test_semantic_match_without_exact_technical_evidence_stays_review_only(self):
        row = self.classify('Bouche de soufflage pièces 6')[0]
        self.assertEqual(row['matched_product_id'], 'P-AIR-001')
        self.assertEqual(row['match_method'], 'multilingual_semantic_candidate')
        self.assertEqual(row['status'], 'review_required')

    def test_semantic_dimension_mismatch_stays_review_only(self):
        row = self.classify('Bouche de soufflage DN160 pièces 6')[0]
        self.assertNotEqual(row['status'], 'calculated')
        self.assertTrue(row['conflict_flags'])

    def test_bend_angle_mismatch_cannot_be_calculated(self):
        row = self.classify('Lüftungsrohr Ø 250 mm, Bogen 45° Stk 2')[0]

        self.assertEqual(row['matched_product_id'], 'P-FTG-B-250-90')
        self.assertEqual(row['status'], 'review_required')
        self.assertIn(
            'bend_angle_mismatch',
            {flag['code'] for flag in row['conflict_flags']},
        )

    def test_special_polyurethane_duct_is_not_equated_to_galvanized_fitting(self):
        row = self.classify(
            'Lüftungsrohr für Erdverlegung aus Polyurethan Hartschaum '
            'Ø 250 mm, Bogen 90° Stk 8'
        )[0]

        self.assertNotEqual(row['status'], 'calculated')

    def test_mineral_wool_compound_keeps_supported_insulation_match(self):
        row = self.classify(
            'Thermische Aussendämmung aus 30 mm Mineralwollplatten '
            'mit Drahtgeflecht aus V2A m2 20'
        )[0]

        self.assertEqual(row['matched_product_id'], 'P-INS-001')
        self.assertEqual(row['status'], 'calculated')

    def test_french_exact_technical_families_match_without_external_translation(self):
        cases = (
            ('Clapet coupe-feu EI90-S DN100 pièces 4', 'P-FIR-001'),
            ('Isolation de gaine en laine minérale 60 mm m² 12', 'P-INS-002'),
            ('Régulateur de débit variable DN160 pièces 6', 'P-VAV-004'),
        )
        for text, expected_product in cases:
            with self.subTest(text=text):
                row = self.classify(text)[0]
                self.assertEqual(row['matched_product_id'], expected_product)
                self.assertEqual(row['status'], 'calculated')
                self.assertEqual(row['match_method'], 'multilingual_exact_technical_match')

    def test_verified_english_references_have_no_false_product_matches(self):
        results = []
        for reference in self.examples:
            text = f"{reference['description']} {reference['unit']} {reference['quantity']}"
            position = parse_page_positions(PdfPageText(int(reference['source_page']), text))[0]
            results.append(
                (
                    reference,
                    classify_position(
                        position,
                        self.catalog,
                        self.productivity,
                        self.parameters,
                    ),
                )
            )

        self.assertEqual(
            [row['matched_product_id'] for _reference, row in results],
            [reference['suggested_product_id'] for reference, _row in results],
        )
        self.assertEqual(sum(row['status'] == 'calculated' for _reference, row in results), 15)
        self.assertEqual(sum(row['status'] == 'supplier_quote_required' for _reference, row in results), 6)
        review = [reference['lv_id'] for reference, row in results if row['status'] == 'review_required']
        self.assertEqual(review, ['LV0021'])

    def test_provider_accept_cannot_bypass_review_or_catalogue_validation(self):
        position = parse_page_positions(PdfPageText(1, 'Bouche de soufflage DN125 pièces 6'))[0]
        row = classify_position(
            position,
            self.catalog,
            self.productivity,
            self.parameters,
            FakeAIProvider(decision='accept', recommended_product_id='P-AIR-002'),
        )
        self.assertEqual(row['matched_product_id'], 'P-AIR-002')
        self.assertEqual(row['status'], 'review_required')
        self.assertEqual(row['match_method'], 'validated_ai_candidate_review')

        case = run_ai_matching_case(
            build_position_input(row),
            list(self.catalog.values()),
            FakeAIProvider(decision='accept', recommended_product_id='NOT-IN-CATALOG'),
        )
        self.assertIsNotNone(case['validation_error'])
        self.assertIsNone(case['ai_result'])


if __name__ == '__main__':
    unittest.main()
