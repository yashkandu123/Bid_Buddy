# Phase 8B Frontend Foundation

This phase adds a separated React + Vite frontend in `frontend/`. It does not change pricing formulas, golden outputs, matching behavior, bid optimization logic, or PDF export behavior.

## What Works Now

- Five-page workflow shell:
  - Welcome & Tender Upload
  - Processing
  - Estimate & Review
  - Bid Optimization
  - Final Offer
- Real PDF upload from the welcome page to `POST /jobs`.
- Processing page reads real job status from `GET /jobs/{job_id}`.
- Estimate page can read real job results from `GET /jobs/{job_id}/results`.
- Estimate page can also load the fixed Phase 2 output through `POST /process/full-tender-output`.
- Product-type tabs are display-only and do not change pricing status.
- German source descriptions, source pages, status/reason codes, duplicate annotations, conflict flags, and catalogue/productivity traceability are shown from backend data.
- Backend CORS is restricted to local Vite origins:
  - `http://127.0.0.1:5173`
  - `http://localhost:5173`

## Not Available Yet

- Persisting estimator edits.
- Accepting or overriding catalogue matches.
- Recalculation after human review.
- Deterministic bid optimization endpoint.
- Final priced-PDF generation.
- Durable job storage, authentication, or multi-user state.

The Bid Optimization and Final Offer pages intentionally show disabled states until backend support exists.

## Install Frontend Dependencies

From the project root:

```powershell
cd frontend
npm install
```

## Run Backend

From the project root:

```powershell
& 'C:\Users\saiya\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m uvicorn src.tender_pricing.api:app --host 127.0.0.1 --port 8000
```

## Run Frontend

In a second terminal:

```powershell
cd frontend
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

Optional API base override:

```powershell
$env:VITE_API_BASE_URL = 'http://127.0.0.1:8000'
npm run dev
```

Do not put API keys or secrets in Vite environment variables.

## Tests and Build

Frontend:

```powershell
cd frontend
npm test
npm run build
```

Backend:

```powershell
& 'C:\Users\saiya\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests
```

