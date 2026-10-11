from __future__ import annotations

import io
import shutil
import tempfile
import unittest
from pathlib import Path

try:
    from fastapi import HTTPException
    from fastapi.testclient import TestClient
    from pydantic import ValidationError
except ModuleNotFoundError:  # pragma: no cover - exercised in environments without FastAPI
    HTTPException = None
    ValidationError = None

if HTTPException is not None:
    from src.tender_pricing.api import (
        FullTenderOutputRequest,
        PositionReviewPatch,
        VerifiedExamplesRequest,
        app,
        download_final_offer_pdf,
        generate_final_offer,
        get_catalog,
        get_final_offer_report,
        get_job_store,
        get_project_root,
        get_review_state,
        health,
        price_verified_examples,
        process_full_tender_output,
        update_position_review,
    )
    from src.tender_pricing.jobs import JobStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_INPUTS = (
    "catalog.csv",
    "productivity.csv",
    "project_parameters.json",
    "example_lv_positions.csv",
    "expected_output_example.json",
)


@unittest.skipIf(HTTPException is None, "fastapi is not installed")
class Phase3ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        app.dependency_overrides.clear()

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def test_health_endpoint(self) -> None:
        body = health()

        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["schema_version"], "phase4.v1")

    def test_job_workflow_supports_local_and_cloud_api_prefixes(self) -> None:
        temp_dir = tempfile.mkdtemp(prefix=".api-prefix-test-", dir=PROJECT_ROOT)
        try:
            store = JobStore(PROJECT_ROOT, upload_root=Path(temp_dir), run_synchronously=True)
            app.dependency_overrides[get_job_store] = lambda: store
            with TestClient(app) as client:
                for prefix in ("", "/api"):
                    with self.subTest(prefix=prefix or "root"):
                        upload = client.post(
                            f"{prefix}/jobs",
                            files={
                                "file": (
                                    "demo.pdf",
                                    _pdf_bytes(_known_position_lines()).getvalue(),
                                    "application/pdf",
                                )
                            },
                        )
                        self.assertEqual(upload.status_code, 200)
                        job_id = upload.json()["job_id"]

                        status = client.get(f"{prefix}/jobs/{job_id}")
                        results = client.get(f"{prefix}/jobs/{job_id}/results")

                        self.assertEqual(status.status_code, 200)
                        self.assertEqual(status.json()["status"], "completed")
                        self.assertEqual(results.status_code, 200)
                        self.assertGreater(results.json()["position_count"], 0)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_every_api_route_has_a_cloud_prefixed_alias(self) -> None:
        route_signatures = {
            (route.path, frozenset(route.methods or set()))
            for route in app.routes
            if hasattr(route, "methods")
        }
        root_routes = {
            (path, methods)
            for path, methods in route_signatures
            if not path.startswith("/api") and path not in {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
        }

        for path, methods in root_routes:
            with self.subTest(path=path):
                self.assertIn((f"/api{path}", methods), route_signatures)

    def test_local_vite_cors_preflight_is_allowed(self) -> None:
        cors = next(middleware for middleware in app.user_middleware if middleware.cls.__name__ == "CORSMiddleware")

        self.assertIn("http://127.0.0.1:5173", cors.kwargs["allow_origins"])
        self.assertIn("http://localhost:5173", cors.kwargs["allow_origins"])
        self.assertEqual(cors.kwargs["allow_methods"], ["GET", "POST", "PATCH"])

    def test_catalog_endpoint_returns_catalogue_only(self) -> None:
        body = get_catalog(PROJECT_ROOT)

        self.assertGreaterEqual(body["count"], 56)
        self.assertIn("product_id", body["items"][0])
        self.assertIn("net_cost_chf", body["items"][0])

    def test_review_state_endpoint_and_patch_errors(self) -> None:
        temp_dir = tempfile.mkdtemp(prefix=".api-review-test-", dir=PROJECT_ROOT)
        try:
            store = JobStore(PROJECT_ROOT, upload_root=Path(temp_dir), run_synchronously=True)
            with self.assertRaises(HTTPException) as unknown_job:
                get_review_state("0" * 32, job_store=store)
            self.assertEqual(unknown_job.exception.status_code, 404)

            with self.assertRaises(HTTPException) as unknown_position:
                update_position_review(
                    "0" * 32,
                    "PDF001-01",
                    PositionReviewPatch(quantity=2),
                    job_store=store,
                )
            self.assertEqual(unknown_position.exception.status_code, 404)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_final_offer_endpoints_generate_report_and_file_response(self) -> None:
        temp_dir = tempfile.mkdtemp(prefix=".api-final-offer-test-", dir=PROJECT_ROOT)
        try:
            store = JobStore(PROJECT_ROOT, upload_root=Path(temp_dir), run_synchronously=True)
            record = store.create_job(_pdf_bytes(_known_position_lines()), original_filename="demo.pdf")

            report = generate_final_offer(record.job_id, job_store=store)
            reloaded = get_final_offer_report(record.job_id, job_store=store)
            response = download_final_offer_pdf(record.job_id, job_store=store)

            self.assertEqual(report["job_id"], record.job_id)
            self.assertEqual(reloaded["summary"]["mapped_position_count"], 2)
            self.assertEqual(response.media_type, "application/pdf")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_verified_examples_preserve_golden_results_and_traceability(self) -> None:
        body = price_verified_examples(VerifiedExamplesRequest(dataset_id="verified_examples"), PROJECT_ROOT)

        self.assertEqual(body["dataset_id"], "verified_examples")
        self.assertEqual(body["position_count"], 22)
        self.assertTrue(body["validation"]["positions_match_reference"])
        self.assertEqual(body["project_totals"]["summary"]["cost_baseline_chf"], 414096.55)
        self.assertEqual(body["project_totals"]["supplier_quotes_outstanding"], 6)
        self.assertEqual(body["project_totals"]["confirmed"]["included_statuses"], ["calculated"])
        self.assertEqual(body["project_totals"]["provisional"]["included_statuses"], ["supplier_quote_required"])
        self.assertLess(
            body["project_totals"]["confirmed"]["summary"]["direct_cost_chf"],
            body["project_totals"]["combined_estimate"]["summary"]["direct_cost_chf"],
        )
        self.assertEqual(body["baseline_reconciliation_warning"]["difference_chf"], 392.57)

        lv0001 = next(row for row in body["positions"] if row["lv_id"] == "LV0001")
        self.assertEqual(lv0001["matched_product_id"], "P-AIR-001")
        self.assertEqual(lv0001["material_cost_chf"], 388.96)
        self.assertEqual(lv0001["labour_cost_chf"], 417.3)
        self.assertEqual(lv0001["direct_position_cost_chf"], 806.26)
        self.assertEqual(lv0001["source_page"], 78)
        self.assertEqual(lv0001["source_language"], "de")
        self.assertIn("Zuluft", lv0001["original_description"])
        self.assertEqual(lv0001["catalogue_traceability"]["product_id"], "P-AIR-001")
        self.assertEqual(lv0001["productivity_traceability"]["install_code"], "DIFFUSER")

    def test_full_tender_output_endpoint_returns_phase2_structure(self) -> None:
        body = process_full_tender_output(FullTenderOutputRequest(dataset_id="phase2_full"), PROJECT_ROOT)

        self.assertEqual(body["dataset_id"], "phase2_full")
        self.assertEqual(body["position_count"], 216)
        self.assertEqual(body["status_counts"]["calculated"], 34)
        self.assertEqual(body["status_counts"]["supplier_quote_required"], 10)
        self.assertEqual(body["status_counts"]["review_required"], 8)
        self.assertEqual(body["status_counts"]["insufficient_information"], 127)
        self.assertEqual(body["status_counts"]["non_priceable"], 37)
        self.assertEqual(body["review_summary"]["duplicate_candidate_rows"], 12)
        self.assertEqual(body["review_summary"]["conflict_flagged_rows"], 11)
        self.assertEqual(body["project_totals"]["supplier_quotes_outstanding"], 10)
        self.assertEqual(body["project_totals"]["confirmed"]["included_position_count"], 34)
        self.assertEqual(body["project_totals"]["provisional"]["included_position_count"], 10)

        calculated = next(row for row in body["positions"] if row["status"] == "calculated")
        self.assertIn("source_page", calculated)
        self.assertIn("original_description", calculated)
        self.assertIsNotNone(calculated["catalogue_traceability"])
        self.assertIsNotNone(calculated["productivity_traceability"])
        self.assertEqual(calculated["duplicate_classification"], "unique")

    def test_full_tender_totals_exclude_uncertain_and_non_priceable_rows(self) -> None:
        body = process_full_tender_output(FullTenderOutputRequest(dataset_id="phase2_full"), PROJECT_ROOT)

        totals = body["project_totals"]
        self.assertEqual(totals["included_statuses"], ["calculated", "supplier_quote_required"])
        self.assertEqual(totals["included_position_count"], 44)
        self.assertEqual(totals["excluded_position_count"], 172)
        self.assertEqual(totals["confirmed"]["included_position_count"], 34)
        self.assertEqual(totals["provisional"]["included_position_count"], 10)
        self.assertEqual(totals["confirmed"]["summary"]["direct_cost_chf"], 173844.82)
        self.assertEqual(totals["provisional"]["summary"]["direct_cost_chf"], 450178.9)
        self.assertEqual(totals["combined_estimate"]["summary"]["direct_cost_chf"], 624023.72)
        self.assertEqual(totals["summary"]["direct_cost_chf"], 624023.72)
        self.assertEqual(totals["confirmed"]["summary"]["cost_baseline_chf"], 192611.66)
        self.assertEqual(totals["provisional"]["summary"]["cost_baseline_chf"], 499709.91)
        self.assertEqual(totals["combined_estimate"]["summary"]["cost_baseline_chf"], 692321.57)
        self.assertEqual(totals["summary"]["cost_baseline_chf"], 692321.57)

    def test_invalid_dataset_id_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            FullTenderOutputRequest(dataset_id="../phase2_full")

    def test_extra_request_fields_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            FullTenderOutputRequest(dataset_id="phase2_full", path="C:/Windows/win.ini")

    def test_missing_phase2_output_returns_404_without_arbitrary_path_input(self) -> None:
        temp_dir = tempfile.mkdtemp(prefix=".api-test-", dir=PROJECT_ROOT)
        try:
            temp_root = Path(temp_dir)
            for filename in REQUIRED_INPUTS:
                shutil.copy(PROJECT_ROOT / filename, temp_root / filename)
            app.dependency_overrides[get_project_root] = lambda: temp_root

            with self.assertRaises(HTTPException) as exc:
                process_full_tender_output(FullTenderOutputRequest(dataset_id="phase2_full"), temp_root)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        self.assertEqual(exc.exception.status_code, 404)
        self.assertIn("outputs", exc.exception.detail)


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
    page_height = 841.8898
    for x in (440.2, 488.3, 562.0):
        pdf.line(x, 40, x, page_height - 40)
    y = 800
    for line in lines:
        pdf.drawString(40, y, line)
        y -= 16
    pdf.save()
    buffer.seek(0)
    return buffer


if __name__ == "__main__":
    unittest.main()
