# Phase 8A UI Architecture and Feasibility Plan

This is an audit/design document only. It does not implement the frontend, change pricing formulas, change extraction/matching behavior, or call an LLM.

## 1. Current Backend Capabilities

Implemented FastAPI endpoints in `src/tender_pricing/api.py`:

| Endpoint | Request | Response | Notes |
|---|---|---|---|
| `GET /health` | none | `{status, service, schema_version}` | Current schema version is `phase4.v1`. |
| `POST /price/examples` | JSON `{ "dataset_id": "verified_examples" }` | 22 verified example positions, validation, totals, baseline warning | Request model forbids extra fields. No filesystem path input. |
| `POST /process/full-tender-output` | JSON `{ "dataset_id": "phase2_full" }` | Existing Phase 2 output normalized for API use | Reads fixed `outputs/phase2_full/priced_positions.json`. No filesystem path input. |
| `POST /jobs` | multipart PDF field `file` | `{job_id, status, created_at}` | Uploads to server-generated job directory, validates PDF header/readability/size, processes synchronously by default. |
| `GET /jobs/{job_id}` | path job ID | job status payload | Statuses: `queued`, `processing`, `completed`, `failed`. |
| `GET /jobs/{job_id}/results` | path job ID | completed job result JSON | Returns `404` unknown/missing result, `409` queued/processing, `500` failed. |

Job processing path in `src/tender_pricing/jobs.py`:

```text
PDF upload -> extract_pdf_text_pages -> parse_lv_positions -> match_positions
-> _normalise_position_payload -> segmented totals + baseline warning
```

Current job limitations:

- Job state is in memory.
- Uploaded PDFs/results are local files under `runtime_data/uploads` by default.
- `POST /jobs` processes synchronously in the current configuration.
- There is no authentication, database, durable queue, cancellation, retry, or multi-user ownership.

## 2. Current Data and Output Schemas

Position payloads already include the main fields needed for an estimator review table:

```text
lv_id
source_page
system
source_language
original_description
description
quantity
unit
original_unit
source_line
evidence
technical_attributes
matched_product_id
match_confidence
match_method
match_reason
classification / classification_reason_code / classification_reason
insufficient_reason_code / insufficient_reason
status
review_required
conflict_flags
duplicate_group_id / duplicate_count / duplicate_classification / duplicate_review_required
supplier_quote_required
catalogue_traceability
productivity_traceability
material/labour/direct cost fields when safely priced
```

Current full tender counts from the generated output/API result:

```text
positions:                   216
calculated:                   34
supplier_quote_required:      10
review_required:               8
insufficient_information:     127
non_priceable:                37
duplicate candidate rows:     12
conflict flagged rows:        11
```

Current totals are split by cost certainty in `src/tender_pricing/api_service.py`:

```text
confirmed calculated direct:          CHF 173,844.82
provisional supplier-package direct:  CHF 450,178.90
combined direct:                      CHF 624,023.72

confirmed calculated baseline:        CHF 192,611.66
provisional supplier-package baseline:CHF 499,709.91
combined baseline:                    CHF 692,321.57
```

Rows with `review_required`, `insufficient_information`, or `non_priceable` are excluded from confirmed and provisional totals.

## 3. Position Updates, Persistence, and Recalculation

No position-update endpoint exists today. The UI cannot safely persist estimator edits or recalculate accepted overrides without backend work.

Safe design for Phase 8B/8C:

1. Keep immutable machine output as the source trace:
   - raw job result remains unchanged;
   - estimator changes are stored separately as review state.
2. Add a review-state store, initially JSON under each job directory or a small SQLite store if durability/concurrency is needed:
   - `job_id`
   - `position_id`
   - selected/overridden `product_id`
   - quantity/unit correction, if allowed
   - status override
   - reviewer note
   - revision, timestamp, reviewer identity placeholder
3. Validate every accepted product against `catalog.csv`.
4. Validate productivity rule existence via `productivity.csv`.
5. Recalculate through the existing Python pricing engine only.
6. Preserve original German text, source page, machine match, conflict flags, duplicate annotations, and human override side by side.
7. Do not let AI recommendations or UI-only state authorize pricing.

Required backend endpoints before a real review UI can save changes:

```text
GET   /jobs/{job_id}/review-state
PATCH /jobs/{job_id}/positions/{lv_id}/review
POST  /jobs/{job_id}/recalculate
GET   /jobs/{job_id}/exports/json
GET   /jobs/{job_id}/exports/csv or xlsx
POST  /jobs/{job_id}/exports/priced-pdf
```

## 4. Existing Export Capabilities

Implemented:

- API returns structured JSON for examples, fixed Phase 2 output, and upload-job results.
- CLI `scripts/process_demo_tender.py` writes:
  - `extracted_positions.json`
  - `priced_positions.json`
- Existing repo also contains example output files:
  - `outputs/example_priced_positions.csv`
  - `outputs/example_pricing_results.json`

Not implemented:

- priced-PDF export;
- review-state export;
- job result CSV/XLSX endpoint;
- PDF coordinate extraction;
- original-PDF price overlay.

## 5. Product-Type Categorization Strategy

Page 3 should use product-type tabs, not pricing-status tabs. Pricing status should remain a separate filter/badge.

Catalogue-backed categories from `catalog.csv`:

| Display Category | Catalogue Evidence |
|---|---|
| Air terminals | `Air terminal`: supply valve, exhaust valve |
| Ductwork and fittings | `Ductwork`: circular duct, circular bend, rectangular duct |
| Dampers and flow control | `Damper`, `Flow controller`: manual damper, CAV/VAV |
| Silencers | `Silencer`: rectangular, compact |
| Fire protection | `Fire protection`: fire damper, seals, inspection cover |
| Insulation | `Insulation`: thermal/weatherproof insulation |
| Equipment/packages | `Equipment`: AHU and fan supplier packages |
| Controls | `Controls`: field devices |
| Supports | `Support`: angle set |
| Other / unclassified | unmatched or unsupported tender families |

Tender text also contains unsupported or partially covered families such as `Regenhut`, `Lamellenhut`, `Gitter`, kitchen packages, mounting feet/rails, and some sensors. These should not be forced into a catalogue-backed category unless evidence exists.

Primary display category assignment:

1. If a row has `catalogue_traceability.category`, map that category to a display category.
2. If the row is `review_required` because of critical conflict flags, display it as a proposed category with a review badge.
3. If no catalogue match exists, use deterministic German source signals:
   - `Zuluft`, `Abluft`, `Tellerventil` -> Air terminals signal.
   - `Kanal`, `Rohr`, `Bogen` -> Ductwork and fittings signal.
   - `Drosselklappe`, `Volumenstromregler`, `VFC`, `TVR`, `TVJ`, `VVS` -> Dampers and flow control signal.
   - `Schalldämpfer`, `Schalldoempfer`, `MS-F`, `KOSD` -> Silencers signal.
   - `Brandschutz`, `EI30`, `EI 90-S`, `Durchdringung` -> Fire protection signal.
   - `Dämmung`, `Aussendämmung`, `Mineralwolle`, `V2A Ummantelung` -> Insulation signal.
   - `Feldgerät`, `Fühler`, `Sensor` -> Controls signal.
4. If signals conflict or are weak, use `Other / needs classification`.

Separate filters:

```text
status
system
install_code
source page
supplier_quote_required
review_required
conflict flag code
duplicate group
source_type
match method
```

Ambiguous classifications must remain reviewable and must not change pricing status.

## 6. Bid Optimization Audit

Implemented production code:

- No bid-optimization implementation was found in `src/`, `scripts/`, or tests.
- Existing pricing code calculates position costs and project cost baselines only.

Inputs in `project_parameters.json`:

```text
reference_win_probability: 0.55
price_sensitivity_probability_points_per_1pct_price: 0.05
strategic_appetite_adjustment: 0.05
competition_adjustment: -0.05
minimum_probability: 0.05
maximum_probability: 0.95
scenario_margins_pct:
  Aggressive: 2.5
  Target: 4.0
  Conservative: 6.5
round_to_chf: 1000
```

Reference scenario outputs in `expected_output_example.json`:

| Scenario | Margin | Bid Price | Estimated Win Probability | Expected Contribution |
|---|---:|---:|---:|---:|
| Aggressive | 2.5% | CHF 426,000 | 0.69 | CHF 7,986.03 |
| Target | 4.0% | CHF 432,000 | 0.63 | CHF 10,951.01 |
| Conservative | 6.5% | CHF 444,000 | 0.49 | CHF 14,418.68 |

The bid-price values are consistent with using the expected reference baseline `CHF 414,489.12` and rounding up to CHF 1,000:

```text
414,489.12 / (1 - 0.025) = 425,117.05 -> 426,000
414,489.12 / (1 - 0.040) = 431,759.50 -> 432,000
414,489.12 / (1 - 0.065) = 443,303.87 -> 444,000
```

Important limitation: the expected contribution formula is not uniquely established by the source files, and the expected baseline itself has the documented unresolved CHF 392.57 discrepancy. The UI must label win probability as an illustrative/demo estimate unless real historical bid data or an implemented model is added.

Required backend work for Page 4:

- Add a deterministic bid-scenario function using explicit documented inputs.
- Decide whether the base is confirmed-only, provisional-only, combined estimate, or user-selected.
- Surface the baseline discrepancy warning beside scenario results.
- Label probability as unsupported/model estimate unless backed by real data.
- Add tests for bid price, rounding, margin, expected contribution, and probability clamping.

## 7. Original PDF Price-Fill Feasibility

Observed tender PDF evidence:

- `BKP_244_LV_Lueftung_260804.pdf` has 202 pages.
- Sampled pages have extractable text and characters; they are not scanned images.
- Page size in sampled pages is about `595.38 x 841.98` points, rotation `0`.
- Header columns include `Einheits- Preis` around x ≈ 449-480 and `Betrag Fr.` around x ≈ 513-537.
- Quantity/source lines appear around x ≈ 85-432, leaving blank price columns to the right.

Representative page 80 coordinate evidence:

```text
source line: "Druckverlust 30Pa Stk 4"
line bbox: x 85.08 to 432.39, y 434.80 to 444.82
unit-price header: x 448.66 to 479.82
amount header: x 513.46 to 536.97
```

Feasibility:

- An overlay can likely preserve original appearance by drawing price text onto a transparent PDF layer and merging it onto the original.
- A small prototype should use representative pages first, not the full 202-page document.
- Price placement should use extracted word coordinates for source lines plus calibrated target x positions for unit-price and amount columns.

Prototype proposal:

1. Pick pages 78, 80, 107, and 169 because they contain air valves, dampers, silencers, supplier packages, and insulation.
2. Add a coordinate extraction function that returns:
   - page number;
   - matched `lv_id`;
   - source line;
   - line bbox;
   - candidate unit-price x/y and amount x/y;
   - confidence/reason.
3. Generate a prototype overlay for those pages only.
4. Render original and overlay pages to PNG.
5. Validate:
   - prices are in the correct columns;
   - no overlap with existing text;
   - totals equal API totals for included statuses;
   - review/provisional/non-priceable rows are visibly marked or left blank according to estimator choice.

Risks:

- Some positions span several lines or pages.
- Some extracted rows are assembly/detail rows, not priceable tender lines.
- Repeated source lines and duplicate groups must not be overwritten without review.
- The current output has page references but no stored PDF coordinates.
- Fonts may not match exactly.
- Page rotations appear normal in sampled pages, but full-document validation must check all pages.
- Pixel-perfect output should not be promised until the prototype is visually verified.

## 8. Proposed React + Vite Structure

The repo has no frontend project today. Proposed location:

```text
frontend/
  package.json
  index.html
  vite.config.ts
  src/
    main.tsx
    app/
      App.tsx
      routes.tsx
      apiClient.ts
      types.ts
    pages/
      WelcomeUploadPage.tsx
      ProcessingPage.tsx
      EstimateReviewPage.tsx
      BidOptimizationPage.tsx
      FinalValidationPage.tsx
    components/
      AppShell.tsx
      Stepper.tsx
      StatusBadge.tsx
      ProductTypeTabs.tsx
      PositionTable.tsx
      PositionDrawer.tsx
      TotalsPanel.tsx
      ConflictFlags.tsx
      SourceTrace.tsx
    styles/
      tokens.css
      global.css
```

Page journey:

1. Welcome and tender upload:
   - call `POST /jobs`;
   - show accepted PDF name and validation errors.
2. Processing/job progress:
   - poll `GET /jobs/{job_id}`;
   - route to results on `completed`;
   - show safe errors on `failed`.
3. Estimate and human review:
   - read `GET /jobs/{job_id}/results`;
   - product-type tabs;
   - status/review/conflict filters;
   - row drawer with German text, source page, evidence, catalogue/productivity traceability, duplicate/conflict flags.
   - Initial Phase 8B can be read-only if backend review persistence is not yet implemented.
4. Bid optimization:
   - show confirmed/provisional/combined cost bases;
   - show scenario table only after backend bid-scenario implementation or clearly mark reference-only demo data.
5. Final validation and priced-PDF generation:
   - show unresolved review items and supplier quotes;
   - block final export when required review is incomplete;
   - priced-PDF button disabled until overlay prototype/export endpoint exists.

## 9. Equans Design Cues

Observed from `Equans_Slides.pdf`:

- Wide 16:9 presentation layout.
- Dark blue/teal background, approximately `rgb(0,36,57)` from PDF object colors.
- Mint/green accent, approximately `rgb(112,189,149)`.
- White uppercase headings with strong weight.
- Small mint eyebrow labels above large page titles.
- Large photographic backgrounds with dark teal overlay.
- Thin line icons in mint.
- Numbered process steps such as `01 02 03 04 05`.
- Equans logo appears white with mint mark, often top-right or bottom-right.
- Layout uses generous whitespace, left-aligned typography, and horizontal process bands.

Approximation warning: exact brand fonts and color specifications were not supplied. Use these observations as UI direction, not official brand tokens.

Suggested UI tone:

- operational dashboard, not a marketing landing page;
- dark header/sidebar with white/mint accents;
- dense review table on light or very dark neutral surfaces;
- strong status badges for review safety;
- preserve German source text visibly in the review drawer.

## 10. API and Backend Gaps for Phase 8B+

Required for a production-like UI:

1. CORS configuration for Vite local dev.
2. Durable job/review state.
3. Position review/update endpoints.
4. Recalculation endpoint using existing pricing engine.
5. Catalogue browsing endpoint or static catalogue payload endpoint.
6. Export endpoints for JSON/CSV/XLSX.
7. PDF coordinate extraction and priced-PDF prototype/export endpoint.
8. Bid-scenario calculation endpoint.
9. Clear lockout rules for unresolved review rows and supplier quotes.

Can be done read-only without backend changes:

- upload PDF;
- show processing result;
- display positions/totals/statuses;
- filter by product type/status/system/conflicts;
- show source text and traceability;
- show existing segmented totals and baseline warning.

## 11. Ordered Implementation Phases

Phase 8B, read-only UI:

- Scaffold React + Vite in `frontend/`.
- Add typed API client for existing endpoints.
- Implement upload, processing, results table, product-type tabs, filters, totals, and traceability drawer.
- Add frontend tests for API typing, category mapping, totals display, safety badges, and failed-job handling.

Phase 8C, review persistence:

- Add backend review-state endpoints.
- Add explicit estimator override workflow.
- Recalculate via existing Python engine only.
- Add audit trail and regression tests.

Phase 8D, bid optimization:

- Implement deterministic scenario service with documented base selection.
- Clearly label win probability as illustrative unless evidence changes.
- Add tests for formulas, rounding, and warnings.

Phase 8E, priced PDF prototype:

- Implement coordinate extraction for representative pages.
- Generate overlay prototype only for selected pages.
- Render and visually/numerically validate.
- Expand only after prototype quality is proven.

## 12. Acceptance Tests

Read-only UI:

- Upload accepts a valid PDF and rejects non-PDF errors from backend.
- Job progress handles `queued`, `processing`, `completed`, and `failed`.
- Results display all 216 rows from current full-tender output.
- Product-type tabs do not change status or pricing.
- German descriptions and source pages are visible for every row.
- Supplier-package rows are labelled provisional, not confirmed supplier quotes.
- `review_required`, `insufficient_information`, and `non_priceable` rows are excluded from calculated totals.
- Baseline discrepancy warning is visible.

Review/recalculation:

- Invalid product IDs are rejected.
- Missing productivity rules prevent calculated status.
- Conflicts cannot be silently accepted without explicit human override.
- Original machine output remains available after edits.

Priced PDF:

- Overlay prototype aligns on sampled pages.
- Numeric values in PDF equal backend totals.
- Unpriced/review rows are not silently filled.

## 13. Local Commands

Current backend:

```powershell
& 'C:\Users\saiya\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m uvicorn src.tender_pricing.api:app --host 127.0.0.1 --port 8000
```

Current backend tests:

```powershell
& 'C:\Users\saiya\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests
```

Planned frontend after Phase 8B scaffolding:

```powershell
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

Planned frontend tests after Phase 8B scaffolding:

```powershell
cd frontend
npm test
```

