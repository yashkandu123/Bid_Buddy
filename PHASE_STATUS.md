# Project Phase Status

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

## Per-task checklist
- [ ] Read `README.md`, `PROJECT_RULES.md`, and this file.
- [ ] Read `example_lv_positions.csv` and `expected_output_example.json` for relevant work.
- [ ] Inspect relevant source code, tests, and prior outputs.
- [ ] Confirm task scope and required inputs.
- [ ] Preserve prior artifacts and unrelated working changes.
- [ ] Run relevant tests and record actual outcomes.
- [ ] Update this file with verified results and unresolved issues.
