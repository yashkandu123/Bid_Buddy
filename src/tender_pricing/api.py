from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .api_service import (
    EXAMPLE_DATASET_ID,
    FULL_TENDER_OUTPUT_ID,
    build_full_tender_output_response,
    build_health_response,
    build_verified_examples_response,
)
from .jobs import (
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JobStore,
    UploadValidationError,
)
from .bid_optimization import BidOptimizationError
from .review_state import ReviewValidationError
from .data_loading import load_project_data


PROJECT_ROOT = Path(__file__).resolve().parents[2]
JOB_STORE = JobStore(PROJECT_ROOT)


class VerifiedExamplesRequest(BaseModel):
    dataset_id: Literal["verified_examples"] = EXAMPLE_DATASET_ID

    class Config:
        extra = "forbid"


class FullTenderOutputRequest(BaseModel):
    dataset_id: Literal["phase2_full"] = FULL_TENDER_OUTPUT_ID

    class Config:
        extra = "forbid"


class PositionReviewPatch(BaseModel):
    quantity: float | None = None
    unit: Literal["pc", "m", "m2", "h", "LS", "system"] | None = None
    matched_product_id: str | None = None
    estimator_notes: str | None = None

    class Config:
        extra = "forbid"


class BidSelectionPatch(BaseModel):
    scenario_name: str

    class Config:
        extra = "forbid"


def get_project_root() -> Path:
    return PROJECT_ROOT


def get_job_store() -> JobStore:
    return JOB_STORE


app = FastAPI(
    title="Tender Pricing API",
    version="0.4.0",
    description="Thin API around the existing deterministic tender-pricing pipeline.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, object]:
    return build_health_response()


@app.post("/price/examples")
def price_verified_examples(
    request: VerifiedExamplesRequest,
    project_root: Path = Depends(get_project_root),
) -> dict[str, object]:
    if request.dataset_id != EXAMPLE_DATASET_ID:
        raise HTTPException(status_code=422, detail="Unsupported example dataset.")
    try:
        return build_verified_examples_response(project_root)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/process/full-tender-output")
def process_full_tender_output(
    request: FullTenderOutputRequest,
    project_root: Path = Depends(get_project_root),
) -> dict[str, object]:
    if request.dataset_id != FULL_TENDER_OUTPUT_ID:
        raise HTTPException(status_code=422, detail="Unsupported full-tender output dataset.")
    try:
        return build_full_tender_output_response(project_root)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/jobs")
def create_upload_job(
    file: UploadFile = File(...),
    job_store: JobStore = Depends(get_job_store),
) -> dict[str, object]:
    try:
        record = job_store.create_job(file.file, original_filename=file.filename)
    except UploadValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - shield local paths and parser details
        raise HTTPException(status_code=400, detail="Upload could not be accepted.") from exc
    return {
        "job_id": record.job_id,
        "status": record.status,
        "created_at": record.created_at,
    }


@app.get("/jobs/{job_id}")
def get_job_status(
    job_id: str,
    job_store: JobStore = Depends(get_job_store),
) -> dict[str, object]:
    try:
        return job_store.get_job(job_id).to_status_payload()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found.") from exc


@app.get("/jobs/{job_id}/results")
def get_job_results(
    job_id: str,
    job_store: JobStore = Depends(get_job_store),
) -> dict[str, object]:
    try:
        record = job_store.get_job(job_id)
        if record.status == JOB_STATUS_FAILED:
            raise HTTPException(status_code=500, detail=record.error or {"message": "Job failed."})
        if record.status != JOB_STATUS_COMPLETED:
            raise HTTPException(status_code=409, detail=f"Job is {record.status}; results are not ready.")
        return job_store.get_result(job_id)
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found.") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job result is missing.") from exc


@app.get("/catalog")
def get_catalog(project_root: Path = Depends(get_project_root)) -> dict[str, object]:
    data = load_project_data(project_root)
    return {
        "items": data["catalog"],
        "count": len(data["catalog"]),
    }


@app.get("/jobs/{job_id}/review-state")
def get_review_state(
    job_id: str,
    job_store: JobStore = Depends(get_job_store),
) -> dict[str, object]:
    try:
        return job_store.get_review_state(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found.") from exc


@app.patch("/jobs/{job_id}/positions/{lv_id}/review")
def update_position_review(
    job_id: str,
    lv_id: str,
    request: PositionReviewPatch,
    job_store: JobStore = Depends(get_job_store),
) -> dict[str, object]:
    fields_set = getattr(request, "model_fields_set", None)
    if fields_set is None:  # pragma: no cover - pydantic v1 compatibility
        fields_set = request.__fields_set__
    patch = {field: getattr(request, field) for field in fields_set}
    try:
        return job_store.update_position_review(job_id, lv_id, patch)
    except ReviewValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=f"Job is {exc}; review updates are not ready.") from exc
    except KeyError as exc:
        message = "Job not found." if len(str(exc).strip("'")) == 32 else "Position not found."
        raise HTTPException(status_code=404, detail=message) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job result is missing.") from exc


@app.get("/jobs/{job_id}/bid-scenarios")
def get_bid_scenarios(
    job_id: str,
    job_store: JobStore = Depends(get_job_store),
) -> dict[str, object]:
    try:
        record = job_store.get_job(job_id)
        if record.status == JOB_STATUS_FAILED:
            raise HTTPException(status_code=500, detail=record.error or {"message": "Job failed."})
        if record.status != JOB_STATUS_COMPLETED:
            raise HTTPException(status_code=409, detail=f"Job is {record.status}; bid scenarios are not ready.")
        return job_store.get_bid_scenarios(job_id)
    except HTTPException:
        raise
    except BidOptimizationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found.") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job result is missing.") from exc


@app.patch("/jobs/{job_id}/bid-selection")
def update_bid_selection(
    job_id: str,
    request: BidSelectionPatch,
    job_store: JobStore = Depends(get_job_store),
) -> dict[str, object]:
    fields_set = getattr(request, "model_fields_set", None)
    if fields_set is None:  # pragma: no cover - pydantic v1 compatibility
        fields_set = request.__fields_set__
    patch = {field: getattr(request, field) for field in fields_set}
    try:
        return job_store.update_bid_selection(job_id, patch)
    except BidOptimizationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=f"Job is {exc}; bid selection is not ready.") from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found.") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job result is missing.") from exc


@app.post("/jobs/{job_id}/final-offer")
def generate_final_offer(
    job_id: str,
    job_store: JobStore = Depends(get_job_store),
) -> dict[str, object]:
    try:
        record = job_store.get_job(job_id)
        if record.status == JOB_STATUS_FAILED:
            raise HTTPException(status_code=500, detail=record.error or {"message": "Job failed."})
        if record.status != JOB_STATUS_COMPLETED:
            raise HTTPException(status_code=409, detail=f"Job is {record.status}; final offer is not ready.")
        return job_store.generate_final_offer_pdf(job_id)
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=f"Job is {exc}; final offer is not ready.") from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found.") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/jobs/{job_id}/final-offer")
def get_final_offer_report(
    job_id: str,
    job_store: JobStore = Depends(get_job_store),
) -> dict[str, object]:
    try:
        return job_store.get_final_offer_report(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found.") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/jobs/{job_id}/final-offer/pdf")
def download_final_offer_pdf(
    job_id: str,
    job_store: JobStore = Depends(get_job_store),
) -> FileResponse:
    try:
        path = job_store.get_final_offer_pdf_path(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found.") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type="application/pdf", filename=f"{job_id}_priced_offer.pdf")
