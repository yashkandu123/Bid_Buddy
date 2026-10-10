# Phase 4 Upload Jobs

This phase adds PDF upload and job-result endpoints to the existing FastAPI service. It does not add n8n, a frontend, external AI calls, a database, authentication, cloud storage or advanced orchestration.

## Environment

Use the bundled Codex Python runtime or install the pinned dependencies:

```powershell
& 'C:\Users\saiya\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pip install -r requirements.txt
```

## Configuration

Uploads and job outputs are stored outside the source/reference data by default:

```text
runtime_data/uploads
```

Environment variables:

```text
TENDER_PRICING_UPLOAD_DIR
TENDER_PRICING_MAX_UPLOAD_BYTES
```

Defaults:

```text
upload directory: runtime_data/uploads
max upload size: 25 MB
```

## Startup

```powershell
& 'C:\Users\saiya\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m uvicorn src.tender_pricing.api:app --host 127.0.0.1 --port 8000
```

## Processing Model

Jobs use an in-memory `JobStore` and local file storage. In the current implementation, processing runs synchronously inside `POST /jobs`: the endpoint returns after the PDF has been processed or failed.

Limitations:

```text
in-memory job state is lost when the process restarts
local uploaded files/results stay on this one service instance
large PDFs may exceed normal HTTP request timeouts
no authentication is implemented
```

Do not expose this service publicly without access controls.

## Endpoints

Existing Phase 3 endpoints still work:

```text
GET  /health
POST /price/examples
POST /process/full-tender-output
```

New Phase 4 endpoints:

```text
POST /jobs
GET  /jobs/{job_id}
GET  /jobs/{job_id}/results
```

### `POST /jobs`

Uploads a PDF as multipart form data. The service validates the PDF header and readability, enforces the configured size limit, stores the file under a server-generated job ID and processes it through the existing Phase 2 pipeline.

Example:

```bash
curl -X POST http://127.0.0.1:8000/jobs \
  -F "file=@BKP_244_LV_Lueftung_260804.pdf;type=application/pdf"
```

Response:

```json
{
  "job_id": "f2b1c2...",
  "status": "completed",
  "created_at": "2026-10-10T12:00:00+00:00"
}
```

### `GET /jobs/{job_id}`

Returns status metadata:

```bash
curl http://127.0.0.1:8000/jobs/f2b1c2...
```

Response fields:

```text
job_id
status
created_at
started_at
completed_at
position_counts_by_status
error
```

Statuses:

```text
queued
processing
completed
failed
```

Because current processing is synchronous, normal successful uploads usually move straight to `completed`; failed uploads or extraction errors return `failed`.

### `GET /jobs/{job_id}/results`

Returns results for completed jobs:

```bash
curl http://127.0.0.1:8000/jobs/f2b1c2.../results
```

For completed jobs, the response includes:

```text
positions
original German descriptions
source pages
quantities and units
technical attributes
catalogue_traceability
productivity_traceability
price sources and cost breakdowns
statuses and reason codes
duplicate annotations
review_required flags
conflict_flags
project_totals
baseline_reconciliation_warning
```

Behavior for non-completed jobs:

```text
unknown job: 404
queued/processing job results: 409
failed job results: 500 with safe error payload
missing stored result: 404
```

## Safety Rules

The upload endpoint does not accept filesystem paths. It uses server-generated job IDs and filenames.

Rows marked:

```text
review_required
insufficient_information
non_priceable
```

are not silently priced or included in confirmed or provisional project totals. Totals are split by cost certainty:

```text
confirmed: calculated rows only
provisional: supplier_quote_required rows only
combined_estimate: confirmed + provisional
```

Supplier-package material values come from `catalog.csv` as provisional estimates; they are not confirmed supplier quotes. Labour for those rows remains a productivity-rule estimate.

The CHF 392.57 baseline discrepancy remains visible in every result payload via `baseline_reconciliation_warning`.

## Tests

Bundled Codex Python:

```powershell
& 'C:\Users\saiya\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests
```

Default Python:

```powershell
python -m unittest discover -s tests
```

The default Python environment skips tests when dependencies such as FastAPI, pdfplumber or reportlab are unavailable.

## Verified Locally

Current bundled-runtime result:

```text
Ran 39 tests in 5.079s
OK
```

Current default-Python result:

```text
Ran 39 tests in 0.061s
OK (skipped=21)
```

Live HTTP/socket testing was not completed in the Codex sandbox because local socket access is blocked there. The route handlers, validation, job store and processing pipeline are covered by automated tests.
