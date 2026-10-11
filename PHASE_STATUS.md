# Project Phase Status

## Cloud `/api/jobs` routing fix (2026-10-11)

- Root cause: the React production client called the deployment's same-origin `/api` base, producing `POST /api/jobs`, while FastAPI registered only root paths such as `/jobs`. Local Vite worked because its default base was `http://127.0.0.1:8000`, so it called the registered root route directly. No reverse-proxy/container configuration exists in this repository to strip `/api` before FastAPI.
- Moved the existing FastAPI endpoint decorators to one `APIRouter` and mounted that unchanged router at both root and `/api`. Upload, job status/results, review edits, bid scenarios/selections and final-offer endpoints now support both preserved-prefix and stripped-prefix proxy conventions.
- Frontend API base selection is explicit: Vite development defaults to direct local FastAPI; production defaults to same-origin `/api`; a non-empty `VITE_API_BASE_URL` remains authoritative and has trailing slashes normalized.
- Added a real multipart TestClient regression that uploads and processes a small PDF through both `/jobs` and `/api/jobs`, then retrieves status and results using the corresponding prefix. Added route-parity coverage for every application endpoint and frontend tests for development, production and configured API bases.
- Documented required reverse-proxy ordering in `docs/project/DEPLOYMENT_READINESS.md`: `/api/*` must reach Uvicorn before the SPA fallback. The cloud host itself is authentication-protected and returned 401 to unauthenticated probes, so the deployed fix still requires rebuilding/redeploying both backend and frontend before live verification.
- Validation: backend `162 passed` with 70 subtests and 95 deprecation warnings; frontend `26 passed` across 10 suites; TypeScript/Vite production build passed with 1,702 modules. The generated production JavaScript contains `/api` and no localhost API base. No pricing, job processing, matching, PDF overlay or UI workflow behavior changed. No commit or push.
- Recommendation only: redeploy, verify `GET /api/health`, upload one controlled PDF through `POST /api/jobs`, and confirm the returned ID through `/api/jobs/{id}` and `/api/jobs/{id}/results`.

## Deployment readiness cleanup (2026-10-11)

- Promoted the audited 229-row full-tender display manifest from ignored evaluation output to `data/full_tender_user_inventory.jsonl`; production inventory projection now behaves consistently in a clean checkout. Required `catalog.csv`, `productivity.csv` and `project_parameters.json` are versioned inputs rather than ignored local files.
- Isolated the externally supplied bundle under `experiments/pipeline_bundle/` and limited default Pytest discovery to production tests under `tests/`. Local evaluations, uploads, generated outputs, media, virtual environments, caches and secrets remain preserved locally and ignored.
- Added `.env.example`, deployment instructions and a documented production test command. `.env` exists locally, remains untracked and ignored, and no secret value was read or displayed.
- Removed only confirmed generated clutter: an empty nested project/runtime directory, a one-page Docling diagnostic PDF, a root PDF byte-identical to two retained runtime exports, and a root logo byte-identical to the versioned frontend asset.
- Restored rendering of backend scenario warnings and the saved-selection confirmation on Bid Optimization. No pricing formula, matching threshold, approval rule, API contract or PDF export behavior changed.
- Validation: backend `160 passed` with 36 deprecation warnings; frontend `23 passed` across 9 suites; production Vite build passed with 1,702 modules. The bundled Codex Python lacked Pytest, so backend tests ran in the project `.venv` (Python 3.14.5). Existing project Uvicorn and Vite processes returned HTTP 200 on ports 8000 and 5173; launcher preflight correctly rejected duplicate startup.
- Remaining limitations: job persistence remains local filesystem state, arbitrary rotated/non-zero-origin PDF overlays remain intentionally skipped, and the optional experiment bundle still lacks its separately documented copied data directory.
- Recommendation only: manually exercise upload, review edits, scenario selection and PDF export before any remote push or external deployment.

## Upload lifecycle and action-state fix (2026-10-11)

- Replaced parallel upload-page conditions with one derived lifecycle: empty, ready, uploading, processing, completed or failed. The status line and upload-panel action now use the same lifecycle, preventing ready/start labels during active work or after completion.
- Lifecycle behavior: no file shows `Upload a tender PDF to get started.`; selected file shows `Ready to process.`; the POST request shows `Uploading tender...`; a created queued/processing job shows `Processing tender...`; verified completion shows the existing success message and an enabled `Proceed to Estimate & Review`; failures show the backend error and an enabled retry when the source file remains available.
- Added a separate restoration stage and request-generation guard. Restoring an explicit job no longer blocks choosing a replacement file, and late responses from the superseded job cannot overwrite the new selection.
- Real UI/API verification used the preserved 20-page `runtime_data/e2e/phase8_ui_acceptance_tender_pages_78_97.pdf`. Observed ready, uploading and completed states; completion job was `98a9a69d609642d1a5f238f3b478df60`. The backend completed before a processing-only frame was sampled; that distinct queued/processing state is covered by the component test.
- Focused lifecycle tests 8/8 passed; complete frontend suite 22/22 passed across 8 files; production build passed. Changed `frontend/src/pages/WelcomeUploadPage.tsx`, `frontend/src/pages/WelcomeUploadPage.test.tsx`, and this status file. Existing APIs, styling, pricing, backend and unrelated pages remain unchanged. No commit or push.

## Upload stale-job root-cause fix (2026-10-11)

- Root cause: the bare `/` upload route automatically restored `lastTenderJobId` from local storage, so an unrelated earlier completed backend job appeared as the current upload. The JSX completion check was correct, but it was checking the wrong restored job.
- `WelcomeUploadPage` now restores only an explicit `/processing/:jobId` job and verifies it with `getJobStatus()` before rendering success. A fresh `/` visit stays neutral even when stale local storage exists. Selecting or starting a new upload still clears current job state immediately.
- Updated workflow and review-back navigation to carry the active job into `/processing/:jobId`, preserving intentional completed-job restoration between stages without making cached local storage authoritative on the fresh upload route.
- Added a direct regression test for empty storage/no job and another for stale stored completed-job data on `/`; the latter asserts no status request and no success message. Explicit routed restoration and stale in-flight response cancellation remain covered.
- Verified in the real browser with an existing stale `lastTenderJobId`: `/` displayed `Upload a tender PDF to get started.` and no green completion message. Focused tests 7/7 passed; complete frontend suite 21/21 passed across 8 files; production build passed. Changed `frontend/src/pages/WelcomeUploadPage.tsx`, `frontend/src/pages/WelcomeUploadPage.test.tsx`, `frontend/src/components/AppShell.tsx`, `frontend/src/pages/EstimateReviewPage.tsx`, and this status file. No design, backend, pricing or PDF behavior changed. No commit or push.

## Upload status-state correction (2026-10-11)

- The upload page now shows a neutral initial status, clears the previous job and message when a genuinely new upload starts, and displays completion only after `getJobStatus()` returns `completed`. The upload-creation response alone cannot trigger success.
- Fixed a stale restoration race: selecting a new file cancels the in-flight previous-job restoration effect, so a late completed response cannot overwrite the new upload state. Valid completed jobs still restore from local storage after backend confirmation; a temporary restore failure does not delete the saved job ID.
- Added frontend tests for neutral startup, backend-confirmed restoration, loading-before-final-status, backend processing failure, stale restoration cancellation, upload failure and successful advancement. Updated one stale app-shell heading assertion to the unchanged current page title.
- Verification: focused upload tests 6/6 passed; complete frontend suite 20/20 passed across 8 files; `npm run build` passed TypeScript validation and Vite production output. Changed `frontend/src/pages/WelcomeUploadPage.tsx`, `frontend/src/pages/WelcomeUploadPage.test.tsx`, `frontend/src/app/App.test.tsx`, and this status file. No backend, pricing, matching, theme or PDF behavior changed. No commit or push.

## Opening-page layout refinement (2026-10-11)

- Adjusted only home-specific CSS in `frontend/src/styles/global.css`: widened the welcome column, increased the inter-column gap, reduced and relaxed the welcome-heading typography, increased home-only header/navigation/content spacing, and placed the existing status/action footer lower in the available viewport without stretching panels or adding UI.
- Verified the rendered opening page at exactly 1366x768. Document scroll dimensions were 1366x768, the action footer ended at y=738, and no content was clipped or hidden. Existing upload, status and navigation order and behavior are unchanged; responsive layouts reset the desktop grid rows below 900px.
- Frontend production build: `npm run build` passed (`tsc --noEmit` and Vite; 1,702 modules transformed). No other page, component, backend behavior, pricing logic or PDF behavior changed. No commit or push.

## Frontend layout and typography refinement (2026-10-11)

- Refined the existing React layout without changing fonts, weights, colors, routes, interactions, API behavior or business logic. Reduced oversized page headings and excess spacing, changed the desktop workflow steps to a compact horizontal layout, and tightened panels, controls, tables, forms and drawers consistently across Upload, Review, Bid Optimization and Final Offer.
- Reorganized the Upload page into a two-column desktop layout so its introduction, upload action, workflow context and footer remain visible without vertical scrolling. Verified document dimensions at 1366x768, 1280x720 and 1024x768: viewport height equals document scroll height and there is no document-level horizontal overflow.
- Verified mobile behavior at 390x844. The page has no document-level horizontal overflow; dense review/final tables and product-category tabs retain intentional, contained horizontal scrolling. Long job paths and definition values wrap instead of widening the page.
- Visually inspected Upload at all listed viewports, plus Review, Bid Optimization and Final Offer at 1366x768, 1024x768 and 390x844. No clipped controls, incoherent overlaps or broken page-level alignment were observed.
- Updated one stale application-shell test assertion to match the unchanged visible product title, `From tender to contender`.
- Frontend tests: `npm test` passed 16/16 across 8 suites. Production build: `npm run build` passed with TypeScript validation and Vite output generation.
- Changed for this task: `frontend/src/styles/global.css`, `frontend/src/pages/WelcomeUploadPage.tsx`, `frontend/src/app/App.test.tsx`, and this status file. No backend, pricing, matching or PDF files changed. No commit or push.
- Recommendation only: retain the current local scrollers for dense tables rather than compressing their columns below readable sizes.

## Final PDF overlay integration hardening (2026-10-10)

- Kept the existing Phase 8F backend/API/React Final Offer flow and single PyMuPDF-independent overlay module; no second export engine, pricing change, matching threshold change, Stage 3 behavior change, catalogue change or API contract change was introduced.
- Removed the fixed-coordinate price-column fallback. Unit-price and total-price boundaries must now be detected from each PDF page's vertical geometry. Pages without validated columns and rotated pages without a validated transform are left blank with explicit placement reasons.
- Overlay typography now starts at 13 pt, remains right-aligned with a 4 pt inner margin, and shrinks only when actual cell width or row spacing requires it. Bounding boxes use Helvetica ascent/descent metrics and are validated horizontally and vertically before writing.
- Fresh full-tender job `0be57a7fd11c4a14b62806535cead9fb` processed the original 202-page PDF with external AI disabled. Of 27 pricing-authorized calculated rows, 22 mapped and 5 were left blank as ambiguous duplicate source lines: PDF079-03, PDF135-09, PDF135-10, PDF169-01 and PDF169-02. Sixteen overlays use 13 pt and six use 10.4 pt. Supplier quotes, review-only rows, insufficient rows and non-priceable rows remain excluded.
- Generated artifact: `runtime_data/uploads/0be57a7fd11c4a14b62806535cead9fb/final_offer/priced_offer.pdf`; validation and mapping reports are in the same `final_offer` directory. Render validation is under `runtime_data/e2e/final_overlay_validation_0be57a7fd11c4a14b62806535cead9fb/`.
- Visually inspected representative mapped and skipped layouts on source PDF pages 78, 79, 107, 113, 164, 169 and 170, plus a contact sheet covering all 22 mapped rows. Prices fit within the detected cells without border or neighboring-row overlap. Page count, media boxes and rotations match the source on all 202 pages; a non-overlay page rendered pixel-identically.
- Live local HTTP smoke test exercised generation, report retrieval and PDF download for the job. The downloaded 8,844,630-byte PDF SHA-256 matched the backend artifact exactly.
- Tests: focused overlay/jobs/API suite 41 passed; complete backend suite 151 passed, zero failures/errors/skips. Frontend Vitest: 16 passed across 8 suites. Frontend production build passed. Initial frontend test/build attempts hit Windows sandbox `EPERM`; approved unrestricted reruns passed.
- Remaining limitation: repeated identical source lines cannot be assigned safely without stronger row evidence, so the five ambiguous rows remain blank for estimator review. Rotated layouts are deliberately unsupported until their coordinate transform is separately validated. No external AI calls, commit or push.
- Recommendation only: review the five blank ambiguous rows against the original tender before treating the export as commercially complete.

## Phase 2B full-tender end-to-end coverage evaluation (2026-10-10)

- Ran the actual `process_uploaded_pdf()` production path over all 202 pages with `pdfplumber` and AI disabled. It emitted 581 parser rows: 27 calculated, 28 supplier_quote_required, 53 review_required, 437 insufficient_information and 36 non_priceable; 108 rows had catalogue products and the job had zero processing failures. The 581 count is not a genuine-position denominator because it includes 306 Bauteilliste rows plus repeated/specification rows.
- Reconciled against the existing correction audit: 229 classified inventory rows represent an estimated 225 distinct source positions after collapsing four unresolved same-page duplicate/sub-item pairs. This remains an audit estimate, not a verified official LV count. Row statuses are 27 calculated, 19 supplier_quote_required, 53 review_required, 105 insufficient_information and 25 non_priceable; 99 rows have catalogue candidates.
- Distinct calculation answer: collapsing the four pairs by best available evidence yields 26 estimated distinct calculated positions. Excluding both unresolved groups that contain calculated rows gives 24 ambiguity-free calculated positions. The raw production status count remains 27; these three values answer different counting questions and must not be interchanged.
- Full page-batched OpenAI comparison used the same 229 inventory rows, existing catalogue and unchanged rules. Candidate retrieval covered 193 rows across 58 page requests. Provider failures: 0; deterministic validation rejected 4 malformed/cross-position outputs. On 22 verified labels, deterministic matching remained 22/22 and LLM top-1 was 21/22; LV0012 was rejected for a source-line association mismatch. LV0009 and LV0021 remained review-only.
- LLM safe decisions: 15 accept, 124 review, 86 abstain and 4 validation-rejected. All 15 accepts were already calculated by deterministic production; no previously uncalculated row became safely calculated and `pricing_authorized` remained false for every AI result. Production before/after status counts are therefore identical.
- Uncalculated blocker rows in the corrected inventory: 66 no plausible catalogue match, 34 incomplete/low-context parsing, 3 missing or ambiguous quantity/unit, 2 labour rows without productivity rules, 53 matched review rows, 19 pending supplier quotes and 25 non-priceable rows. The LLM ranked a candidate for 45/66 no-match rows, but safely accepted 0; these are human-labelling opportunities, not measured coverage gains.
- Live usage reported for 57/58 requests: 208,689 input tokens and 49,246 output tokens; one successful page response omitted usage. Cost was unavailable and not estimated. Secret values were not displayed.
- Artifacts: `evaluation/phase2b_full_tender/production_result.json`, `full_inventory_labelled.jsonl`, `llm_live_results.json`, `llm_dry_run.json`, `evaluation_summary.json` and local response cache. Added evaluation-only `scripts/prepare_full_tender_llm_evaluation.py`; production code and business rules were unchanged.
- Tests: targeted backend set 61 passed; final full backend suite 148 passed in 26.480 seconds, zero failures/errors/skips. No commit or push.
- Recommendation only: human-label the 45 unmatched rows with ranked candidates, then improve deterministic family/attribute rules only for verified recurring patterns. Separately correct parser over-segmentation so the upload API reports the audited inventory rather than 581 raw rows.

## Phase 2B page-batched LLM mapper (2026-10-10)

- Extended the existing isolated `ai_matching_experiment.py` path with page-batched OpenAI Responses requests. Each strict structured response is bounded to the supplied catalogue and position IDs and must exactly echo position ID, source page, source line, quantity and unit before it is accepted for evaluation.
- Added deterministic post-validation for rule/LLM product conflicts and missing or conflicting diameter, dimensions, fire rating and material evidence. Every AI result remains review-only with `pricing_authorized=false`; provider/schema failures retain the unchanged deterministic result as an explicit fallback.
- Added successful-response disk caching keyed by model and complete request payload. Errors are not cached. The CLI now supports `--page-batched` and `--cache-dir`; the original single-position experiment remains available.
- Authorized live evaluation used `gpt-4.1-mini` on 8 difficult, verified rows across 6 source pages/requests. Provider and validation errors: 0. LLM top-1 verified product: 8/8; current deterministic product: 8/8, so measured product-selection improvement was 0. All 8 safe decisions were review and 0 authorized pricing. Four raw accepts concerned supplier/uncertain rows and were correctly downgraded; safe calculation candidates: 0.
- Reported live usage: 11,305 input tokens, 3,053 output tokens, 27,022.62 ms aggregate request latency. Provider cost was unavailable and was not estimated. A repeat run served all 6 batches from the local cache with no provider errors.
- Artifacts: `evaluation/phase2b_page_batch/live_results.json`, `cache_replay_results.json`, mock outputs and local cache. Targeted AI tests: 25 passed. Final full backend suite: 148 passed in 26.937 seconds, zero failures/errors/skips.
- Changed for this pass: `src/tender_pricing/ai_matching_experiment.py`, `scripts/evaluate_ai_matching.py`, `tests/test_ai_matching_experiment.py`, and this status file. Existing unrelated working-tree changes were preserved. No parser, pricing formula, threshold, API/output schema, review-state rule, commit or push changed. Secret values were not displayed.
- Limitation: this labelled sample tests difficult rows the deterministic matcher already mapped correctly. It validates safe batching and cross-language ranking but does not demonstrate increased catalogue coverage. Recommendation only: human-label difficult currently-unmatched rows before considering any production integration.

## Phase 2B multilingual matching coverage (2026-10-10)

- Extended the existing `semantic_matching.py` path rather than adding another matcher. Added normalized German umlaut spellings and supported English/French HVAC phrases for silencers, VAV/CAV controllers, insulation, fire seals, AHUs and controls; added exact insulation-thickness scoring.
- Production may now auto-accept a semantic candidate only when it is the unique family match satisfying all available critical evidence (diameter, dimensions, fire rating and/or insulation thickness), has no ambiguous dimensions, no catalogue conflict and no multilingual family/material conflict. Existing 0.85 calculation threshold is unchanged; the new exact method returns 0.9. Non-exact semantic candidates remain 0.7 review-only.
- Comparable evaluation uses the 22 verified English reference descriptions with their original quantities/units. Before: 20/22 correct products, 2 false products, 0 calculated, 5 supplier_quote_required, 17 review_required. After: 22/22 correct products, 0 false products, 15 calculated, 6 supplier_quote_required, 1 review_required. LV0021 remains review because it lacks exact technical evidence; actual German LV0021 also retains its quantity conflict. Actual German LV0009 retains its model-length conflict and remains review-only.
- Added `scripts/evaluate_multilingual_matching.py` and regression tests for exact French valve/fire-damper/insulation/VAV matching, insufficient-evidence review, dimension-mismatch review, and all 22 English references. Original descriptions and technical attributes remain unchanged.
- Targeted run: 18 passed. Full bundled-Python backend suite: 133 passed in 14.085 seconds, zero failures/errors/skips. Golden pricing, API/jobs, review state, accepted-total safeguards and actual 22-reference production path all passed. No frontend interface or response schema changed; frontend rebuild not required for this backend-only change.
- Limitation: the reported 32/576 baseline was not reproduced and has no compatible labelled full-tender ground truth. This task demonstrates improvement only on the same 22 labelled English descriptions and targeted French cases; it does not establish a new full-tender calculated count.
- No live LLM/external service call, dependency, pricing formula, margin, threshold, catalogue ID, API contract, output schema, review-state rule, commit or push.
- Recommendation only: human-label a broader multilingual unmatched/review sample before expanding automatic semantic acceptance to families without exact technical evidence.

## Phase 2B production regression fixes (2026-10-10)

- Fixed AI candidate retrieval in `semantic_matching.py`: strict family filtering had returned only the existing exhaust-valve match. When a deterministic match exists, retrieval may now add lower-ranked siblings only when catalogue category, unit and component noun agree. The reviewed DN125 exhaust-valve prompt now contains exactly P-AIR-001, P-AIR-002 and P-AIR-003; unrelated dampers are excluded. Catalogue bounds, conflict validation and `pricing_authorized=false` behavior are unchanged.
- Fixed `position_parser.py` hour parsing: global case-insensitivity made dimension label `H` match the bare `h` hour unit. The single-letter hour token is now lowercase-only in both unit-before-quantity and quantity-before-unit forms. `B x H 110 x 35 cm Stk 1` parses as 1 pc, while `h 21`, `21 h`, `Std. 21` remain labour units.
- The P8H078-001 association failure was downstream of the same H/hour bug: page 78 had been parsed as 110 h instead of 1 pc. Exact association now succeeds from the unchanged source line, quantity and unit; no candidate-ID/source-page hardcode was added.
- Regression coverage added/updated in `tests/test_ai_matching_experiment.py`, `tests/test_phase2_extraction.py`, and `tests/test_phase_b2_matching.py`. Targeted final run: 6 passed. Full bundled-Python backend run: 129 passed in 13.152 seconds, zero failures/errors/skips; all 22 reference products/status safeguards and Phase 1 golden pricing passed.
- No pricing formulas, margins, thresholds, catalogue IDs, API/output schemas, approval rules, review state, pipeline-bundle code or PDF placement changed. No live LLM/external service call, commit or push.
- Remaining failures: none observed in the complete backend suite. Recommendation only: use the existing human-labelled review dataset before broadening candidate sibling rules beyond the tested catalogue component classes.

## Phase 2B pipeline-bundle audit (2026-10-10)

- Audited the now-isolated `experiments/pipeline_bundle/`: optional Docling+LLM extraction, regex fallback, translation/retrieval/LLM reranking, deterministic ID/supplier guard, and a separate copied pricing engine. The bundle omits its documented `data/` directory.
- Installed pytest 8.4.2 into the bundled Codex Python runtime. Ran the bundle's 13 offline/mocked tests in an isolated temporary copy populated with current project inputs and blank provider variables: 13 passed in 41.59 seconds. No live provider call.
- Deterministic bundle run: 263 LV rows; 53 calculated, 20 supplier_quote_required, 68 assumption_applied, 84 review_required, 1 insufficient_information, 37 non_priceable; 133 rows had product IDs. This population is not comparable with the reported 576-row baseline.
- Bundle selected all 22 expected primary reference product IDs, matching the last verified production result rather than improving it. It unsafely marked known-conflict LV0009 and LV0021 calculated; its LLM guard does not revalidate critical technical attributes, and assumption_applied enters priced totals. No production integration was made.
- Added `tests/test_pipeline_bundle_compatibility.py` (three offline tests: bounded multilingual retrieval, invalid-ID rejection, no-key stub) and `docs/project/PHASE2B_PIPELINE_BUNDLE_AUDIT.md`. All three new tests pass.
- Full backend: 127 run, 124 passed, 2 failures, 1 error. Pre-existing dirty-worktree issues remain: AI prompt candidate count, uppercase dimension H parsed as hour, and missing P8H078-001 parser association. Golden pricing, API/jobs, review safety and overlay tests pass. Frontend: 16/16 passed; production build passed.
- Root `.env` exists; only OPENAI_API_KEY appears configured. `.env` is ignored and untracked. The bundle supports OPENAI_API_KEY, DEEPSEEK_API_KEY and OPENROUTER_API_KEY but does not load `.env` itself. No secret value was displayed or copied, and no live LLM test occurred.
- Recommendation only: compare candidate rankers on human-labelled difficult rows before considering a retrieval-only adapter. Do not integrate the bundle reranker or copied pricing engine without stricter conflict validation and accepted-total compatibility.

## UI usability and PDF typography update (2026-10-10)

- Added Upload-contained processing, four workflow navigation stages, bottom actions, job-scoped navigation, pending-edit protection and the supplied Equans Switzerland image from assets/company logo.jpg. Existing layout/palette preserved.
- Extended existing review PATCH with finite non-negative net_unit_cost_chf overrides. Existing deterministic engine recalculates a copied catalogue product; original machine/catalogue values retained. Overrides persist on disk/recovery and flow into accepted PDF values. Quantity/cost autosave after 400 ms; errors remain visible. Conflict/excluded/supplier rules and golden pricing formulas unchanged.
- Overlay text 7.2 -> 9.5 pt (readable minimum 8.5), existing insets/column assignments retained; oversized prices are explicitly skipped. Three-page typography artifact outputs/ui_improvements_pdf_validation/typography_test_only.pdf, mapping.json and source/priced PNG pairs for pages 78/79/105. Four mappings visually inspected at 9.5 pt; one ambiguous mapping remains blank. Page count/geometry/original text preserved. No full tender regenerated.
- Final backend unittest discovery: 124 run, 121 passed, 2 failures, 1 error, zero skips. Remaining failures in untouched prior parser/matcher work: AI candidate count, uppercase dimension H as hours, P8H078-001 exact production reference association. Focused API/jobs/review/bid/golden/PDF suite: 60 passed. Frontend: 16 passed across 8 suites; TypeScript/Vite production build passed after approved Windows sandbox permission reruns.
- Desktop/mobile (390 px) Upload/logo visually inspected; existing saved 20-page job opened without edits. External standard PDF viewer unavailable; PNG visual validation verified, external viewer acceptance unverified. Current export has no generated summary PDF page. Full acceptance is not claimed while these limitations and three suite failures remain.
- Exact changed-file list, commands and limitations: docs/project/UI_IMPROVEMENTS.md. Earlier partial Docling/matcher work, user assets/pipeline_bundle, sources and reference artifacts preserved. No external AI calls, commits or pushes.
- Recommendation only: repair remaining parser/matcher tests separately and inspect typography_test_only.pdf in a standard PDF viewer before full acceptance.

## Parser and matcher improvements (2026-10-10)

- Worked directly on improve-parser-matcher; initial working tree clean. Changed position_parser.py, product_matching.py, added scripts/evaluate_parser_matching.py and tests/test_parser_matcher_improvements.py, and updated this status file. No reference, pricing, threshold, response-schema or export changes.
- Fixed decimal-comma matching, quantity-as-diameter and pressure-as-diameter false positives. Fire resistance alone no longer identifies a fire damper. Deterministic rules must respect catalogue units. German field-device candidates remain review-only at the existing 0.7 confidence, with combined sensors/switches rejected when catalogue coverage is insufficient.
- Parser isolates explicit field-device rows and preserves their immediately adjacent electrical specification. A preceding device cannot supply voltage to the next actuator. Original German text, quantity source line and PDF page retained; no new schema fields.
- New artifacts: outputs/parser_matcher_improvement/source_pages.json, before.json, after.json and improvement_report.md. Evaluation reuses the Phase B2 inventory association and production classifier, without costs; selected real PDF pages cover every reference plus 81/82/110/165/166. It is not a full-document coverage count or accuracy benchmark.
- All 22 primary reference products match before and after; 20 statuses match and 2 evidence-backed conflicts remain review_required: LV0009 model/table length, LV0021 penetration/set quantity. Existing pricing-engine golden tests also passed; those fixture tests alone do not exercise production matching, whereas Phase B2 reference tests do.
- Selected 69 inventory records: calculated 14 -> 14; supplier_quote_required 6 -> 6; review_required 7 -> 14; insufficient_information 40 -> 33; non_priceable 2 -> 2. Seven new field-device candidates are review-only, not newly authorized prices.
- Commands (bundled Python at C:/Users/saiya/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe): scripts/evaluate_parser_matching.py before, scripts/evaluate_parser_matching.py after; -m unittest discover -s tests -p test_parser_matcher_improvements.py -v (10 passed); -m unittest discover -s tests -v (109 passed, zero failures/errors/skips). Frontend npm test: sandbox EPERM prevented execution; unrestricted rerun passed all 11 tests across 6 suites. No external AI calls, commits or pushes.
- Remaining limitations: catalogue has no complete control-device specifications or combined temperature/humidity equivalence; generic candidates require estimator review. Quantity-only valves can retain low-confidence suggestions, never calculated. Existing full-document extraction and classification limitations remain. Recommendation only: review new control candidates and investigate unsupported variants using source evidence before expanding automatic rules.

## Review reconstruction compatibility fix (2026-10-10)

- Fixed review_state.py::_position_from_row, the only ExtractedPosition constructor that omitted record_type. The parser constructor already supplies it correctly.
- Current rows retain their explicit source record_type. Older saved results lack the field; reconstruction uses the existing parser's original-unit rule (hour units -> labour_service; other legacy units -> tender_position). No new dataclass default or response-schema field added.
- Added tests/test_review_state_compatibility.py: full parser/reconstruction round trip for all four record types, explicit type preserved after a unit edit, legacy unit semantics and legacy recalculation without payload-schema changes.
- Bundled Python command: `-m unittest tests.test_bid_optimization.BidOptimizationApiTests.test_job_bid_scenarios_use_saved_review_state tests.test_jobs.Phase4JobTests.test_final_offer_pdf_excludes_supplier_package_estimates tests.test_jobs.Phase4JobTests.test_final_offer_pdf_exports_only_accepted_calculated_prices tests.test_jobs.Phase4JobTests.test_insufficient_and_non_priceable_positions_stay_excluded_after_override tests.test_jobs.Phase4JobTests.test_product_change_with_dimension_mismatch_stays_review_only tests.test_jobs.Phase4JobTests.test_review_edit_is_saved_reloaded_and_recalculates_totals tests.test_jobs.Phase4JobTests.test_supplier_quote_required_override_remains_provisional tests.test_review_state_compatibility`: 11 passed, zero failures/errors/skips (seven previously failing tests plus four new tests).
- Then `C:/Users/saiya/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe -m unittest discover -s tests`: 99 passed in 14.030 seconds, zero failures/errors/skips. Golden tests and 22-reference production-path subtests ran as part of this suite; references unchanged. The malformed-PDF negative test emits its existing EOF diagnostic; suite succeeds.
- Pricing formulas, approval/exclusion rules, supplier-package provisional handling, dimension-conflict safeguards, fixtures and persisted outputs unchanged. No external calls, commits or pushes. Only review_state.py, new compatibility tests and this status file changed.
- No remaining backend test failure observed. Earlier entries describing seven errors are historical. Remaining Phase B matching/coverage and commercial limitations are unaffected; recommendation: review them separately before broader commercial validation. No next phase started.

## Project organization update (2026-10-10)

- Moved 18 phase/audit documents into docs/project, docs/architecture and docs/decisions; moved three loose outputs into outputs/legacy_root and instruction ZIP into archive. 22 moves total; full log and inventories in outputs/project_organization/.
- Retained production modules, tests, input/reference data, PDFs, baseline warning document, previous phase artifacts and runtime job storage at existing paths. No alternate colleague source implementation found. No files deleted, Git initialized or external calls made.
- Added scripts/audit_project_layout.py and documentation indexes; updated README and .gitignore. No application/test/frontend/business logic changes.
- Before/after backend tests: bundled Python unittest discovery, 95 run, 88 passed, 7 existing record_type reconstruction errors, zero skips. Syntax: 29 Python files parsed; both reference datasets retain 22 positions. Final hash/front-end verification recorded in outputs/project_organization/organization_report.md.
- Duplicate groups: 17, all preserved. Confidentiality of tender, brand assets, reference data and derived artifacts needs owner review before publication. .env contents were not accessed.
- Final verification: all 10,270 original files accounted for, zero preservation errors; moved-file/reference hashes unchanged. Root ordinary files 38 -> 16; three added index documents yield 10,273 files excluding the organization audit directory. Frontend permission reruns: 11 tests passed across 6 suites; production build passed. Archived instructions match root AGENTS/PROJECT_RULES, but archive PHASE_STATUS is an older snapshot.
- Recommendation: review publication eligibility and separately address existing backend failures. No next phase authorized or started.

## Verified Phase B2 update (2026-10-10)

- Changed production parser context retention and matching/classification logic in position_parser.py and product_matching.py; added cost-free classify_position reused by the pricing wrapper. Pricing formulas, thresholds, references and export logic unchanged.
- Added scripts/reconcile_phase_b2.py and tests/test_phase_b2_matching.py. Actual PDF extraction/parser/classifier exercised for all 22 reference products; no commercial pricing run.
- Artifacts: outputs/phase8h_phase_b2_matching/, including seven requested reports/datasets, reference comparison, previous-34 comparison and three source-page PNGs.
- Full document: 222 corrected inputs plus 7 evidence-backed recovered exclusions = 229 results. Statuses: 27 calculated, 10 supplier_quote_required, 17 review_required, 136 insufficient_information, 39 non_priceable. These are proposed classifications only; pricing_authorized=false and no cost fields for all results.
- All 22 reference primary products match; 20 reference statuses match. LV0009 retains model/table length conflict, LV0021 retains penetration-versus-angle-set quantity ambiguity; both review_required. Six expected supplier-package references remain supplier_quote_required with review flags.
- Of previous 34 calculated, 27 retain expected product and calculated status; seven have documented source conflicts. Forty archived Phase B product selections are not reproduced by the production matcher and need investigation; no global accuracy claim.
- Tests: final focused bundled run 46 passed, zero failures/skips; final default run 35 passed, zero failures/skips. Broad bundled suite 94 run / 87 passed / 7 errors / zero skips: unchanged review_state.py reconstruction omits required record_type.
- Limitation: prior Phase B generator absent; counts compare different implementations. Existing non_priceable classifier is not independently human-verified. No Git repository found. PDF text inspected on all reference pages, renders visually inspected on 80/107/171.
- Recommended next action: review the two reference conflicts and cross-implementation losses, then authorize the record_type integration repair and broader matching reconciliation. Commercial progression blocked; no next phase started.

> Update at the end of each task using verified artifacts and commands. Mark uninspected or unrerun details as unverified. A recommended next step is not permission to execute it.

## Project
Sprintd Hackathon — Equans “From Tender to First Price”  
Tender: `BKP_244_LV_Lueftung_260804.pdf`  
Expected project root: `D:\Sprintd Hackathon_Equans_Tender to priced offer`

## Last known state from conversation
**Reported state:** Phase B matching and B1 reconciliation completed; reference-example reconciliation and matching regression fixes are not yet verified as implemented. This summary comes from conversation reports; the local files have not been inspected in this setup task.

### Known inputs
- `README.md`
- `example_lv_positions.csv` — reported to contain 22 verified example positions/mappings; verify exact contents and meaning.
- `expected_output_example.json`
- `catalog.csv`
- `productivity.csv`
- `project_parameters.json`
- `BKP_244_LV_Lueftung_260804.pdf`

### Reported Phase 8G baseline
- Full PDF: 202 pages.
- Previous parser output: 216 candidate records.
- Reported status counts: 34 calculated, 10 supplier-quote-required, 8 review-required, 127 insufficient-information, 37 non-priceable.
- Historical figures; inspect artifacts or rerun relevant checks before claiming reproducibility.

### Reported Phase 8H extraction audit
- Initial audit: 259 candidates, estimated 152 distinct positions, 107 possible duplicates/repeated sub-items, 60 ambiguous candidates, 306 excluded Bauteilliste rows.
- The 152 estimate was reported as heuristic, not ground truth.
- A later correction pass was reported completed; Phase B used 222 candidates. Inspect correction artifacts before relying on detailed counts.

### Reported Phase B
Output: `outputs/phase8h_phase_b_matching/`
- 222 input candidates and 222 primary results.
- 63 matched, 159 unmatched.
- 209 human-review queue entries.
- Proposed statuses: 13 calculated, 13 supplier_quote_required, 93 review_required, 103 insufficient_information, 0 assumption_applied.
- No pricing fields/costs reportedly emitted.

### Reported Phase B1 reconciliation
Output: `outputs/phase8h_phase_b_reconciliation/`
- No artifact supporting exactly 32 calculated positions was found.
- Substantiated historical baseline: 34 calculated out of 216.
- Reported reconciliation: 6 remained calculated with same product; 4 remained calculated with changed product ID; 13 downgraded to review_required; 7 downgraded to insufficient_information; 4 removed as false positives; 3 new calculated rows.
- 17 likely matching regressions were flagged, including insulation thickness, fire-seal geometry, TVR-D variants, and air-valve/controller cases.

## Important unresolved issue
The 22 reference examples in `example_lv_positions.csv` have not yet been individually reconciled against the corrected 222-candidate inventory and Phase B results in the conversation. Do not implement matching changes until reference reconciliation and regression evidence have been reviewed.

## Next recommended action
Reconcile every reference example against the corrected inventory and Phase B results; establish whether existing tests exercise the production matching pipeline. Then consider narrowly scoped deterministic matching fixes with regression tests, if supported by evidence.

**Recommendation only. Do not execute without user approval.**

## Phase 2B matching-coverage investigation (2026-10-10)

- Rejected `576` as a unique-position denominator: it is one upload result row count. The correction artifacts support 218 estimated distinct source occurrences plus 7 previously reviewed recoveries, yielding an estimated 225 distinct positions; 8 rows remain unresolved duplicate/sub-item cases. After 21 non-priceable rows, the estimated potentially priceable denominator is 204. This remains an audit estimate, not an official LV count.
- Added narrow multilingual normalization for OCR replacement characters in known HVAC roots, German compound `Mineralwollplatten`, shared VAV/CAV flow-controller terminology, and source-row-first candidate retrieval. Catalogue candidate coverage on the same 229 classification rows increased from 54 to 111. Automatic calculated coverage remained 27/204; added candidates stay review/provisional where evidence is incomplete.
- Added deterministic safeguards for bend-angle mismatches and unconfirmed polyurethane construction. A DN250 45-degree buried-duct bend is no longer allowed to calculate against a DN250 90-degree catalogue bend. Pricing formulas, catalogue data, thresholds, APIs and output schemas were unchanged.
- Verified references: all 22 primary product IDs still match; 20 statuses match and LV0009/LV0021 retain their evidence-backed review status.
- Authorized live evaluation: 6 bounded OpenAI Responses requests, all successful and schema-valid; all returned `review`, all retained `pricing_authorized=false`. Usage reported: 5,628 input tokens, 2,301 output tokens, 23,457.21 ms aggregate latency; provider did not report cost. No human labels exist, so accuracy remains unmeasured. The model correctly described the sampled diameter, angle, thickness and catalogue-detail gaps; this is qualitative evidence, not an accuracy score.
- Artifacts: `evaluation/phase2b_coverage/coverage_summary.json`, `matching_results.jsonl`, `difficult_sample.jsonl`, and `ai_results_real.json`. Script: `scripts/evaluate_phase2b_coverage.py`.
- Tests: targeted matcher/AI suite `38 passed`; production backend suite `138 passed` with 4 Pydantic deprecation warnings. Repository-wide `pytest -q` produced `143 passed, 8 errors`; all errors are setup failures in the separate bundle tests because `experiments/pipeline_bundle/data/catalog.csv` and companion copied inputs are absent. That bundle was not integrated or modified.
- Limitation: the mentor's 95% calculable hypothesis is not supported by current verified evidence. Candidate retrieval was materially incomplete, but most recovered candidates lack exact technical equivalence, catalogue detail, or human labels. Recommendation: human-label the 57 recovered review/provisional candidates and resolve the 8 denominator ambiguities before considering additional automatic matching rules.

## Phase 2B 26-row live matching evaluation (2026-10-10)

- Corrected cohort interpretation: 111 rows had catalogue candidates in the prior artifact; 84 were uncalculated (62 review_required, 22 supplier_quote_required). The major blockers were supplier-commercial status, explicit technical conflicts, sparse catalogue specifications, and false candidates inherited from cumulative descriptions.
- Ran 26 authorized OpenAI Responses requests against bounded catalogue candidates: 26 succeeded, zero provider/schema failures, no pricing authorization. Usage was 29,476 input and 9,845 output tokens; measured aggregate latency 90,970.65 ms; provider cost unavailable. Secret values were not displayed.
- Eight rows had verified reference labels: top-ranked product accuracy was 8/8, but raw unsafe accept rate was 3/8 because the model accepted supplier-package products. The other 18 require human labels. No verified row qualified to become calculated.
- Added unsupported local-family rejection and source-row-first AI validation. Confirmed false smoke-detector-to-actuator matches and supplier-package accepts are now downgraded. Offline replay of saved responses: 24 review, 2 accept; the two accepts (P8H162-002 and P8H142-005) remain unlabelled and cannot be promoted.
- Recomputed 229-row inventory: matched candidates 111 -> 99; calculated 27 -> 27; review_required 62 -> 53; supplier_quote_required 22 -> 19; insufficient_information 97 -> 105; non_priceable 21 -> 25. The 12 removed assignments were unsupported candidates, not verified products. All 22 reference products still match; LV0009 and LV0021 remain review-only.
- Artifacts: `evaluation/phase2b_llm_26/representative_sample.jsonl`, `ai_results_real.json`, `revalidated_results.json`, and `report.md`. Scripts: `scripts/prepare_phase2b_llm_sample.py` and `scripts/revalidate_phase2b_llm_results.py`.
- Tests: targeted suite 42 passed; full production backend suite 142 passed with 4 existing Pydantic deprecation warnings. Pricing formulas, catalogue data, thresholds, API contracts and output schemas unchanged. No commit or push.
- Recommendation only: obtain estimator labels for P8H162-002 and P8H142-005, then evaluate a narrow deterministic rule if both are confirmed. Do not integrate raw LLM acceptance into pricing.

## Per-task checklist
- [ ] Read `README.md`, `PROJECT_RULES.md`, and this file.
- [ ] Read `example_lv_positions.csv` and `expected_output_example.json` for relevant work.
- [ ] Inspect relevant source code, tests, and prior outputs.
- [ ] Confirm task scope and required inputs.
- [ ] Preserve prior artifacts and unrelated working changes.
- [ ] Run relevant tests and record actual outcomes.
- [ ] Update this file with verified results and unresolved issues.

## Estimate & Review corrected inventory integration (2026-10-11)

- Root cause: uploaded jobs persisted and returned every production parser row, so the frontend correctly rendered all 581 raw rows. The audited full-tender inventory was used only by evaluation scripts and was never projected into the job-results API.
- Added `src/tender_pricing/user_inventory.py`. For the recognized full tender it associates the existing audited manifest by page, source line, quantity and unit, and returns the 229 retained rows. The projection is applied only when every manifest occurrence is present; unrelated tenders keep their normal parser output.
- Raw job `result.json` files remain unchanged for traceability. Existing production position IDs and row pricing values are retained. Review saves, recovered jobs, status counts, project totals, bid scenarios and PDF export now consume the same user-facing row inventory.
- Verified against `evaluation/phase2b_full_tender/production_result.json` and `evaluation_summary.json`: 581 stored raw rows, 229 displayed rows, no `component_list_row` records displayed. The 225 distinct count remains an audit estimate; eight rows in four unresolved duplicate/sub-item groups remain visible for human review.
- Existing persisted full-tender job verification: 229 response rows; 27 calculated, 19 supplier-quote-required, 53 review-required, 104 insufficient-information and 26 non-priceable. The one-row status difference from the evaluation artifact (105/25) is preserved production classification, not an inventory/count change.
- Tests: `pytest tests -q` -> 154 passed, 54 subtests passed, zero failures/skips; `npm test` -> 23 passed across 9 files; `npm run build` succeeded. Vite tests/build required execution outside the filesystem sandbox because Windows denied `realpath` inside it.
- Limitation: the corrected projection depends on the existing local full-tender evaluation manifest. If it is absent or does not fully associate, the system deliberately falls back to unfiltered parser output rather than partially hiding rows.
- Recommendation: promote the audited manifest to a maintained versioned project data asset before distributing the application to a clean checkout.

## PDF overlay alignment correction (2026-10-11)

- Root causes verified on the real tender: overlays started at a fixed 13 pt although source rows are 10.02 pt; vertical placement used a synthetic band between neighboring lines, moving page-78 row two from its real y=135.24 baseline to y=113.97; substring matching could select a generic description that omitted the position quantity; mappings were not checked for two positions sharing one output cell.
- `pdf_overlay.py` now reads each matched line's PDF text-matrix baseline, font size and y bounds; starts at 9.5 pt for the 10.02 pt tender text; shrinks for narrower/shorter cells and smaller source typography; keeps the 4 pt horizontal inset and right alignment. Rotated pages and non-zero MediaBox origins remain blank unless a validated transform exists.
- Source association now requires the row quantity even for substring matches. A final page-level collision check rejects multiple approved positions resolving to the same price baseline. Existing calculated/pricing-authorized eligibility remains unchanged; no pricing, catalogue, review-state, API or schema changes.
- Validation artifact: `outputs/pdf_overlay_alignment_validation/aligned_overlay_validation.pdf`; mapping and summary beside it; source/overlay renders under `renders/`. Visually inspected pages 78, 79, 105, 107 and 169 at 144 dpi. Nine positions mapped at 9.5 pt; `PDF079-03` remained blank because two source rows are indistinguishable. Page geometry and rotations match the selected source pages.
- Regression coverage: adaptive source font sizing, exact PDF matrix baselines, adjacent rows, multiple values in one position block, duplicate output-cell rejection, ambiguous rows, price-cell bounds, oversized values, missing columns, page rotation and non-zero MediaBox origin. `pytest tests/test_pdf_overlay.py -q`: 14 passed. Full backend: 159 passed plus 54 subtests, zero failures/skips. Frontend production build passed.
- Frontend suite: 21 passed and 2 existing Bid Optimization tests failed consistently because their expected copy (`supplier-package catalogue estimates`, `Saved Target for this job`) is absent from the current modified page. No frontend files were changed in this task; these failures are unrelated to PDF overlay behavior.
- Limitation: arbitrary rotated or non-zero-origin PDFs are safely skipped rather than transformed. Recommendation: add a separately validated transform before supporting those geometries.
