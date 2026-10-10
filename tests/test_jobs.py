from __future__ import annotations

import io
import shutil
import tempfile
import unittest
from pathlib import Path

try:
    from fastapi import HTTPException
    from starlette.datastructures import UploadFile
except ModuleNotFoundError:  # pragma: no cover - exercised in environments without FastAPI
    HTTPException = None
    UploadFile = None

if HTTPException is not None:
    from src.tender_pricing.api import create_upload_job, get_job_results, get_job_status
    from src.tender_pricing.jobs import (
        JOB_STATUS_COMPLETED,
        JOB_STATUS_FAILED,
        JOB_STATUS_QUEUED,
        JobRecord,
        JobStore,
        UploadValidationError,
    )
    from src.tender_pricing.review_state import ReviewValidationError


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@unittest.skipIf(HTTPException is None, "fastapi is not installed")
class Phase4JobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix=".jobs-test-", dir=PROJECT_ROOT))
        self.store = JobStore(PROJECT_ROOT, upload_root=self.temp_dir, run_synchronously=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_valid_pdf_upload_processes_to_completed_job(self) -> None:
        record = self.store.create_job(_pdf_bytes(_known_position_lines()), original_filename="../Tender.pdf")

        self.assertEqual(record.status, JOB_STATUS_COMPLETED)
        self.assertEqual(record.upload_filename, "Tender.pdf")
        self.assertEqual(record.position_counts_by_status["calculated"], 2)
        self.assertIsNotNone(record.completed_at)

        result = self.store.get_result(record.job_id)
        self.assertEqual(result["job_id"], record.job_id)
        self.assertEqual(result["position_count"], 2)
        self.assertEqual(result["status_counts"]["calculated"], 2)
        first = result["positions"][0]
        self.assertEqual(first["source_page"], 1)
        self.assertEqual(first["source_language"], "de")
        self.assertIn("Zuluft", first["original_description"])
        self.assertEqual(first["catalogue_traceability"]["product_id"], "P-AIR-001")
        self.assertEqual(first["productivity_traceability"]["install_code"], "DIFFUSER")

    def test_api_upload_handler_returns_job_id_and_status(self) -> None:
        upload = UploadFile(file=_pdf_bytes(_known_position_lines()), filename="demo.pdf")

        body = create_upload_job(file=upload, job_store=self.store)

        self.assertRegex(body["job_id"], r"^[0-9a-f]{32}$")
        self.assertEqual(body["status"], JOB_STATUS_COMPLETED)

    def test_invalid_non_pdf_upload_is_rejected(self) -> None:
        with self.assertRaises(UploadValidationError) as exc:
            self.store.create_job(io.BytesIO(b"not a pdf"), original_filename="note.txt")

        self.assertEqual(exc.exception.status_code, 415)

    def test_corrupt_pdf_upload_is_rejected(self) -> None:
        with self.assertRaises(UploadValidationError) as exc:
            self.store.create_job(io.BytesIO(b"%PDF-1.7\nnot really a pdf"), original_filename="bad.pdf")

        self.assertEqual(exc.exception.status_code, 400)

    def test_upload_size_limit_is_enforced(self) -> None:
        small_store = JobStore(PROJECT_ROOT, upload_root=self.temp_dir / "small", max_upload_bytes=10)

        with self.assertRaises(UploadValidationError) as exc:
            small_store.create_job(_pdf_bytes(_known_position_lines()), original_filename="too-large.pdf")

        self.assertEqual(exc.exception.status_code, 413)

    def test_unique_job_ids_and_file_isolation(self) -> None:
        first = self.store.create_job(_pdf_bytes(_known_position_lines()), original_filename="first.pdf")
        second = self.store.create_job(_pdf_bytes(_known_position_lines()), original_filename="second.pdf")

        self.assertNotEqual(first.job_id, second.job_id)
        first_path = self.temp_dir / first.job_id / first.stored_filename
        second_path = self.temp_dir / second.job_id / second.stored_filename
        self.assertTrue(first_path.exists())
        self.assertTrue(second_path.exists())
        self.assertNotEqual(first_path, second_path)

    def test_status_endpoint_returns_counts_after_processing(self) -> None:
        record = self.store.create_job(_pdf_bytes(_known_position_lines()), original_filename="demo.pdf")

        body = get_job_status(record.job_id, job_store=self.store)

        self.assertEqual(body["job_id"], record.job_id)
        self.assertEqual(body["status"], JOB_STATUS_COMPLETED)
        self.assertEqual(body["position_counts_by_status"]["calculated"], 2)

    def test_results_endpoint_returns_completed_job_payload(self) -> None:
        record = self.store.create_job(_pdf_bytes(_known_position_lines()), original_filename="demo.pdf")

        body = get_job_results(record.job_id, job_store=self.store)

        self.assertEqual(body["job_id"], record.job_id)
        self.assertEqual(body["project_totals"]["included_position_count"], 2)
        self.assertEqual(body["project_totals"]["confirmed"]["included_position_count"], 2)
        self.assertEqual(body["project_totals"]["provisional"]["included_position_count"], 0)
        self.assertEqual(body["baseline_reconciliation_warning"]["difference_chf"], 392.57)

    def test_processing_failure_sets_failed_status_and_safe_error(self) -> None:
        record = self.store.create_job(_pdf_bytes(["This PDF has text but no LV quantities."]), original_filename="empty.pdf")

        self.assertEqual(record.status, JOB_STATUS_FAILED)
        self.assertEqual(record.error["code"], "processing_failed")
        self.assertIn("no priceable position candidates", record.error["message"])

        with self.assertRaises(HTTPException) as exc:
            get_job_results(record.job_id, job_store=self.store)
        self.assertEqual(exc.exception.status_code, 500)

    def test_unknown_job_ids_return_404(self) -> None:
        with self.assertRaises(HTTPException) as exc:
            get_job_status("0" * 32, job_store=self.store)

        self.assertEqual(exc.exception.status_code, 404)

    def test_results_before_completion_return_409(self) -> None:
        record = JobRecord(
            job_id="1" * 32,
            status=JOB_STATUS_QUEUED,
            created_at="2026-10-10T00:00:00+00:00",
            upload_filename="queued.pdf",
            stored_filename="1" * 32 + ".pdf",
            upload_size_bytes=100,
        )
        self.store.jobs[record.job_id] = record

        with self.assertRaises(HTTPException) as exc:
            get_job_results(record.job_id, job_store=self.store)

        self.assertEqual(exc.exception.status_code, 409)

    def test_non_priceable_and_insufficient_rows_are_not_silently_priced(self) -> None:
        lines = [
            "SH Erlenstrasse Oberglatt 244.01 LA01 Nebenraeume Seite 1 / 1",
            "Tellerventil",
            "exkl. Sonderfarbzuschlag Stk 1",
            "Zuluftgitter",
            "Grösse (B x H) 25 x 10 cm Stk 2",
        ]
        record = self.store.create_job(_pdf_bytes(lines), original_filename="review.pdf")
        result = self.store.get_result(record.job_id)

        statuses = {row["status"] for row in result["positions"]}
        self.assertIn("non_priceable", statuses)
        self.assertIn("insufficient_information", statuses)
        for row in result["positions"]:
            if row["status"] in {"non_priceable", "insufficient_information"}:
                self.assertNotIn("direct_position_cost_chf", row)
        self.assertEqual(result["project_totals"]["included_position_count"], 0)
        self.assertEqual(result["project_totals"]["confirmed"]["included_position_count"], 0)
        self.assertEqual(result["project_totals"]["provisional"]["included_position_count"], 0)

    def test_review_edit_is_saved_reloaded_and_recalculates_totals(self) -> None:
        record = self.store.create_job(_pdf_bytes(_known_position_lines()), original_filename="demo.pdf")
        before = self.store.get_result(record.job_id)

        updated = self.store.update_position_review(
            record.job_id,
            "PDF001-01",
            {"quantity": 10, "estimator_notes": "Estimator adjusted count."},
        )
        reloaded = self.store.get_result(record.job_id)
        row = next(position for position in reloaded["positions"] if position["lv_id"] == "PDF001-01")

        self.assertEqual(row["quantity"], 10.0)
        self.assertEqual(row["machine_values"]["quantity"], 5.0)
        self.assertTrue(row["review_state"]["has_overrides"])
        self.assertEqual(row["review_state"]["estimator_notes"], "Estimator adjusted count.")
        self.assertEqual(row["status"], "calculated")
        self.assertTrue(row["pricing_authorized"])
        self.assertEqual(row["accepted_direct_position_cost_chf"], row["direct_position_cost_chf"])
        self.assertGreater(
            updated["project_totals"]["confirmed"]["summary"]["direct_cost_chf"],
            before["project_totals"]["confirmed"]["summary"]["direct_cost_chf"],
        )

    def test_review_update_rejects_invalid_fields_and_values(self) -> None:
        record = self.store.create_job(_pdf_bytes(_known_position_lines()), original_filename="demo.pdf")

        with self.assertRaises(ReviewValidationError):
            self.store.update_position_review(record.job_id, "PDF001-01", {"quantity": 0})
        with self.assertRaises(ReviewValidationError):
            self.store.update_position_review(record.job_id, "PDF001-01", {"matched_product_id": "P-NOT-REAL"})
        with self.assertRaises(ReviewValidationError):
            self.store.update_position_review(record.job_id, "PDF001-01", {"unit": "kg"})
        with self.assertRaises(ReviewValidationError):
            self.store.update_position_review(record.job_id, "PDF001-01", {"direct_position_cost_chf": 1})

    def test_product_change_with_dimension_mismatch_stays_review_only(self) -> None:
        record = self.store.create_job(_pdf_bytes(_known_position_lines()), original_filename="demo.pdf")

        updated = self.store.update_position_review(
            record.job_id,
            "PDF001-01",
            {"matched_product_id": "P-DAM-001"},
        )
        row = next(position for position in updated["positions"] if position["lv_id"] == "PDF001-01")

        self.assertEqual(row["status"], "review_required")
        self.assertFalse(row["pricing_authorized"])
        self.assertIsNone(row["accepted_direct_position_cost_chf"])
        self.assertIn("diameter_mismatch", {flag["code"] for flag in row["conflict_flags"]})
        self.assertIn("override_cost_preview", row)
        self.assertEqual(updated["project_totals"]["confirmed"]["included_position_count"], 1)

    def test_supplier_quote_required_override_remains_provisional(self) -> None:
        record = self.store.create_job(_pdf_bytes(_known_position_lines()), original_filename="demo.pdf")

        updated = self.store.update_position_review(
            record.job_id,
            "PDF001-01",
            {"matched_product_id": "P-FAN-500"},
        )
        row = next(position for position in updated["positions"] if position["lv_id"] == "PDF001-01")

        self.assertEqual(row["status"], "supplier_quote_required")
        self.assertTrue(row["supplier_quote_required"])
        self.assertEqual(row["cost_confirmation_status"], "provisional_supplier_quote_required")
        self.assertEqual(updated["project_totals"]["provisional"]["included_position_count"], 1)
        self.assertEqual(updated["project_totals"]["supplier_quotes_outstanding"], 1)

    def test_final_offer_pdf_exports_only_accepted_calculated_prices(self) -> None:
        record = self.store.create_job(_pdf_bytes(_known_position_lines()), original_filename="demo.pdf")
        self.store.update_position_review(record.job_id, "PDF001-01", {"matched_product_id": "P-DAM-001"})

        report = self.store.generate_final_offer_pdf(record.job_id)

        self.assertEqual(report["schema_version"], "phase8f.pdf_overlay_export.v1")
        self.assertEqual(report["summary"]["accepted_position_count"], 1)
        self.assertEqual(report["summary"]["mapped_position_count"], 1)
        self.assertEqual(report["mapped_positions"][0]["lv_id"], "PDF001-02")
        self.assertTrue((self.temp_dir / report["output_pdf"]).exists())
        self.assertTrue((self.temp_dir / report["validation_report"]).exists())
        self.assertNotIn("PDF001-01", {row["lv_id"] for row in report["mapped_positions"]})

    def test_final_offer_pdf_excludes_supplier_package_estimates(self) -> None:
        record = self.store.create_job(_pdf_bytes(_known_position_lines()), original_filename="demo.pdf")
        self.store.update_position_review(record.job_id, "PDF001-01", {"matched_product_id": "P-FAN-500"})

        report = self.store.generate_final_offer_pdf(record.job_id)

        self.assertEqual(report["summary"]["supplier_quotes_outstanding"], 1)
        self.assertEqual(report["summary"]["accepted_position_count"], 1)
        self.assertEqual({row["lv_id"] for row in report["mapped_positions"]}, {"PDF001-02"})
        self.assertIn("supplier_quotes_outstanding", {warning["code"] for warning in report["warnings"]})

    def test_completed_job_is_recovered_from_disk_after_restart(self) -> None:
        record = self.store.create_job(_pdf_bytes(_known_position_lines()), original_filename="demo.pdf")
        restarted = JobStore(PROJECT_ROOT, upload_root=self.temp_dir, run_synchronously=True)

        recovered = restarted.get_job(record.job_id)
        result = restarted.get_result(record.job_id)

        self.assertEqual(recovered.status, JOB_STATUS_COMPLETED)
        self.assertEqual(result["job_id"], record.job_id)
        self.assertEqual(result["position_count"], 2)

    def test_insufficient_and_non_priceable_positions_stay_excluded_after_override(self) -> None:
        lines = [
            "SH Erlenstrasse Oberglatt 244.01 LA01 Nebenraeume Seite 1 / 1",
            "Tellerventil",
            "exkl. Sonderfarbzuschlag Stk 1",
            "Zuluftgitter",
            "Grösse (B x H) 25 x 10 cm Stk 2",
        ]
        record = self.store.create_job(_pdf_bytes(lines), original_filename="review.pdf")

        updated = self.store.update_position_review(
            record.job_id,
            "PDF001-02",
            {"matched_product_id": "P-AIR-001", "estimator_notes": "Potential product, still needs review."},
        )
        row = next(position for position in updated["positions"] if position["lv_id"] == "PDF001-02")

        self.assertEqual(row["status"], "insufficient_information")
        self.assertFalse(row["pricing_authorized"])
        self.assertIsNone(row["accepted_direct_position_cost_chf"])
        self.assertIn("override_cost_preview", row)
        self.assertEqual(updated["project_totals"]["included_position_count"], 0)

    def test_review_update_reports_missing_job_and_position(self) -> None:
        record = self.store.create_job(_pdf_bytes(_known_position_lines()), original_filename="demo.pdf")

        with self.assertRaises(KeyError):
            self.store.update_position_review("0" * 32, "PDF001-01", {"quantity": 2})
        with self.assertRaises(KeyError):
            self.store.update_position_review(record.job_id, "PDF999-01", {"quantity": 2})


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
    except ModuleNotFoundError as exc:  # pragma: no cover - bundled runtime provides reportlab
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
