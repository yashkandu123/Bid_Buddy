# Phase 8C Editable Estimator Review

This phase adds editable review state for uploaded jobs. It does not change pricing formulas, golden outputs, bid optimization, LLM behavior, or priced-PDF generation.

## Dependency Security Check

Initial `npm audit --json` reported three frontend dev-dependency vulnerabilities:

| Package | Severity | Path | Advisory | Fix |
|---|---:|---|---|---|
| `vitest` | critical | direct dev dependency | path traversal / transitive issues | upgrade to `vitest@5.0.3` |
| `@vitest/mocker` | moderate | `vitest -> @vitest/mocker` | path traversal / arbitrary file read | fixed by `vitest@5.0.3` |
| `tinypool` | critical | `vitest -> tinypool` | prototype pollution / RCE gadget | fixed by `vitest@5.0.3` |

No `npm audit fix --force` was used. The explicit non-forced dev-dependency update to `vitest@^5.0.3` cleared the audit:

```text
found 0 vulnerabilities
```

## New Backend Endpoints

```text
GET   /catalog
GET   /jobs/{job_id}/review-state
PATCH /jobs/{job_id}/positions/{lv_id}/review
```

Editable fields:

```json
{
  "quantity": 5.0,
  "unit": "pc",
  "matched_product_id": "P-AIR-001",
  "estimator_notes": "Optional note"
}
```

Unsupported fields such as direct costs or totals are rejected. Product IDs must exist in `catalog.csv`. Units must be one of:

```text
pc, m, m2, h, LS, system
```

Recalculation uses the existing Python pricing functions. The browser never submits authoritative totals.

## Persistence Model

Review state is stored as `review_state.json` inside the uploaded job directory under `runtime_data/uploads/<job_id>/`.

Limitations:

- The job registry is still in memory.
- Uploaded files, result JSON, and review-state JSON remain local to one backend process.
- If the backend process loses its in-memory job registry, the current API cannot rediscover old jobs automatically.
- This is suitable for the demo/local job lifetime, not durable production storage.

## Safety Rules

- Original machine values are retained under `machine_values`.
- Effective reviewed values are returned at the top level.
- Accepted costs are exposed separately as `accepted_*_cost_chf`.
- Review-only previews are exposed as `override_cost_preview`.
- `review_required`, `insufficient_information`, and `non_priceable` rows remain excluded from accepted totals.
- Critical mismatches such as diameter or dimension conflicts keep the row review-only.
- Supplier-package catalogue estimates remain `supplier_quote_required` and provisional.
- Supplier quotes are not treated as confirmed merely because an estimator edits a row.

## Frontend Changes

Estimate & Review now includes:

- Product-family tabs based on catalogue/tender evidence.
- Search.
- Filters for status, install code, and ventilation system.
- Pagination, 25 rows per page.
- Editable position side panel for uploaded jobs.
- Read-only side panel for fixed Phase 2 output.
- Original German description, source page, quantity/unit, match evidence, conflicts, supplier-quote status, cost breakdowns, and estimator notes.

## Commands

Backend:

```powershell
& 'C:\Users\saiya\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m uvicorn src.tender_pricing.api:app --host 127.0.0.1 --port 8000
```

Frontend:

```powershell
cd frontend
npm install
npm run dev
```

Tests:

```powershell
cd frontend
npm test
npm run build
cd ..
& 'C:\Users\saiya\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests
```

