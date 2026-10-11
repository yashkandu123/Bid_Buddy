import unittest
from pathlib import Path

from src.tender_pricing.data_loading import load_project_data
from src.tender_pricing.pdf_ingestion import PdfPageText
from src.tender_pricing.position_parser import parse_page_positions
from src.tender_pricing.review_state import apply_position_review, validate_review_patch, ReviewValidationError


class UnitCostOverrideTests(unittest.TestCase):
    def setUp(self):
        self.data = load_project_data(Path(__file__).resolve().parents[1])
        position, = parse_page_positions(PdfPageText(78, "Zuluft - Tellerventil\nGrösse Ø 10 cm Stk 5"))
        self.row = {**position.to_dict(), "matched_product_id": "P-AIR-001", "status": "calculated"}

    def test_override_reuses_engine_without_mutating_catalogue(self):
        result = apply_position_review(self.row, {"quantity": 10, "net_unit_cost_chf": 100}, self.data)
        self.assertEqual(result["material_cost_chf"], 1040)
        self.assertEqual(result["net_unit_cost_chf"], 100)
        self.assertEqual(result["direct_position_cost_chf"], 1040 + result["labour_cost_chf"])
        self.assertEqual(result["accepted_direct_position_cost_chf"], result["direct_position_cost_chf"])
        product = next(p for p in self.data["catalog"] if p["product_id"] == "P-AIR-001")
        self.assertEqual(float(product["net_cost_chf"]), 74.8)

    def test_invalid_costs_rejected(self):
        for value in (-1, float("nan"), float("inf"), "bad"):
            with self.subTest(value=value), self.assertRaises(ReviewValidationError):
                validate_review_patch(self.row, {"net_unit_cost_chf": value}, self.data)

    def test_cost_edit_cannot_authorize_review_position(self):
        result = apply_position_review({**self.row, "status": "review_required"}, {"net_unit_cost_chf": 100}, self.data)
        self.assertEqual(result["status"], "review_required")
        self.assertFalse(result["pricing_authorized"])
        self.assertIsNone(result["accepted_direct_position_cost_chf"])

    def test_null_cost_restores_catalogue_basis(self):
        result = apply_position_review(self.row, {"net_unit_cost_chf": None}, self.data)
        self.assertEqual(result["net_unit_cost_chf"], 74.8)

    def test_supplier_override_remains_provisional(self):
        result = apply_position_review(self.row, {"matched_product_id": "P-FAN-500", "net_unit_cost_chf": 500}, self.data)
        self.assertEqual(result["status"], "supplier_quote_required")
        self.assertEqual(result["cost_confirmation_status"], "provisional_supplier_quote_required")
        self.assertEqual(result["material_cost_basis"], "estimator_net_unit_cost_override")

    def test_price_edit_does_not_clear_dimension_conflicts(self):
        result = apply_position_review(self.row, {"matched_product_id": "P-DAM-001", "net_unit_cost_chf": 100}, self.data)
        self.assertEqual(result["status"], "review_required")
        self.assertIsNone(result["accepted_direct_position_cost_chf"])
        self.assertIn("diameter_mismatch", {flag["code"] for flag in result["conflict_flags"]})


if __name__ == "__main__":
    unittest.main()
