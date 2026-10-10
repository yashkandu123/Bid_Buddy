from __future__ import annotations

import unittest
from pathlib import Path

from src.tender_pricing.calculation_engine import (
    calculate_example_summary,
    calculate_positions,
    calculate_project_cost_breakdown,
    validate_against_reference,
)
from src.tender_pricing.data_loading import find_missing_files, load_project_data


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class GoldenExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = load_project_data(PROJECT_ROOT)
        cls.positions = calculate_positions(cls.data)
        cls.positions_by_id = {row["lv_id"]: row for row in cls.positions}
        cls.expected_by_id = {
            row["lv_id"]: row for row in cls.data["expected"]["position_results"]
        }
        cls.summary = calculate_example_summary(cls.positions, cls.data["parameters"])
        cls.breakdown = calculate_project_cost_breakdown(cls.positions, cls.data["parameters"])

    def test_required_input_files_are_present(self) -> None:
        self.assertEqual(find_missing_files(PROJECT_ROOT), [])

    def test_lv0001_matches_reference(self) -> None:
        actual = self.positions_by_id["LV0001"]
        expected = self.expected_by_id["LV0001"]
        for field in (
            "source_page",
            "matched_product_id",
            "install_code",
            "quantity",
            "unit",
            "net_unit_cost_chf",
            "material_cost_chf",
            "adjusted_install_hours",
            "labour_cost_chf",
            "direct_position_cost_chf",
            "price_source",
            "match_confidence",
            "review_required",
            "status",
        ):
            self.assertEqual(actual[field], expected[field], field)

    def test_all_example_positions_match_reference_rows(self) -> None:
        validation = validate_against_reference(
            self.positions,
            self.data["expected"]["example_subset_summary"],
            self.data["expected"],
        )
        self.assertTrue(validation["positions_match_reference"], validation["position_differences"])

    def test_aggregate_position_totals_match_reference(self) -> None:
        expected = self.data["expected"]["example_subset_summary"]
        self.assertEqual(self.summary["material_cost_chf"], expected["material_cost_chf"])
        self.assertEqual(self.summary["labour_cost_chf"], expected["labour_cost_chf"])
        self.assertEqual(self.summary["direct_cost_chf"], expected["direct_cost_chf"])

    def test_project_level_breakdown_uses_documented_phase1_formula(self) -> None:
        self.assertEqual(self.breakdown["catalog_material_cost_chf"], 72954.29)
        self.assertEqual(self.breakdown["supplier_package_material_cost_chf"], 204672.0)
        self.assertEqual(self.breakdown["small_material_allowance_chf"], 9716.92)
        self.assertEqual(self.breakdown["overhead_chf"], 31679.51)
        self.assertEqual(
            self.breakdown["cost_baseline_formula"],
            "direct_cost + small_material_allowance_on_material + overhead_on_direct_cost",
        )
        self.assertEqual(self.summary["cost_baseline_chf"], 414096.55)

    def test_reference_cost_baseline_has_documented_source_gap(self) -> None:
        expected_baseline = self.data["expected"]["example_subset_summary"]["cost_baseline_chf"]
        self.assertEqual(round(expected_baseline - self.summary["cost_baseline_chf"], 2), 392.57)

    def test_other_project_components_do_not_explain_reference_gap(self) -> None:
        self.assertEqual(self.breakdown["transport_equipment_allowance_chf"], 9317.5)
        self.assertEqual(self.breakdown["supplier_package_contingency_chf"], 6140.16)
        self.assertEqual(self.breakdown["engineering_chf"], 60900.0)
        self.assertEqual(self.breakdown["commissioning_chf"], 24800.0)
        self.assertEqual(self.breakdown["hygiene_inspection_chf"], 18000.0)
        self.assertEqual(self.breakdown["documentation_chf"], 12000.0)


if __name__ == "__main__":
    unittest.main()

