# Phase 3 API

Thin FastAPI service around the existing tender-pricing Python pipeline.

Out of scope in this phase:

```text
n8n
frontend
LLM/external AI calls
database
background queue
PDF upload handling
```

Python remains the source of truth for pricing calculations.

## Installation

Use the bundled Codex Python runtime, which already contains the PDF dependencies used in Phase 2:

```powershell
& 'C:\Users\saiya\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pip install -r requirements.txt
```

## Startup

From the project root:

```powershell
& 'C:\Users\saiya\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m uvicorn src.tender_pricing.api:app --host 127.0.0.1 --port 8000
```

## Endpoints

### `GET /health`

Returns service status and response schema version.

Example:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/health
```

### `POST /price/examples`

Prices the supplied 22-position verified example dataset using the existing Phase 1 calculation engine.

Request:

```json
{
  "dataset_id": "verified_examples"
}
```

Example:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/price/examples `
  -ContentType 'application/json' `
  -Body '{"dataset_id":"verified_examples"}'
```

The response includes:

```text
positions
position-level material/labour/direct costs
source pages
original German descriptions when linked from Phase 2 output
catalogue_traceability
productivity_traceability
status/reason codes
duplicate annotations
review/conflict flags
project_totals
baseline_reconciliation_warning
validation against expected_output_example.json
```

### `POST /process/full-tender-output`

Processes the existing Phase 2 output at:

```text
outputs/phase2_full/priced_positions.json
```

It does not run PDF extraction and does not accept filesystem paths.

Request:

```json
{
  "dataset_id": "phase2_full"
}
```

Example:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/process/full-tender-output `
  -ContentType 'application/json' `
  -Body '{"dataset_id":"phase2_full"}'
```

The response preserves Phase 2 fields, including German source text, source page, technical attributes, status/reason codes, duplicate annotations and conflict flags.

Project totals include only rows with complete pricing fields and status:

```text
calculated
supplier_quote_required
```

Rows with `review_required`, `insufficient_information` or `non_priceable` are excluded from totals so uncertain records are not silently priced.

## Validation and Errors

The API accepts only fixed dataset IDs:

```text
verified_examples
phase2_full
```

Extra request fields, including arbitrary path-like fields, are rejected with validation errors. Missing required project files or missing Phase 2 output returns an HTTP 404.

## Baseline Warning

Every pricing response includes:

```text
baseline_reconciliation_warning
```

Current documented formula result:

```text
CHF 414,096.55
```

Reference expected baseline:

```text
CHF 414,489.12
```

Unresolved discrepancy:

```text
CHF 392.57
```

This remains documented in `BASELINE_RECONCILIATION.md`. The API does not hardcode an adjustment or modify Phase 1 formulas to force the reference aggregate.

## Tests

Bundled Codex Python:

```powershell
& 'C:\Users\saiya\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests
```

Default Python:

```powershell
python -m unittest discover -s tests
```

The default Python environment skips API tests when FastAPI is unavailable and skips real-PDF tests when `pdfplumber` is unavailable.
