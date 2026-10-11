from __future__ import annotations

import unittest
from pathlib import Path

from src.tender_pricing.data_loading import load_project_data
from src.tender_pricing.pdf_ingestion import PdfPageText, extract_pdf_text_pages
from src.tender_pricing.position_parser import parse_lv_positions, parse_page_positions
from src.tender_pricing.product_matching import match_positions


PROJECT_ROOT = Path(__file__).resolve().parents[1]


PAGE_78_TEXT = """
SH Erlenstrasse Oberglatt 244.01 LA01 Nebenraeume Seite 10 / 20
Pos. Gegenstand Mass- Mass- Einheits- Betrag
Gattg. betrag Preis Fr.
Zuluft - Tellerventil
aus Kunststoff, mit Luftmengeneinstellung
Fabrikat z.B Trox Hesco
Typ z.B Z-LVS
Farbe NCS nach Wunsch des Architekten
Groesse ? 10 cm Stk 5
? 12.5 cm Stk 6
"""


PAGE_169_TEXT = """
SH Erlenstrasse Oberglatt 244.04 Schulzimmer OG Seite 20 / 24
F DAEMMUNGEN
Thermische Aussendaemmung 30/5
aus 30 mm Mineralwollmatten
mit Alu-Folie, gestiftet m2 52
Thermische Aussendaemmung 60/10
aus 60 mm Mineralwollplatten
mit Alu-Folie, gestiftet m2 12
Thermische Aussendaemmung 100/15
aus 100 mm Mineralwollplatten
Wetterfeste Ummantelung V2A inkl. Abdichtung m2 440
"""


class Phase2ExtractionTests(unittest.TestCase):
    def test_parser_preserves_page_system_quantity_and_units(self) -> None:
        positions = parse_page_positions(PdfPageText(page_number=78, text=PAGE_78_TEXT))
        self.assertGreaterEqual(len(positions), 2)
        first = positions[0]
        self.assertEqual(first.source_page, 78)
        self.assertEqual(first.system, "244.01 LA01 Nebenraeume")
        self.assertEqual(first.quantity, 5.0)
        self.assertEqual(first.unit, "pc")
        self.assertEqual(first.source_language, "de")
        self.assertEqual(first.original_description, first.description)
        self.assertIn("Tellerventil", first.description)
        self.assertIn("? 10 cm", first.description)
        self.assertEqual(first.technical_attributes["diameters"][0]["value_mm"], 100.0)

    def test_matching_prices_known_air_terminal_fixture(self) -> None:
        data = load_project_data(PROJECT_ROOT)
        positions = parse_page_positions(PdfPageText(page_number=78, text=PAGE_78_TEXT))
        priced = match_positions(positions, data["catalog"], data["productivity"], data["parameters"])
        by_quantity = {row["quantity"]: row for row in priced}

        self.assertEqual(by_quantity[5.0]["matched_product_id"], "P-AIR-001")
        self.assertEqual(by_quantity[5.0]["status"], "calculated")
        self.assertEqual(by_quantity[5.0]["match_method"], "deterministic_cross_language")
        self.assertEqual(by_quantity[5.0]["material_cost_chf"], 388.96)
        self.assertEqual(by_quantity[6.0]["matched_product_id"], "P-AIR-002")

    def test_matching_flags_supplier_package_fixture_for_review(self) -> None:
        data = load_project_data(PROJECT_ROOT)
        positions = parse_page_positions(PdfPageText(page_number=169, text=PAGE_169_TEXT))
        priced = match_positions(positions, data["catalog"], data["productivity"], data["parameters"])
        by_quantity = {row["quantity"]: row for row in priced}

        self.assertEqual(by_quantity[52.0]["matched_product_id"], "P-INS-001")
        self.assertEqual(by_quantity[52.0]["status"], "calculated")
        self.assertEqual(by_quantity[440.0]["matched_product_id"], "P-INS-003")
        self.assertEqual(by_quantity[440.0]["status"], "supplier_quote_required")
        self.assertTrue(by_quantity[440.0]["review_required"])

    def test_german_decimal_comma_and_compound_attributes_are_normalized(self) -> None:
        text = """
SH Erlenstrasse Oberglatt 244.99 Testanlage Seite 1 / 1
Schalldämpfer
Material V2A
B x H x L 1,25 x 0,50 x 2,00 m
Brandschutzdämmung EI30
Druckverlust 30Pa Stk 1,25
"""
        positions = parse_page_positions(PdfPageText(page_number=1, text=text))
        self.assertEqual(len(positions), 1)
        position = positions[0]
        self.assertEqual(position.quantity, 1.25)
        self.assertEqual(position.unit, "pc")
        self.assertIn("Schalldämpfer", position.original_description)
        self.assertEqual(position.technical_attributes["dimensions"][0]["values"], [1.25, 0.5, 2.0])
        self.assertEqual(position.technical_attributes["dimensions"][0]["unit"], "m")
        self.assertEqual(position.technical_attributes["dimensions"][0]["values_mm"], [1250.0, 500.0, 2000.0])
        self.assertEqual(position.technical_attributes["fire_ratings"], ["EI30"])
        self.assertIn("V2A", position.technical_attributes["materials"])

    def test_silencer_model_code_dimensions_are_not_parsed_as_centimetres(self) -> None:
        text = """
SH Erlenstrasse Oberglatt 244.01 LA01 Nebenraeume Seite 12 / 20
Schalldämpfer
Typ z.B.MS-F/300x400x1250/1x230/P
Luftmenge 700 m3/h
B x H x L 40 x 30 x 125 cm
Druckverlust 30Pa Stk 4
"""
        positions = parse_page_positions(PdfPageText(page_number=80, text=text))
        self.assertEqual(len(positions), 1)
        attrs = positions[0].technical_attributes

        self.assertEqual(attrs["model_code_dimensions"][0]["raw"], "300x400x1250")
        self.assertEqual(attrs["model_code_dimensions"][0]["unit"], "model_code_mm")
        self.assertEqual(attrs["model_code_dimensions"][0]["values_mm"], [300.0, 400.0, 1250.0])
        self.assertNotIn("300x400x1250", {dimension["raw"] for dimension in attrs["dimensions"]})
        self.assertEqual(attrs["dimensions"][0]["raw"], "40 x 30 x 125 cm")
        self.assertEqual(attrs["dimensions"][0]["values_mm"], [400.0, 300.0, 1250.0])
        self.assertEqual(attrs["ambiguous_dimensions"][0]["raw"], "1x230")

    def test_ambiguous_dimensions_are_preserved_without_invented_units(self) -> None:
        text = """
SH Erlenstrasse Oberglatt 244.99 Testanlage Seite 1 / 1
Unklare Baugruppe
Abmessung 12 x 8 Stk 2
"""
        positions = parse_page_positions(PdfPageText(page_number=1, text=text))
        attrs = positions[0].technical_attributes

        self.assertEqual(attrs["dimensions"], [])
        self.assertEqual(attrs["ambiguous_dimensions"][0]["raw"], "12 x 8")
        self.assertIsNone(attrs["ambiguous_dimensions"][0]["unit"])
        self.assertNotIn("values_mm", attrs["ambiguous_dimensions"][0])

    def test_uppercase_dimension_h_is_not_parsed_as_hour_unit(self) -> None:
        text = """
SH Erlenstrasse Oberglatt 244.01 LA01 Nebenraeume Seite 10 / 20
Regenhut
B x H 110 x 35 cm Stk 1
"""
        positions = parse_page_positions(PdfPageText(page_number=78, text=text))

        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0].unit, "pc")
        self.assertEqual(positions[0].quantity, 1.0)

    def test_lowercase_hour_units_remain_supported(self) -> None:
        positions = parse_page_positions(
            PdfPageText(page_number=1, text="Montageleistung h 21\nInbetriebnahme 8 h")
        )

        self.assertEqual([(row.quantity, row.unit) for row in positions], [(21.0, "h"), (8.0, "h")])
        self.assertTrue(all(row.record_type == "labour_service" for row in positions))

    def test_dotted_symbol_and_split_units_are_parsed_without_losing_source_unit(self) -> None:
        text = """
SH Erlenstrasse Oberglatt 244.02 LA02 Essenraeume EG Seite 19 / 27
Regelkomponenten
Drehantrieb, 20 Nm, Stk. 2
Kanalrauchmelder Stk. 1
Filterfläche 6.5 m²
Luftmenge 700 m3/h
- TW-1/70 A+-592-287-450-H 1 Stk
Servicearbeiten Std. 21
Revisionsfläche m² 1,25
Luftvolumen m³ 2,5
"""
        positions = parse_page_positions(PdfPageText(page_number=110, text=text))
        by_line = {position.source_line: position for position in positions}

        self.assertEqual(by_line["Drehantrieb, 20 Nm, Stk. 2"].quantity, 2.0)
        self.assertEqual(by_line["Drehantrieb, 20 Nm, Stk. 2"].unit, "pc")
        self.assertEqual(by_line["Drehantrieb, 20 Nm, Stk. 2"].original_unit, "Stk.")
        self.assertEqual(by_line["- TW-1/70 A+-592-287-450-H 1 Stk"].quantity, 1.0)
        self.assertEqual(by_line["Servicearbeiten Std. 21"].record_type, "labour_service")
        self.assertEqual(by_line["Servicearbeiten Std. 21"].unit, "h")
        self.assertEqual(by_line["Revisionsfläche m² 1,25"].unit, "m2")
        self.assertEqual(by_line["Revisionsfläche m² 1,25"].original_unit, "m²")
        self.assertEqual(by_line["Luftvolumen m³ 2,5"].unit, "m3")
        self.assertNotIn("Filterfläche 6.5 m²", by_line)
        self.assertNotIn("Luftmenge 700 m3/h", by_line)

    def test_unit_without_quantity_is_preserved_as_missing_quantity(self) -> None:
        text = """
SH Erlenstrasse Oberglatt 244.01 LA01 Nebenraeume Seite 1 / 20
Lueftungsgeraet
Zuluftgerät 1-1 Stk
1 Leerteil Stk. 1
"""
        positions = parse_page_positions(PdfPageText(page_number=67, text=text))

        self.assertEqual(len(positions), 2)
        self.assertEqual(positions[0].source_line, "Zuluftgerät 1-1 Stk")
        self.assertEqual(positions[0].quantity, 0.0)
        self.assertEqual(positions[0].record_type, "tender_position_missing_quantity")
        self.assertEqual(positions[1].quantity, 1.0)
        self.assertEqual(positions[1].original_unit, "Stk.")

    def test_bauteilliste_component_rows_are_extracted_with_table_evidence(self) -> None:
        text = """
Bauteilliste Lüftung
Auflistung der Kanäle
l mm KZ Formteil
3938 L Luftleitung 150 500
224 LT Luftleitungsteil 100 450
Auflistung der Kanalformstücke
Stk KZ Formteil
2 BA Bogen asymmetrisch 236 612 300 90
1 UA Übergang asymmetrisch 236 300 300
"""
        positions = parse_page_positions(PdfPageText(page_number=75, text=text))

        self.assertEqual(len(positions), 4)
        self.assertTrue(all(position.record_type == "component_list_row" for position in positions))
        self.assertEqual(positions[0].quantity, 3938.0)
        self.assertEqual(positions[0].unit, "mm")
        self.assertEqual(positions[0].technical_attributes["component_list"]["type_code"], "L")
        self.assertEqual(positions[2].quantity, 2.0)
        self.assertEqual(positions[2].unit, "pc")
        self.assertEqual(positions[2].technical_attributes["component_list"]["numeric_values"], [236.0, 612.0, 300.0, 90.0])
        self.assertIn("Auflistung der Kanalformstücke", positions[2].evidence)

    def test_component_and_labour_review_rows_are_not_automatically_priced(self) -> None:
        data = load_project_data(PROJECT_ROOT)
        text = """
Bauteilliste Lüftung
Auflistung der Kanäle
l mm KZ Formteil
3938 L Luftleitung 150 500
"""
        component_positions = parse_page_positions(PdfPageText(page_number=75, text=text))
        labour_positions = parse_page_positions(
            PdfPageText(
                page_number=135,
                text="""
SH Erlenstrasse Oberglatt 244.03 LA03 Küche/Abwaschen Seite 15 / 26
Servicearbeiten
Einregulierung Std. 21
""",
            )
        )
        priced = match_positions(component_positions + labour_positions, data["catalog"], data["productivity"], data["parameters"])

        self.assertEqual(priced[0]["status"], "insufficient_information")
        self.assertEqual(priced[0]["insufficient_reason_code"], "component_list_requires_assumption_or_catalogue_rule")
        self.assertEqual(priced[1]["status"], "insufficient_information")
        self.assertEqual(priced[1]["insufficient_reason_code"], "labour_service_requires_productivity_rule")
        self.assertNotIn("direct_position_cost_chf", priced[0])
        self.assertNotIn("direct_position_cost_chf", priced[1])

    def test_unsupported_vfc_variants_are_not_priced_as_dn250_controller(self) -> None:
        text = """
SH Erlenstrasse Oberglatt 244.04 Schulzimmer OG Seite 15 / 24
Einkanal-Volumenstromregler für konstanten Vol.strom
Fabrikat z.B. Trox Hesco
Typ z.B. VFC
Mod. DN V ΔP
cm m3/h Pa
VFC 8 40-100 50. Stk 12
"""
        data = load_project_data(PROJECT_ROOT)
        positions = parse_page_positions(PdfPageText(page_number=164, text=text))
        priced = match_positions(positions, data["catalog"], data["productivity"], data["parameters"])

        self.assertEqual(priced[0]["matched_product_id"], None)
        self.assertEqual(priced[0]["status"], "insufficient_information")
        self.assertEqual(priced[0]["insufficient_reason_code"], "no_plausible_catalogue_match")

    def test_round_pipe_silencer_variants_are_not_priced_as_kosd_package(self) -> None:
        text = """
SH Erlenstrasse Oberglatt 244.03 LA03 Küche/Abwaschen Seite 12 / 20
Rohrschalldämpfer
Doppelwandig, Innenrohr perforiert, mit Anschlussstutzen passend auf Spirorohre
Fabrikat z.B. Trox Hesco
Typ z.B. CA
Länge Ø Ø Isol. Dämpfung
100 10 20 10 ..... Stk 8
"""
        data = load_project_data(PROJECT_ROOT)
        positions = parse_page_positions(PdfPageText(page_number=187, text=text))
        priced = match_positions(positions, data["catalog"], data["productivity"], data["parameters"])

        self.assertEqual(priced[0]["matched_product_id"], None)
        self.assertEqual(priced[0]["status"], "insufficient_information")
        self.assertEqual(priced[0]["insufficient_reason_code"], "no_plausible_catalogue_match")

    def test_non_priceable_rows_are_classified_without_losing_traceability(self) -> None:
        text = """
SH Erlenstrasse Oberglatt 244.01 LA01 Nebenraeume Seite 10 / 20
Tellerventil
exkl. Sonderfarbzuschlag Stk 1
"""
        data = load_project_data(PROJECT_ROOT)
        positions = parse_page_positions(PdfPageText(page_number=78, text=text))
        priced = match_positions(positions, data["catalog"], data["productivity"], data["parameters"])

        self.assertEqual(priced[0]["status"], "non_priceable")
        self.assertEqual(priced[0]["classification"], "confirmed_non_priceable")
        self.assertEqual(priced[0]["classification_reason_code"], "non_priceable_or_assembly_entry")
        self.assertEqual(priced[0]["original_description"], positions[0].original_description)
        self.assertEqual(priced[0]["source_page"], 78)

    def test_failed_catalogue_match_is_not_automatically_non_priceable(self) -> None:
        text = """
SH Erlenstrasse Oberglatt 244.01 LA01 Nebenraeume Seite 12 / 20
Zuluftgitter
Grösse (B x H) 25 x 10 cm Stk 2
"""
        data = load_project_data(PROJECT_ROOT)
        positions = parse_page_positions(PdfPageText(page_number=80, text=text))
        priced = match_positions(positions, data["catalog"], data["productivity"], data["parameters"])

        self.assertEqual(priced[0]["status"], "insufficient_information")
        self.assertEqual(priced[0]["classification"], "ambiguous_priceable_candidate")
        self.assertEqual(priced[0]["insufficient_reason_code"], "no_plausible_catalogue_match")

    def test_duplicate_source_occurrences_are_preserved_and_annotated(self) -> None:
        text = """
SH Erlenstrasse Oberglatt 244.01 LA01 Nebenraeume Seite 10 / 20
Zuluft - Tellerventil
Grösse Ø 10 cm Stk 2
Abluft - Tellerventil
Grösse Ø 10 cm Stk 2
"""
        data = load_project_data(PROJECT_ROOT)
        positions = parse_page_positions(PdfPageText(page_number=135, text=text))
        priced = match_positions(positions, data["catalog"], data["productivity"], data["parameters"])

        self.assertEqual(len(priced), 2)
        self.assertEqual(priced[0]["source_line"], priced[1]["source_line"])
        self.assertEqual(priced[0]["duplicate_group_id"], priced[1]["duplicate_group_id"])
        self.assertEqual(priced[0]["duplicate_classification"], "repeated_source_line_different_context")
        self.assertEqual(priced[1]["duplicate_classification"], "repeated_source_line_different_context")
        self.assertFalse(priced[0]["duplicate_review_required"])
        self.assertFalse(priced[1]["duplicate_review_required"])
        self.assertEqual({row["matched_product_id"] for row in priced}, {"P-AIR-001", "P-AIR-003"})

    def test_catalogue_dimension_conflicts_are_review_only(self) -> None:
        text = """
SH Erlenstrasse Oberglatt 244.01 LA01 Nebenraeume Seite 11 / 20
Abluft - Tellerventil
aus Kunststoff, mit Luftmengeneinstellung
Fabrikat z.B Trox Hesco
Typ z.B LVS
Grösse Ø 12.5 cm Stk 6
"""
        data = load_project_data(PROJECT_ROOT)
        positions = parse_page_positions(PdfPageText(page_number=79, text=text))
        priced = match_positions(positions, data["catalog"], data["productivity"], data["parameters"])

        self.assertEqual(priced[0]["matched_product_id"], "P-AIR-003")
        self.assertEqual(priced[0]["status"], "review_required")
        self.assertTrue(priced[0]["review_required"])
        self.assertIn("diameter_mismatch", {flag["code"] for flag in priced[0]["conflict_flags"]})
        self.assertIn("source_page", priced[0])
        self.assertIn("install_code", priced[0])

    def test_round_penetration_does_not_hide_rectangular_catalogue_conflict(self) -> None:
        text = """
SH Erlenstrasse Oberglatt 244.02 LA02 Essenraeume EG Seite 24 / 27
Durchdringungen durch brandabschnittsbildende Waende
und Decken fuer runde Rohre EI30
Grösse 25 Ø cm Stk 6
"""
        data = load_project_data(PROJECT_ROOT)
        positions = parse_page_positions(PdfPageText(page_number=115, text=text))
        priced = match_positions(positions, data["catalog"], data["productivity"], data["parameters"])

        self.assertEqual(priced[0]["matched_product_id"], "P-FIR-002")
        self.assertEqual(priced[0]["status"], "review_required")
        self.assertIn("geometry_mismatch", {flag["code"] for flag in priced[0]["conflict_flags"]})

    def test_supplier_package_silencer_match_remains_provisional_with_dimension_review(self) -> None:
        text = """
SH Erlenstrasse Oberglatt 244.01 LA01 Nebenraeume Seite 12 / 20
Schalldämpfer
Typ z.B.MS-F/300x400x1250/1x230/P
Luftmenge 700 m3/h
B x H x L 40 x 30 x 125 cm
Druckverlust 30Pa Stk 4
"""
        data = load_project_data(PROJECT_ROOT)
        positions = parse_page_positions(PdfPageText(page_number=80, text=text))
        priced = match_positions(positions, data["catalog"], data["productivity"], data["parameters"])

        self.assertEqual(priced[0]["matched_product_id"], "P-SIL-001")
        self.assertEqual(priced[0]["status"], "supplier_quote_required")
        self.assertEqual(priced[0]["cost_confirmation_status"], "provisional_supplier_quote_required")
        self.assertEqual(priced[0]["material_cost_basis"], "supplier_package_catalogue_estimate_pending_quote")
        self.assertEqual(priced[0]["labour_cost_basis"], "productivity_rule_estimate")
        self.assertIn("ambiguous_dimension_unit", {flag["code"] for flag in priced[0]["conflict_flags"]})

    def test_pdf_slice_extraction_validates_known_pages_when_pdfplumber_available(self) -> None:
        try:
            pages = extract_pdf_text_pages(
                PROJECT_ROOT / "BKP_244_LV_Lueftung_260804.pdf",
                page_numbers=[78, 79, 80],
            )
        except RuntimeError as exc:
            self.skipTest(str(exc))

        data = load_project_data(PROJECT_ROOT)
        positions = parse_lv_positions(pages)
        priced = match_positions(positions, data["catalog"], data["productivity"], data["parameters"])
        matched_ids = {row.get("matched_product_id") for row in priced}

        self.assertIn("P-AIR-001", matched_ids)
        self.assertIn("P-AIR-002", matched_ids)
        self.assertIn("P-AIR-003", matched_ids)
        self.assertIn("P-FIR-001", matched_ids)
        self.assertTrue(any(row["source_page"] == 78 for row in priced))

    def test_pdf_affected_pages_extract_new_phase8h_rows_when_pdfplumber_available(self) -> None:
        try:
            pages = extract_pdf_text_pages(
                PROJECT_ROOT / "BKP_244_LV_Lueftung_260804.pdf",
                page_numbers=[67, 71, 75, 110, 131, 135, 197],
            )
        except RuntimeError as exc:
            self.skipTest(str(exc))

        positions = parse_lv_positions(pages)
        by_page = {}
        for position in positions:
            by_page.setdefault(position.source_page, []).append(position)

        self.assertGreaterEqual(len(by_page[67]), 2)
        self.assertTrue(any(position.record_type == "tender_position_missing_quantity" for position in by_page[67]))
        self.assertTrue(any(position.source_line == "- TW-1/70 A+-592-287-450-H 1 Stk" for position in by_page[71]))
        self.assertGreaterEqual(len(by_page[75]), 50)
        self.assertGreaterEqual(len(by_page[131]), 50)
        self.assertTrue(any(position.source_line == "Drehantrieb, 20 Nm, Stk. 2" for position in by_page[110]))
        self.assertTrue(any(position.record_type == "labour_service" and position.quantity == 176.0 for position in by_page[135]))
        self.assertTrue(any(position.source_line == "Montageschiene z.B. m 500" for position in by_page[197]))

    def test_pdf_known_example_pages_validate_all_reference_matches_when_pdfplumber_available(self) -> None:
        data = load_project_data(PROJECT_ROOT)
        known_pages = sorted({int(row["source_page"]) for row in data["examples"]})
        try:
            pages = extract_pdf_text_pages(
                PROJECT_ROOT / "BKP_244_LV_Lueftung_260804.pdf",
                page_numbers=known_pages,
            )
        except RuntimeError as exc:
            self.skipTest(str(exc))

        priced = match_positions(
            parse_lv_positions(pages),
            data["catalog"],
            data["productivity"],
            data["parameters"],
        )

        missing = []
        for expected in data["examples"]:
            candidates = [
                row
                for row in priced
                if row["source_page"] == int(expected["source_page"])
                and row["quantity"] == float(expected["quantity"])
                and row["unit"] == expected["unit"]
                and row.get("matched_product_id") == expected["suggested_product_id"]
            ]
            if not candidates:
                missing.append(expected["lv_id"])

        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()

