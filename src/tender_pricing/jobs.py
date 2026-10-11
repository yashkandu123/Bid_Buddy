from __future__ import annotations

import json
import os
import os
import shutil
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO

from .api_service import (
    API_SCHEMA_VERSION,
    _normalise_position_payload,
    build_baseline_warning,
    build_segmented_project_totals,
)
from .bid_optimization import build_bid_scenarios, validate_bid_selection
from .data_loading import load_project_data
from .pdf_ingestion import extract_pdf_text_pages
from .pdf_overlay import (
    EXPORT_SCHEMA_VERSION,
    eligible_overlay_positions,
    map_price_cells,
    write_mapping_json,
    write_overlay_prototype,
)
from .position_parser import parse_lv_positions
from .product_matching import match_positions
from .review_state import (
    ReviewValidationError,
    apply_review_state,
    empty_review_state,
    validate_review_patch,
)
from .user_inventory import project_user_facing_inventory


JOB_STATUS_QUEUED = "queued"
JOB_STATUS_PROCESSING = "processing"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"
ALLOWED_JOB_STATUSES = {
    JOB_STATUS_QUEUED,
    JOB_STATUS_PROCESSING,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
}
DEFAULT_UPLOAD_ROOT = Path("runtime_data") / "uploads"
DEFAULT_MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class UploadValidationError(ValueError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class JobRecord:
    job_id: str
    status: str
    created_at: str
    upload_filename: str
    stored_filename: str
    upload_size_bytes: int
    started_at: str | None = None
    completed_at: str | None = None
    error: dict[str, str] | None = None
    position_counts_by_status: dict[str, int] = field(default_factory=dict)
    result_path: str | None = None

    def to_status_payload(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "position_counts_by_status": self.position_counts_by_status,
            "error": self.error,
        }


class JobStore:
    def __init__(
        self,
        project_root: Path,
        upload_root: Path | None = None,
        max_upload_bytes: int | None = None,
        run_synchronously: bool = True,
    ) -> None:
        self.project_root = project_root
        self.upload_root = (upload_root or _configured_upload_root(project_root)).resolve()
        self.max_upload_bytes = max_upload_bytes if max_upload_bytes is not None else _configured_max_upload_bytes()
        self.run_synchronously = run_synchronously
        self.jobs: dict[str, JobRecord] = {}
        self._lock = threading.Lock()
        self.upload_root.mkdir(parents=True, exist_ok=True)

    def create_job(self, upload: BinaryIO, original_filename: str | None = None) -> JobRecord:
        job_id = uuid.uuid4().hex
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        stored_filename = f"{job_id}.pdf"
        stored_path = job_dir / stored_filename
        size = _copy_limited(upload, stored_path, self.max_upload_bytes)
        _validate_pdf_file(stored_path)

        now = _utc_now()
        record = JobRecord(
            job_id=job_id,
            status=JOB_STATUS_QUEUED,
            created_at=now,
            upload_filename=_safe_display_filename(original_filename),
            stored_filename=stored_filename,
            upload_size_bytes=size,
        )
        with self._lock:
            self.jobs[job_id] = record

        if self.run_synchronously:
            self.process_job(job_id)
        else:
            thread = threading.Thread(target=self.process_job, args=(job_id,), daemon=True)
            thread.start()
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> JobRecord:
        _validate_job_id(job_id)
        with self._lock:
            if job_id not in self.jobs:
                recovered = self._recover_completed_job(job_id)
                if recovered is None:
                    raise KeyError(job_id)
                self.jobs[job_id] = recovered
            return self.jobs[job_id]

    def get_result(self, job_id: str) -> dict[str, Any]:
        record = self.get_job(job_id)
        if record.status != JOB_STATUS_COMPLETED:
            raise RuntimeError(record.status)
        if not record.result_path:
            raise FileNotFoundError("Completed job has no result path.")
        result_path = (self.upload_root / record.result_path).resolve()
        _assert_within_root(result_path, self.upload_root)
        if not result_path.exists():
            raise FileNotFoundError("Stored job result is missing.")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result = project_user_facing_inventory(result, self.project_root)
        return apply_review_state(result, load_project_data(self.project_root), self.get_review_state(job_id))

    def get_review_state(self, job_id: str) -> dict[str, Any]:
        self.get_job(job_id)
        path = self._review_state_path(job_id)
        if not path.exists():
            return empty_review_state()
        return json.loads(path.read_text(encoding="utf-8"))

    def update_position_review(self, job_id: str, lv_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        record = self.get_job(job_id)
        if record.status != JOB_STATUS_COMPLETED:
            raise RuntimeError(record.status)
        if not record.result_path:
            raise FileNotFoundError("Completed job has no result path.")
        result_path = (self.upload_root / record.result_path).resolve()
        _assert_within_root(result_path, self.upload_root)
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result = project_user_facing_inventory(result, self.project_root)
        base_position = next((row for row in result["positions"] if row["lv_id"] == lv_id), None)
        if not base_position:
            raise KeyError(lv_id)
        data = load_project_data(self.project_root)
        normalized_patch = validate_review_patch(base_position, patch, data)
        normalized_patch["updated_at"] = _utc_now()
        review_state = self.get_review_state(job_id)
        review_state.setdefault("positions", {})[lv_id] = {
            **review_state.setdefault("positions", {}).get(lv_id, {}),
            **normalized_patch,
        }
        self._write_review_state(job_id, review_state)
        updated_result = apply_review_state(result, data, review_state)
        self._update(job_id, position_counts_by_status=updated_result["status_counts"])
        return updated_result

    def get_bid_scenarios(self, job_id: str) -> dict[str, Any]:
        result = self.get_result(job_id)
        data = load_project_data(self.project_root)
        return build_bid_scenarios(result, data["parameters"], self.get_bid_selection(job_id))

    def get_bid_selection(self, job_id: str) -> dict[str, Any]:
        self.get_job(job_id)
        path = self._bid_selection_path(job_id)
        if not path.exists():
            return {"scenario_name": None, "updated_at": None}
        return json.loads(path.read_text(encoding="utf-8"))

    def update_bid_selection(self, job_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        scenarios = self.get_bid_scenarios(job_id)
        valid_names = {scenario["scenario"] for scenario in scenarios["scenarios"]}
        selection = validate_bid_selection(patch, valid_names)
        selection["updated_at"] = _utc_now()
        self._write_bid_selection(job_id, selection)
        return self.get_bid_scenarios(job_id)

    def generate_final_offer_pdf(self, job_id: str) -> dict[str, Any]:
        record = self.get_job(job_id)
        if record.status != JOB_STATUS_COMPLETED:
            raise RuntimeError(record.status)
        result = self.get_result(job_id)
        source_pdf = self._job_dir(job_id) / record.stored_filename
        if not source_pdf.exists():
            raise FileNotFoundError("Uploaded source PDF is missing.")

        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("PDF export requires pypdf.") from exc

        page_count = len(PdfReader(str(source_pdf)).pages)
        pages = list(range(1, page_count + 1))
        eligible = eligible_overlay_positions(result["positions"], set(pages))
        mappings = map_price_cells(source_pdf, eligible, set(pages)) if eligible else []
        mapped = [mapping for mapping in mappings if mapping.placement_status == "mapped"]
        skipped_mappings = [mapping for mapping in mappings if mapping.placement_status != "mapped"]

        export_dir = self._job_dir(job_id) / "final_offer"
        output_pdf = export_dir / "priced_offer.pdf"
        validation_report = export_dir / "validation_report.json"
        mapping_path = export_dir / "overlay_mapping.json"
        write_overlay_prototype(source_pdf=source_pdf, output_pdf=output_pdf, mappings=mappings, pages=pages)
        write_mapping_json(mapping_path, mappings, pages)

        status_counts = result.get("status_counts", {})
        report = {
            "schema_version": EXPORT_SCHEMA_VERSION,
            "job_id": job_id,
            "status": "completed",
            "created_at": _utc_now(),
            "source_pdf": record.upload_filename,
            "page_count": page_count,
            "output_pdf": str(output_pdf.relative_to(self.upload_root)).replace("\\", "/"),
            "download_url": f"/jobs/{job_id}/final-offer/pdf",
            "validation_report": str(validation_report.relative_to(self.upload_root)).replace("\\", "/"),
            "mapping_report": str(mapping_path.relative_to(self.upload_root)).replace("\\", "/"),
            "pricing_policy": (
                "Only pricing_authorized calculated rows with accepted direct costs are overlaid. "
                "Supplier_quote_required, review_required, insufficient_information and non_priceable rows are left blank."
            ),
            "summary": {
                "accepted_position_count": len(eligible),
                "mapped_position_count": len(mapped),
                "skipped_mapping_count": len(skipped_mappings),
                "supplier_quotes_outstanding": int(result["project_totals"].get("supplier_quotes_outstanding", 0)),
                "unresolved_position_counts": {
                    "review_required": int(status_counts.get("review_required", 0)),
                    "insufficient_information": int(status_counts.get("insufficient_information", 0)),
                    "non_priceable": int(status_counts.get("non_priceable", 0)),
                    "supplier_quote_required": int(status_counts.get("supplier_quote_required", 0)),
                },
            },
            "mapped_positions": [mapping.to_dict() for mapping in mapped],
            "skipped_positions": [mapping.to_dict() for mapping in skipped_mappings],
            "warnings": _final_offer_warnings(result, skipped_mappings),
        }
        export_dir.mkdir(parents=True, exist_ok=True)
        validation_report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        return report

    def get_final_offer_report(self, job_id: str) -> dict[str, Any]:
        self.get_job(job_id)
        path = self._final_offer_report_path(job_id)
        if not path.exists():
            raise FileNotFoundError("Final offer PDF has not been generated.")
        return json.loads(path.read_text(encoding="utf-8"))

    def get_final_offer_pdf_path(self, job_id: str) -> Path:
        report = self.get_final_offer_report(job_id)
        path = (self.upload_root / report["output_pdf"]).resolve()
        _assert_within_root(path, self.upload_root)
        if not path.exists():
            raise FileNotFoundError("Generated final offer PDF is missing.")
        return path

    def process_job(self, job_id: str) -> None:
        try:
            record = self.get_job(job_id)
            self._update(job_id, status=JOB_STATUS_PROCESSING, started_at=_utc_now())
            uploaded_pdf = self._job_dir(job_id) / record.stored_filename
            result = process_uploaded_pdf(uploaded_pdf, self.project_root, job_id=job_id)
            result_path = self._job_dir(job_id) / "result.json"
            result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            user_result = project_user_facing_inventory(result, self.project_root)
            self._update(
                job_id,
                status=JOB_STATUS_COMPLETED,
                completed_at=_utc_now(),
                position_counts_by_status=user_result["status_counts"],
                result_path=str(result_path.relative_to(self.upload_root)),
            )
        except Exception as exc:  # noqa: BLE001 - job runner must always record failure
            self._update(
                job_id,
                status=JOB_STATUS_FAILED,
                completed_at=_utc_now(),
                error={
                    "code": "processing_failed",
                    "message": _safe_error_message(exc),
                },
            )

    def _update(self, job_id: str, **updates: Any) -> None:
        with self._lock:
            record = self.jobs[job_id]
            for key, value in updates.items():
                setattr(record, key, value)

    def _job_dir(self, job_id: str) -> Path:
        _validate_job_id(job_id)
        path = (self.upload_root / job_id).resolve()
        _assert_within_root(path, self.upload_root)
        return path

    def _review_state_path(self, job_id: str) -> Path:
        return self._job_dir(job_id) / "review_state.json"

    def _write_review_state(self, job_id: str, review_state: dict[str, Any]) -> None:
        path = self._review_state_path(job_id).resolve()
        _assert_within_root(path, self.upload_root)
        path.write_text(json.dumps(review_state, indent=2, ensure_ascii=False), encoding="utf-8")

    def _bid_selection_path(self, job_id: str) -> Path:
        return self._job_dir(job_id) / "bid_selection.json"

    def _write_bid_selection(self, job_id: str, selection: dict[str, Any]) -> None:
        path = self._bid_selection_path(job_id).resolve()
        _assert_within_root(path, self.upload_root)
        path.write_text(json.dumps(selection, indent=2, ensure_ascii=False), encoding="utf-8")

    def _final_offer_report_path(self, job_id: str) -> Path:
        return self._job_dir(job_id) / "final_offer" / "validation_report.json"

    def _recover_completed_job(self, job_id: str) -> JobRecord | None:
        try:
            job_dir = self._job_dir(job_id)
        except KeyError:
            return None
        source_pdf = job_dir / f"{job_id}.pdf"
        result_path = job_dir / "result.json"
        if not source_pdf.exists() or not result_path.exists():
            return None
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        created = datetime.fromtimestamp(source_pdf.stat().st_mtime, timezone.utc).isoformat()
        completed = datetime.fromtimestamp(result_path.stat().st_mtime, timezone.utc).isoformat()
        return JobRecord(
            job_id=job_id,
            status=JOB_STATUS_COMPLETED,
            created_at=created,
            started_at=created,
            completed_at=completed,
            upload_filename=source_pdf.name,
            stored_filename=source_pdf.name,
            upload_size_bytes=source_pdf.stat().st_size,
            position_counts_by_status=project_user_facing_inventory(result, self.project_root).get("status_counts", {}),
            result_path=str(result_path.relative_to(self.upload_root)),
        )


def process_uploaded_pdf(pdf_path: Path, project_root: Path, job_id: str) -> dict[str, Any]:
    data = load_project_data(project_root)
    pages = extract_pdf_text_pages(
        pdf_path,
        backend=os.getenv("TENDER_PDF_BACKEND", "pdfplumber").strip().lower(),
    )
    positions = parse_lv_positions(pages)
    if not positions:
        raise RuntimeError("PDF text extraction produced no priceable position candidates.")
    ai_provider = None
    provider_name = os.getenv("TENDER_MATCH_PROVIDER", "").strip().lower()
    if provider_name:
        from .ai_matching_experiment import create_provider

        ai_provider = create_provider(
            provider_name,
            fake_decision=os.getenv("TENDER_AI_FAKE_DECISION", "review").strip().lower(),
        )
    priced_rows = match_positions(
        positions,
        data["catalog"],
        data["productivity"],
        data["parameters"],
        ai_provider=ai_provider,
    )
    positions_payload = [_normalise_position_payload(row, data) for row in priced_rows]
    status_counts: dict[str, int] = {}
    for row in positions_payload:
        status = str(row.get("status"))
        status_counts[status] = status_counts.get(status, 0) + 1
    duplicate_rows = [row for row in positions_payload if row.get("duplicate_group_id")]
    conflict_rows = [row for row in positions_payload if row.get("conflict_flags")]
    return {
        "schema_version": API_SCHEMA_VERSION,
        "job_id": job_id,
        "scope": "Uploaded tender PDF processed through the Phase 2 extraction and pricing pipeline.",
        "positions": positions_payload,
        "position_count": len(positions_payload),
        "status_counts": status_counts,
        "review_summary": {
            "review_required_rows": sum(1 for row in positions_payload if row.get("review_required")),
            "conflict_flagged_rows": len(conflict_rows),
            "duplicate_candidate_rows": len(duplicate_rows),
            "duplicate_groups": len({row["duplicate_group_id"] for row in duplicate_rows}),
        },
        "project_totals": build_segmented_project_totals(positions_payload, data["parameters"]),
        "baseline_reconciliation_warning": build_baseline_warning(data),
        "warnings": [
            "Combined estimate totals include confirmed calculated rows plus provisional supplier_quote_required rows.",
            "Confirmed totals exclude supplier_quote_required rows because supplier quotes remain outstanding.",
            "Rows marked review_required, insufficient_information or non_priceable are excluded from both confirmed and provisional totals.",
            "Job state is in memory and uploaded files/results are local to this service instance.",
        ],
    }


def _configured_upload_root(project_root: Path) -> Path:
    configured = os.environ.get("TENDER_PRICING_UPLOAD_DIR")
    if configured:
        return Path(configured)
    return project_root / DEFAULT_UPLOAD_ROOT


def _configured_max_upload_bytes() -> int:
    configured = os.environ.get("TENDER_PRICING_MAX_UPLOAD_BYTES")
    if not configured:
        return DEFAULT_MAX_UPLOAD_BYTES
    try:
        value = int(configured)
    except ValueError:
        return DEFAULT_MAX_UPLOAD_BYTES
    return max(value, 1)


def _copy_limited(upload: BinaryIO, destination: Path, max_bytes: int) -> int:
    total = 0
    with destination.open("wb") as output:
        while True:
            chunk = upload.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                output.close()
                destination.unlink(missing_ok=True)
                raise UploadValidationError("Uploaded PDF exceeds the configured size limit.", status_code=413)
            output.write(chunk)
    if total == 0:
        destination.unlink(missing_ok=True)
        raise UploadValidationError("Uploaded file is empty.", status_code=400)
    return total


def _validate_pdf_file(path: Path) -> None:
    with path.open("rb") as handle:
        header = handle.read(5)
    if header != b"%PDF-":
        path.unlink(missing_ok=True)
        raise UploadValidationError("Uploaded file is not a PDF.", status_code=415)
    try:
        import pypdf

        with path.open("rb") as handle:
            reader = pypdf.PdfReader(handle)
            if len(reader.pages) == 0:
                raise UploadValidationError("Uploaded PDF has no pages.", status_code=400)
    except UploadValidationError:
        path.unlink(missing_ok=True)
        raise
    except Exception as exc:  # noqa: BLE001 - convert parser details to safe API error
        path.unlink(missing_ok=True)
        raise UploadValidationError("Uploaded PDF is corrupt or unreadable.", status_code=400) from exc


def _safe_display_filename(filename: str | None) -> str:
    if not filename:
        return "upload.pdf"
    name = Path(filename).name
    return name[:120] or "upload.pdf"


def _validate_job_id(job_id: str) -> None:
    if not job_id or not all(char in "0123456789abcdef" for char in job_id) or len(job_id) != 32:
        raise KeyError(job_id)


def _assert_within_root(path: Path, root: Path) -> None:
    path.resolve().relative_to(root.resolve())


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_error_message(exc: Exception) -> str:
    if isinstance(exc, RuntimeError):
        return str(exc)
    if isinstance(exc, UploadValidationError):
        return str(exc)
    return "Processing failed. See server logs for details."


def _final_offer_warnings(result: dict[str, Any], skipped_mappings: list[Any]) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    supplier_quotes = int(result["project_totals"].get("supplier_quotes_outstanding", 0))
    if supplier_quotes:
        warnings.append(
            {
                "code": "supplier_quotes_outstanding",
                "severity": "warning",
                "message": (
                    f"{supplier_quotes} supplier-package rows remain provisional and were not overlaid as final prices."
                ),
            }
        )
    status_counts = result.get("status_counts", {})
    unresolved = int(status_counts.get("review_required", 0)) + int(status_counts.get("insufficient_information", 0))
    if unresolved:
        warnings.append(
            {
                "code": "unresolved_positions_excluded",
                "severity": "warning",
                "message": f"{unresolved} unresolved rows were excluded from the priced PDF.",
            }
        )
    if skipped_mappings:
        warnings.append(
            {
                "code": "mapping_failures",
                "severity": "warning",
                "message": f"{len(skipped_mappings)} accepted rows could not be mapped unambiguously and were left blank.",
            }
        )
    return warnings


def reset_job_store(store: JobStore) -> None:
    with store._lock:
        store.jobs.clear()
    if store.upload_root.exists():
        shutil.rmtree(store.upload_root)
    store.upload_root.mkdir(parents=True, exist_ok=True)
