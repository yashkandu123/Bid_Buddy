from __future__ import annotations

import io
import math
import shutil
import tempfile
import unittest
from pathlib import Path

try:
    from fastapi import HTTPException
    from pydantic import ValidationError
except ModuleNotFoundError:  # pragma: no cover
    HTTPException = None
    ValidationError = None

from src.tender_pricing.bid_optimization import build_bid_scenarios
from src.tender_pricing.data_loading import load_project_data

if HTTPException is not None:
    from src.tender_pricing.api import BidSelectionPatch, get_bid_scenarios, update_bid_selection
    from src.tender_pricing.jobs import JobStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class BidOptimizationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = load_project_data(PROJECT_ROOT)
        self.result = {
            "job_id": "abc",
            "status_counts": {
                "calculated": 34,
                "supplier_quote_required": 10,
                "review_required": 8,
                "insufficient_information": 127,
                "non_priceable": 37,
            },
            "project_totals": {
                "summary": {"direct_cost_chf": 624023.72, "cost_baseline_chf": 692321.57},
                "formula_note": "Uses the documented Phase 1 formula.",
                "included_statuses": ["calculated", "supplier_quote_required"],
                "included_position_count": 44,
                "excluded_position_count": 172,
                "supplier_quotes_outstanding": 10,
                "confirmed": {"summary": {"direct_cost_chf": 173844.82, "cost_baseline_chf": 192611.66}},
                "provisional": {"summary": {"direct_cost_chf": 450178.9, "cost_baseline_chf": 499709.91}},
                "combined_estimate": {"summary": {"direct_cost_chf": 624023.72, "cost_baseline_chf": 692321.57}},
            },
            "baseline_reconciliation_warning": {"code": "baseline", "severity": "warning", "message": "baseline gap"},
        }

    def test_all_configured_margins_and_chf_rounding_are_returned(self) -> None:
        scenarios = build_bid_scenarios(self.result, self.data["parameters"])

        by_name = {row["scenario"]: row for row in scenarios["scenarios"]}
        self.assertEqual(set(by_name), {"Aggressive", "Target", "Conservative"})
        self.assertEqual(by_name["Aggressive"]["margin_pct"], 2.5)
        self.assertEqual(by_name["Target"]["margin_pct"], 4.0)
        self.assertEqual(by_name["Conservative"]["margin_pct"], 6.5)
        self.assertEqual(by_name["Aggressive"]["bid_price_chf"], 711000.0)
        self.assertEqual(by_name["Target"]["bid_price_chf"], 722000.0)
        self.assertEqual(by_name["Conservative"]["bid_price_chf"], 741000.0)
        self.assertIn("round_up", scenarios["formula_audit"]["bid_price_formula"])

    def test_probability_is_clamped_and_labelled_heuristic(self) -> None:
        parameters = dict(self.data["parameters"])
        parameters["stretch_bid_optimization"] = dict(parameters["stretch_bid_optimization"])
        parameters["stretch_bid_optimization"]["reference_win_probability"] = 2.0
        parameters["stretch_bid_optimization"]["scenario_margins_pct"] = {"Aggressive": 0}
        parameters["stretch_bid_optimization"]["scenario_names"] = ["Aggressive"]

        scenarios = build_bid_scenarios(self.result, parameters)

        scenario = scenarios["scenarios"][0]
        self.assertLessEqual(scenario["estimated_win_probability"], 0.95)
        self.assertEqual(scenarios["warnings"][0]["code"], "probability_is_heuristic")

    def test_probability_is_unavailable_when_required_config_is_missing(self) -> None:
        parameters = dict(self.data["parameters"])
        parameters["stretch_bid_optimization"] = dict(parameters["stretch_bid_optimization"])
        parameters["stretch_bid_optimization"].pop("reference_win_probability")

        scenarios = build_bid_scenarios(self.result, parameters)

        self.assertFalse(scenarios["scenarios"][0]["probability_available"])
        self.assertIsNone(scenarios["scenarios"][0]["expected_contribution_chf"])

    def test_zero_and_non_finite_cost_inputs_are_unavailable(self) -> None:
        for value in (0, math.inf):
            result = dict(self.result)
            totals = dict(result["project_totals"])
            totals["combined_estimate"] = {"summary": {"direct_cost_chf": 0, "cost_baseline_chf": value}}
            result["project_totals"] = totals

            scenarios = build_bid_scenarios(result, self.data["parameters"])

            self.assertFalse(scenarios["scenarios"][0]["complete"])
            self.assertIsNone(scenarios["scenarios"][0]["bid_price_chf"])

    def test_warnings_report_unresolved_and_provisional_cost_basis(self) -> None:
        scenarios = build_bid_scenarios(self.result, self.data["parameters"])

        codes = {warning["code"] for warning in scenarios["warnings"]}
        self.assertIn("supplier_quotes_outstanding", codes)
        self.assertIn("unresolved_positions_excluded", codes)
        self.assertTrue(scenarios["cost_basis"]["has_provisional_supplier_estimates"])
        self.assertTrue(scenarios["cost_basis"]["has_unresolved_positions"])


@unittest.skipIf(HTTPException is None, "fastapi is not installed")
class BidOptimizationApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix=".bid-test-", dir=PROJECT_ROOT))
        self.store = JobStore(PROJECT_ROOT, upload_root=self.temp_dir, run_synchronously=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_job_bid_scenarios_use_saved_review_state(self) -> None:
        record = self.store.create_job(_pdf_bytes(_known_position_lines()), original_filename="demo.pdf")
        before = self.store.get_bid_scenarios(record.job_id)

        self.store.update_position_review(record.job_id, "PDF001-01", {"quantity": 100})
        after = get_bid_scenarios(record.job_id, job_store=self.store)

        self.assertGreater(
            after["cost_basis"]["cost_baseline_chf"],
            before["cost_basis"]["cost_baseline_chf"],
        )
        self.assertGreater(
            after["scenarios"][0]["bid_price_chf"],
            before["scenarios"][0]["bid_price_chf"],
        )

    def test_bid_selection_is_job_scoped_and_reloaded(self) -> None:
        record = self.store.create_job(_pdf_bytes(_known_position_lines()), original_filename="demo.pdf")

        updated = update_bid_selection(record.job_id, BidSelectionPatch(scenario_name="Target"), job_store=self.store)
        reloaded = get_bid_scenarios(record.job_id, job_store=self.store)

        self.assertEqual(updated["selection"]["scenario_name"], "Target")
        self.assertEqual(reloaded["selection"]["scenario_name"], "Target")
        self.assertIsNotNone(reloaded["selection"]["updated_at"])

    def test_bid_selection_rejects_unknown_scenarios_and_extra_fields(self) -> None:
        record = self.store.create_job(_pdf_bytes(_known_position_lines()), original_filename="demo.pdf")

        with self.assertRaises(HTTPException) as exc:
            update_bid_selection(record.job_id, BidSelectionPatch(scenario_name="Optimistic"), job_store=self.store)
        self.assertEqual(exc.exception.status_code, 422)

        with self.assertRaises(ValidationError):
            BidSelectionPatch(scenario_name="Target", total_chf=1)


def _known_position_lines() -> list[str]:
    return [
        "SH Erlenstrasse Oberglatt 244.01 LA01 Nebenraeume Seite 1 / 1",
        "Zuluft - Tellerventil",
        "aus Kunststoff, mit Luftmengeneinstellung",
        "Fabrikat z.B Trox Hesco",
        "Typ z.B Z-LVS",
        "Groesse Ø 10 cm Stk 5",
        "Ø 12.5 cm Stk 6",
    ]


def _pdf_bytes(lines: list[str]) -> io.BytesIO:
    try:
        from reportlab.pdfgen import canvas
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise unittest.SkipTest("reportlab is not installed") from exc

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    y = 800
    for line in lines:
        pdf.drawString(40, y, line)
        y -= 16
    pdf.save()
    buffer.seek(0)
    return buffer


if __name__ == "__main__":
    unittest.main()
