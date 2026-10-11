# UI improvements - 2026-10-10

## Implemented

- Four workflow stages: Upload, Estimate & Review, Bid Optimization, Final Offer. Upload contains processing status, polling, errors and retry; old processing URLs display Upload. The last job is restored on return/refresh.
- Each stage has a bottom action. Review requires an uploaded job; bid advancement requires a saved scenario. Job IDs follow navigation. Pending editor changes block stage/row navigation; closing the drawer saves changes. Browser refresh warns about unsaved changes.
- Quantity and Unit Cost (CHF) edits save after a 400 ms typing pause and recalculate through the existing backend. The save button remains available for notes, product/unit changes, and retry. Inputs are disabled during saving; failures stay visible.
- Unit cost means **net material cost per unit**, before waste and labour. It is not the installed PDF unit price. The existing deterministic function receives a copied product with the overridden net cost; catalogue/reference data and formulas remain unchanged. Null restores catalogue cost. Negative/non-finite costs are rejected. Updated project totals and scenario prices use saved review state.
- Existing `PATCH /jobs/{job_id}/positions/{lv_id}` accepts optional `net_unit_cost_chf`. Overrides persist in the existing review-state JSON, including after completed-job recovery. Machine values and catalogue traceability are retained, estimator cost basis is explicit, and edited rows show an indicator.
- Price edits do not authorize excluded positions or clear technical conflicts. Supplier estimates remain provisional. PDF export reads current accepted direct costs through the existing job workflow.
- Price overlay text increased from 7.2 to 9.5 pt, with an 8.5 pt readable minimum, existing right alignment and 5 pt inset. A value that cannot fit is flagged `price_text_does_not_fit`, never clipped or placed in another column.
- The supplied company logo was copied unchanged to `frontend/src/assets/equans-reference.jpg`. The duplicate source copy was removed during deployment cleanup. The original Equans Switzerland image replaces the drawn/text mark. Aspect ratio preserved; JPEG has a solid background. There was no generated Equans PDF logo to replace.

## Verification

- Complete backend suite: **124 tests, 121 passed, 2 failures, 1 error, no skips**.
- Focused pricing/API/job/review/bid/golden/PDF run: **60 passed, no skips**. Includes override validation, provisional and critical-conflict safeguards, disk recovery, recalculation, exported numeric values, larger-font boundaries and rejection of oversized text.
- Frontend: **16 tests passed across 8 suites**. Includes upload completion/error, cost editing, autosave errors, navigation blocking and existing review/bid/export tests. Production TypeScript/Vite build passed.
- Windows sandbox denied Vite realpath access; tests/build passed with approved unrestricted reruns. No dependency changes were needed for this task.
- Desktop Upload navigation visually inspected. Supplied logo and Upload layout visually inspected at desktop and 390 px mobile width. Existing saved 20-page job opened in review; quantity 5 and net cost 74.8 were displayed. No existing job was edited for this browser check.
- Rendered **source and overlay pages 78, 79, 105**. Four overlays use 9.5 pt; one ambiguous page-79 mapping remains blank. Original text and media boxes verified unchanged; output has three pages. This uses archived eligible rows for typography testing only, not a new commercially approved offer.
- Test artifact: `outputs/ui_improvements_pdf_validation/typography_test_only.pdf`; mappings in `mapping.json`, source/render PNG pairs in the same directory.
- Standard external PDF-viewer check remains **unverified**: only the in-app browser is connected, and its PDF tab did not render visible page content. Rendered PNG inspection is verified; external viewer acceptance is not claimed.
- No generated project-summary PDF page exists in the current exporter; project summary remains in the UI/JSON. This task did not invent one or overlay unsupported summary cells.

## Remaining suite failures

These paths retain unfinished earlier parser/matcher changes and were not modified in this UI task:

1. `test_prompt_case_contains_no_prices_and_keeps_catalogue_candidate_boundary`: candidate retrieval supplies 1 candidate instead of the asserted 3.
2. `test_uppercase_dimension_h_is_not_parsed_as_hour_unit`: uppercase dimension H parsed as hours.
3. `test_all_reference_primary_products_and_source_supported_statuses`: exact association of `P8H078-001` fails. Therefore full production 22-reference reconciliation is not claimed. Isolated Phase 1 golden tests pass unchanged.

Full acceptance is pending those failures and a standard PDF-viewer inspection. Recommendation only: address the parser/matcher failures in a separate scoped task.

## Commands

Run from project root in PowerShell:

```powershell
$py = 'C:\Users\saiya\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py -m unittest discover -s tests
& $py -m unittest tests.test_unit_cost_overrides tests.test_jobs tests.test_api tests.test_bid_optimization tests.test_golden_examples tests.test_pdf_overlay
& $py scripts/validate_ui_pdf_typography.py
& $py -m uvicorn src.tender_pricing.api:app --host 127.0.0.1 --port 8000
```

In another PowerShell terminal:

```powershell
Set-Location frontend
npm test
npm run build
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

UI: http://127.0.0.1:5173/ ; backend documentation: http://127.0.0.1:8000/docs.

## Files changed in this task

- `src/tender_pricing/api.py`, `review_state.py`, `pdf_overlay.py`
- `frontend/src/app/App.tsx`, `App.test.tsx`, `types.ts`, `ReviewNavigationContext.tsx`
- `frontend/src/components/AppShell.tsx`, `PositionDrawer.tsx`, `PositionDrawer.test.tsx`, `PositionTable.tsx`, `WorkflowFooter.tsx`, `WorkflowFooter.test.tsx`
- `frontend/src/pages/WelcomeUploadPage.tsx`, `WelcomeUploadPage.test.tsx`, `EstimateReviewPage.tsx`, `BidOptimizationPage.tsx`, `FinalOfferPage.tsx`
- `frontend/src/styles/global.css`, `frontend/src/assets/equans-reference.jpg`
- `tests/test_jobs.py`, `tests/test_pdf_overlay.py`, `tests/test_unit_cost_overrides.py`
- `scripts/validate_ui_pdf_typography.py`, this document, `PHASE_STATUS.md`

Earlier Docling/matcher modifications and the supplied bundle, now isolated under `experiments/pipeline_bundle/`, were preserved. No matching integration, external AI calls, reference edits, commits or pushes performed.
