# Implementation Handoff: From Tender to First Price
## AI-powered HVAC tender pricing assistant — Equans Switzerland Hackathon

## 1. Mission and success criteria

Build a usable web application that takes the supplied ventilation tender PDF for **Primary School Oberglatt, BKP 244 Lüftungsanlagen**, extracts its relevant bill-of-quantities (LV) positions, matches them to the supplied catalogue and installation rules, calculates an indicative price, and lets an estimator inspect and correct the results.

This is an **estimator decision-support tool**, not an autonomous bidding system. Prioritise a clear end-to-end workflow, traceable calculations, and visible uncertainty over complex AI/ML or production-grade infrastructure.

### Required workflow

1. Ingest the full tender PDF.
2. Identify systems and relevant LV positions.
3. Extract position IDs (where present), descriptions, quantities, units, technical attributes and source-page references.
4. Match each position to a catalogue product or supplier package and an installation rule.
5. Estimate installation hours and labour cost.
6. Calculate direct costs, project costs, overhead, cost baseline and indicative selling price.
7. Show evidence, assumptions, confidence, and a clear status for every relevant position.
8. Let the user review/edit proposed matches and assumptions and recalculate totals.

### Success criteria

- Attempt to process the **full tender**, not only the 22 supplied example positions.
- Complete at least one position calculation end to end and validate it against the reference output.
- Present a meaningful portion of the tender in a reviewable table.
- Keep source-page traceability and uncertainty visible.
- Never silently invent a product, supplier quote, quantity, or price.
- Every relevant position must receive an explicit outcome, including cases that cannot yet be priced.

## 2. Supplied files and their roles

Keep these files together in the project data directory. The uploaded package contains:

| File | Purpose |
|---|---|
| `BKP_244_LV_Lueftung_260804.pdf` | Main tender document. A 202-page PDF containing the ventilation tender, conditions and LV positions. |
| `catalog.csv` | 56 catalogue/product or supplier-package records. Contains product IDs, categories, descriptions, units, list prices, discounts, net costs, installation codes and quote-required flags. |
| `productivity.csv` | 22 installation rules. Contains work type, unit, base hours per unit, labour role, default hourly rate and project-factor keys. |
| `project_parameters.json` | Project-specific productivity factors, allowances, project costs, overhead, target margin, rounding and bid-optimization settings. |
| `example_lv_positions.csv` | 22 verified example LV positions with systems, source pages, descriptions, quantities, units, expected installation codes, suggested product IDs and ground-truth statuses. |
| `expected_output_example.json` | Reference calculations for those example positions, aggregate subset totals and three bid scenarios. |
| `README.md` | Short project overview, formulas, statuses and golden-example instructions. |
| `Equans_Slides.pdf` | Hackathon brief and judging expectations. |

The reference JSON explicitly describes itself as a **verified example subset**; its totals are not the total price for the full tender. The full tender remains the product target.

### Data loading

Use pandas for CSVs and Python's JSON library for the parameter/reference files, or equivalent tools in the chosen stack. Preserve IDs as strings and preserve original source fields.

```python
import json
import pandas as pd

catalog = pd.read_csv("catalog.csv")
productivity = pd.read_csv("productivity.csv")
examples = pd.read_csv("example_lv_positions.csv")

with open("project_parameters.json", encoding="utf-8") as f:
    parameters = json.load(f)

with open("expected_output_example.json", encoding="utf-8") as f:
    expected = json.load(f)
```

Do not modify the supplied reference files to make tests pass. Keep extracted tender data, computed results and user edits separate.

## 3. Scope and phased delivery

**The web UI is explicitly deferred.** Follow the delivery order in Section 13: first make the Python pipeline correct without n8n; then add a small n8n workflow that calls the backend; then add long-running job handling; build the web UI only in a later phase. Do not let n8n or frontend work block the pricing baseline.

The current phase should produce these outputs:

1. A page-aware extraction of relevant LV positions from the full tender PDF.
2. Structured position records containing descriptions, quantities, units, technical attributes and source-page references.
3. Product and supplier-package match proposals linked to catalogue IDs, installation rules, price sources and confidence/review information.
4. Deterministic position calculations and project-level cost aggregates.
5. An explicit status and explanation for every relevant position, including items that cannot yet be priced.
6. Machine-readable output, preferably JSON, plus CSV exports where useful, so a later UI can consume the results without rewriting the core logic.
7. Automated tests comparing the 22 verified example positions with `expected_output_example.json`.

Start with a command-line runner and reusable Python modules. Add a small API only after the core pipeline runs and tests pass. Keep processing, matching, calculation and aggregation independent of both n8n and any future UI.

## 4. Architecture and implementation approach

Use the team's existing stack if one already exists. If starting from scratch, a practical backend-first prototype stack is:

- **Language:** Python.
- **PDF extraction:** `pdfplumber` or another PDF text extraction library; extract page by page. Add OCR only for pages that are scanned or have unusable text.
- **Data processing:** pandas for the provided CSVs; standard JSON handling for configuration and output.
- **Calculation engine:** ordinary deterministic Python functions, separate from the LLM.
- **Initial interface:** command-line runner. Add a small FastAPI (or equivalent) backend after the pipeline is tested; the API is for orchestration and later integration, not a web UI.
- **Persistence:** local files or SQLite are enough for the first demo. Use a small jobs table or JSON-backed job store only when adding asynchronous processing. Avoid infrastructure that does not improve extraction, pricing or validation.

Suggested code separation:

```text
src/
  data_loading.py
  pdf_ingestion.py
  position_parser.py
  normalization.py
  product_matching.py
  calculation_engine.py
  project_aggregation.py
  output_serialization.py
  schemas.py
scripts/
  process_demo_tender.py
data/
  supplied CSV, JSON and PDF files
tests/
  golden-example tests
  calculation tests
  extraction and matching tests
outputs/
  extracted_positions.json
  priced_positions.json
  project_summary.json
```

These names are suggestions, not mandatory filenames. Keep modules small, testable and independent of any future frontend. If an API is useful, expose functions for processing a project, listing positions, updating reviewed inputs and returning a summary; do not build screens or frontend routes in this phase.


### Backend API contract (add after the CLI pipeline works)

Keep the first API intentionally small. Suggested endpoints are illustrative and can be adjusted to the implementation:

- `GET /health` — confirm the backend is running.
- `POST /process-demo` — process the supplied demo project without uploading a new PDF; useful for early integration tests.
- `POST /jobs` — accept a PDF upload, create a job ID, and start processing asynchronously.
- `GET /jobs/{job_id}` — return `queued`, `running`, `completed` or `failed`, plus progress and error details where available.
- `GET /jobs/{job_id}/results` — return the structured positions, price breakdowns, evidence, flags and project summary when completed.

Do not implement all endpoints before the Python functions are stable. Begin with `/health` and `/process-demo`, then add `/jobs` when the full tender takes too long for one request. Avoid sending a 202-page PDF through multiple services unnecessarily; have one clear upload path and pass a stored file reference or job ID after upload.

The results contract should be versioned and UI-neutral. Include `job_id`, processing status, positions, project totals, warnings, and source-page evidence. Do not return only a formatted narrative. For errors, return a useful error code/message without exposing secrets or full server paths.

### n8n orchestration (after the Python pipeline passes tests)

n8n is an orchestration layer, not the pricing engine. Do not move complicated PDF parsing, matching logic or arithmetic into a large chain of Code nodes. The first workflow should be small:

1. **Webhook** receives a request or a demo-processing trigger.
2. **HTTP Request** calls the Python backend.
3. **Respond to Webhook** returns the response for short-running demo calls.

For long-running full-tender jobs, use a second pattern: a webhook starts a job and returns its `job_id`; the caller checks `GET /jobs/{job_id}` until the job completes, then fetches results. Prefer the UI or a client polling the backend directly rather than creating a busy polling loop inside n8n. If a webhook starts a long job, return promptly instead of keeping the HTTP connection open for the entire PDF processing run.

Add IF/Switch routing for failed jobs or positions needing review only after the basic call succeeds. Store credentials in n8n credentials, not in workflow text. Test the workflow manually before connecting any coding-agent MCP integration. MCP is optional and should be introduced only if it saves time after the workflow is understandable and working.

### Web UI (later phase — explicitly out of scope now)

Do not build screens, styling, frontend routes, dashboard components or upload UI during the current backend phase. The future UI should consume the versioned backend results contract and display position-level evidence, source pages, confidence, review flags and totals. Decide later whether the browser uploads directly to the backend or through n8n; do not build both paths.

## 5. Core data model

Use structured objects internally; do not rely on free-form LLM prose as the source of numeric truth.

### Tender position

Recommended fields:
- `lv_id`: stable ID; use source ID if available, otherwise generate one.
- `system`: system/plant/area label, e.g. LA01.
- `source_page`: page number in the original PDF.
- `description`: original extracted German description.
- `quantity`: numeric quantity or null if not found.
- `unit`: normalized unit, while retaining the original unit.
- `technical_attributes`: dimensions, DN, material, fire rating, airflow or other relevant properties extracted from text.
- `manufacturer_hint`, `model_hint`: when present.
- `product_id`: selected catalogue ID or null.
- `install_code`: selected installation rule or null.
- `match_confidence`: score or qualitative confidence with an explanation.
- `price_source`: `catalog`, `supplier_package`, `assumption`, or other explicit source.
- `status`: one of the required statuses in Section 8.
- `review_required`: boolean.
- `evidence`: short supporting text and page reference.
- calculated fields: net unit cost, material cost, adjusted installation hours, labour cost, direct position cost.

Retain the original description and extraction evidence even after normalizing fields. Do not overwrite source text with an AI paraphrase.

### Product and installation records

- Use `product_id` to identify catalogue rows.
- Use `install_code` to join catalogue items to productivity rules.
- Check units are compatible before calculating. Supported example units from README: `pc`, `m`, `m2`, `h`, `LS`, `system`.
- Some catalogue entries are supplier packages and/or require a supplier quote. Respect `source_type` and `supplier_quote_required`; do not treat every `net_cost_chf` as a confirmed quote.
- If multiple candidates are plausible, return alternatives or request review rather than silently choosing an unsupported match.

## 6. Tender ingestion and extraction

The tender is a large PDF, so use a staged pipeline.

1. **Extract by page.** Preserve the PDF page number alongside every text chunk. Do not flatten the whole document into one untraceable string.
2. **Identify the LV region and structure.** Distinguish the actual priced positions from tender conditions, cover pages, summaries, blank price forms and other non-priceable content.
3. **Parse positions.** Identify position number/ID, description, quantity, unit, system/section and technical attributes. Keep multi-line descriptions together.
4. **Normalize conservatively.** Standardize numeric formats and units for calculations but preserve the raw text and original unit.
5. **Validate.** Flag missing quantities, ambiguous units, duplicate IDs, implausible values and extraction failures.
6. **Store evidence.** Every extracted position should link to the original page and, where feasible, include the relevant source snippet.
7. **Classify non-position content.** Use `non_priceable` for content such as headings or informational text that is not a priced work item. Use `out_of_scope` when a position is genuinely outside this assistant's scope.

The PDF is in German. Do not assume English-only extraction or matching. Keep German source descriptions visible; normalized matching terms can be stored separately.

Use the 22 verified example positions as an initial validation set, but do not simply display them as if they were a full tender extraction. A useful demo may seed or compare them while still attempting full-PDF extraction.

## 7. Product matching

Use a deterministic-first matching pipeline. An LLM can assist with interpreting technical descriptions, but the final selection must be reviewable and constrained to the provided data.

1. Compare unit compatibility.
2. Compare product category/subcategory and technical description.
3. Compare dimensions such as DN/diameter, rectangular dimensions, material, fire rating and other attributes when present.
4. Use manufacturer/model hints as supporting signals, not as the only criterion.
5. Use the product's `install_code` to select a matching productivity rule.
6. Return candidate ID, confidence, reason/evidence, price source and review flag.
7. If there is no defensible match, leave it unmatched and assign an appropriate status.

Do not invent catalogue products or prices. Never treat a product match as proof that the supplier price is current or confirmed.

### Confidence guidance

The provided expected output has example values such as `0.92` for catalog matches and `0.72` for supplier-package matches that require review. These are example reference values, not universal truths. Calibrate scores for the implementation and document what they mean. A numeric score should not conceal missing evidence.

## 8. Status handling

Use these status values from the README / challenge package consistently:

- `calculated` — enough supported inputs exist to calculate a position.
- `supplier_quote_required` — a supplier/package price needs confirmation; show any indicative cost as provisional if appropriate.
- `assumption_applied` — calculation depends on an explicit documented assumption.
- `review_required` — a human must confirm a match, extracted value or calculation input.
- `insufficient_information` — essential data is missing, so a defensible calculation cannot be made.
- `out_of_scope` — a work item is outside the supported scope.
- `non_priceable` — a heading, note or other tender content is not a priceable position.

Every relevant position must end with a clear outcome. Do not force all positions into `calculated`. A row may also have `review_required: true`; keep the status and boolean consistent and explain the reason.

## 9. Calculation engine

Implement and test calculations in ordinary code, not in an LLM response. Keep full precision internally and round displayed amounts consistently to CHF cents unless the reference behavior requires otherwise.

### 9.1 Material cost

README formula:

```text
material cost = quantity × net unit cost × (1 + material waste % / 100)
```

The provided project parameters specify `material_waste_pct = 4.0`. For a supplier package, respect its source/quote status and the relevant contingency setting; do not apply the same allowance twice.

### 9.2 Installation hours

README formula:

```text
installation hours =
    quantity × base hours per unit × project factors
```

Look up `base_hours_per_unit`, `default_hourly_rate_chf` and `factor_keys` in `productivity.csv`. Resolve factor keys using `project_parameters.json`.

Special rule from README: apply `site_efficiency` as **`1 / site_efficiency`**; multiply the other project factors directly.

Project factors provided include:
- `site_efficiency`
- `school_logistics`
- `mounting_height_school`
- `mounting_height_sports_hall`
- `timber_interface`

Only apply factors relevant to the position's installation rule and context. For example, do not apply the sports-hall mounting factor to every school position. If the applicable building area cannot be determined, flag the assumption for review.

### 9.3 Labour cost

```text
labour cost = adjusted installation hours × hourly rate
```

Use the hourly rate associated with the installation rule unless a documented, user-approved override is applied.

### 9.4 Direct position cost

```text
direct position cost = material cost + labour cost
```

For supplier packages, make sure the package cost is included once and labour is added according to the relevant installation rule. Avoid counting a package twice.

### 9.5 Project-level cost build-up

The source materials describe project direct cost as including:
- material and supplier packages
- installation labour
- engineering / project management
- transport and equipment
- special costs

The provided project parameters include:
- engineering: 420 hours at CHF 145/hour
- commissioning: 160 hours at CHF 155/hour
- hygiene inspection: CHF 18,000
- documentation: CHF 12,000
- small-material allowance: 3.5%
- transport/equipment allowance: 2.5%
- supplier-package contingency: 3.0%
- overhead: 8.5%
- target margin: 5.5%
- selling-price rounding: CHF 1,000

Use the actual parameter keys in `project_parameters.json`. Document the calculation base for every percentage. Avoid double-counting an allowance or cost already included in a product/package price. If the provided files do not unambiguously define the base for an allowance, make the interpretation explicit and configurable rather than silently guessing.

### 9.6 Cost baseline and indicative selling price

README formula:

```text
cost baseline = project direct cost + overhead
indicative selling price = cost baseline / (1 - target margin)
```

Treat percentages as decimals in code. With a target margin of 5.5%, divide the cost baseline by `1 - 0.055`. Apply configured rounding to the final display/price only at the appropriate final stage. Explain whether displayed margin is calculated on selling price, as implied by this formula.

The slide deck also mentions risk allowance / opportunities. Only implement these as separate explicit inputs if their values and calculation basis are defined; do not invent defaults.

## 10. Golden-example validation — do this early

Before building the entire interface, reproduce the reference result for `LV0001`. The README says it is on PDF page 78: five DN100 supply-air valves, matched to `P-AIR-001`, with installation code `DIFFUSER`.

The supplied expected JSON gives:
- quantity: 5 pc
- net unit cost: CHF 74.80
- material cost: CHF 388.96
- adjusted installation hours: 4.35
- labour cost: CHF 417.30
- direct position cost: CHF 806.26
- price source: `catalog`
- match confidence: `0.92`
- status: `calculated`

Create automated tests comparing computed values with `expected_output_example.json`, allowing a small numeric tolerance for floating-point calculations. Then validate all 22 example positions and compare status, product ID, installation code, hours and cost fields. Investigate discrepancies; do not hard-code output values for each ID.

The expected-output summary for the **22-position subset** is:
- material cost: CHF 277,626.29
- labour cost: CHF 95,073.83
- direct cost: CHF 372,700.12
- cost baseline: CHF 414,489.12

These are reference subset figures, not the full tender estimate. If an aggregate differs, identify whether the reason is rounding, allowance application, supplier-package handling or project-level costs.

## 11. Bid optimization — stretch goal only

Only after extraction, matching, calculation and review work end to end, implement the optional `Recommended Bid Range`.

The supplied parameters define three scenarios:
- **Aggressive:** 2.5% margin
- **Target:** 4.0% margin
- **Conservative:** 6.5% margin

Each scenario should display:
- bid price
- margin
- estimated win probability
- expected contribution

The example JSON includes sample scenario outputs. The parameters mention a reference win probability, price sensitivity, strategic appetite and competition adjustments, plus potential inputs such as historical bids, similar projects, relative price position, competitive intensity, client price sensitivity and available capacity.

Do not present an illustrative probability as a statistically validated prediction. The supplied package does not establish that real historical bid data is available. If no evidence is available, label probabilities as **illustrative/demo estimates**, expose assumptions and avoid overstating accuracy. Compare scenarios; do not claim the tool knows which bid will win.

## 12. Testing plan

### Unit tests
- CSV and JSON loading, required columns and missing values.
- Unit compatibility and product/install-code joins.
- Material cost, factor calculation, labour cost and position total.
- Supplier-package contingency and quote-required status.
- Margin formula and final rounding.
- Handling of null quantity, null price, unsupported unit and missing installation rule.

### Golden tests
- `LV0001` exactly as described above.
- All 22 records in `example_lv_positions.csv` against `expected_output_example.json`.
- Aggregate totals for the example subset, with documented rounding/tolerance.

### Integration tests
- Load the demo project.
- Process the PDF and retain page references.
- Produce structured positions and a project summary as JSON/CSV.
- Change a match or assumption through a test fixture or function call and verify that totals update.
- Confirm that unmatched or uncertain positions are not silently marked as calculated.
- Confirm that extraction or calculation errors are returned/logged clearly.

## 13. Suggested implementation order for a hackathon

Follow this order. Each phase should produce a working, testable result before moving on.

### Phase 1 — Python pricing baseline (no n8n, no UI)
1. Inspect the supplied CSV/JSON schemas and load the project data.
2. Implement the deterministic calculation engine and the product/productivity joins.
3. Pass the `LV0001` golden test, then validate all 22 examples against `expected_output_example.json`.
4. Record discrepancies rather than hard-coding expected values.
5. Create a CLI command that produces JSON/CSV outputs for the example subset.

**Exit condition:** repeatable tests pass, or any remaining discrepancies are documented and understood. Do not start with the full 202-page extraction if the cost formulas and reference data handling are not yet trustworthy.

### Phase 2 — Full-PDF extraction and matching
1. Parse the tender page by page and preserve original PDF page references.
2. Identify LV sections and extract positions, descriptions, quantities, units and technical attributes.
3. Validate extracted positions against the 22 known examples.
4. Match to catalogue and productivity rules; keep candidate evidence and confidence.
5. Calculate position costs and project totals, flagging missing or uncertain inputs.
6. Produce machine-readable JSON and CSV outputs.

**Exit condition:** one command processes the supplied PDF end to end and emits reviewable, traceable results. Do not claim the 22-position reference totals represent the entire tender.

### Phase 3 — Small Python API
1. Add `/health` and `/process-demo` endpoints around the already-tested pipeline.
2. Keep the API response contract structured and versioned.
3. Test API outputs against the CLI outputs to ensure both use the same business logic.
4. Keep synchronous processing only if it reliably finishes within the chosen server/request timeout.

**Exit condition:** an HTTP client can call the backend and receive the same result as the CLI for the demo project.

### Phase 4 — First n8n workflow
1. Create a workflow manually with a Webhook trigger, an HTTP Request node and Respond to Webhook.
2. Call `/health` first, then `/process-demo`.
3. Inspect input and output data at each node and test failure cases.
4. Add only the minimum routing needed for errors. Keep all pricing logic in Python.
5. Use n8n credentials for secrets. Do not connect MCP or an agent until the manual workflow is understood and working.

**Exit condition:** a request sent to the n8n webhook triggers the Python backend and returns structured results.

### Phase 5 — Full PDF upload and job status handling
1. Add `POST /jobs` to accept a PDF, store it safely and return a job ID promptly.
2. Process the PDF asynchronously and persist job status, progress, warnings and failure details.
3. Add `GET /jobs/{job_id}` and `GET /jobs/{job_id}/results`.
4. Test queued, running, completed and failed states, plus invalid PDFs and duplicate requests.
5. Decide on one upload path for the future UI: either browser → backend, or browser → n8n → backend. Do not implement both by default.

**Exit condition:** a 202-page tender can be submitted without holding the upload request open until all extraction and pricing finishes; results can be retrieved by job ID.

### Phase 6 — Optional agent/MCP integration
1. Only after the workflow works manually, configure n8n MCP for a supported coding agent if it provides a concrete productivity benefit.
2. Let the agent inspect or edit workflow configuration, but review all changes and test the workflow after each change.
3. Keep a shared Git repository, `AGENTS.md`, implementation notes and automated tests so Codex and Claude Code can work on the same project.
4. Avoid multiple agents editing the same files at the same time.

### Phase 7 — Web UI (later, not now)
Build the upload, progress, position-review and summary screens only after the backend contract and job lifecycle are stable. The UI should not contain pricing logic; it should call the backend and render its results.

### Stretch goal — bid scenarios
Implement the optional bid scenarios only after extraction, matching, calculation and job handling work end to end. Clearly label unsupported win probabilities as illustrative/demo estimates.

## 14. Guardrails and common failure modes

- **Do not price from LLM memory.** All product prices must originate from the provided catalogue, an explicitly labelled supplier package, or a visible user-approved assumption.
- **Do not fabricate missing quantities or specifications.** Flag them.
- **Do not silently choose weak matches.** Show alternatives, evidence and review status.
- **Do not ignore source pages.** Traceability is a core judging criterion.
- **Do not treat the 22 example rows as the full tender.** They are a verification subset.
- **Do not double-count costs or percentage allowances.** Define the base of each percentage and test it.
- **Do not hard-code expected results.** Calculate from the source data and use the reference JSON only for validation.
- **Do not rely on an LLM for arithmetic.** Use deterministic functions and automated tests.
- **Do not overbuild infrastructure.** The challenge explicitly prioritizes the estimator experience over complex AI/ML or production-ready architecture.
- **Do not claim real bid-win prediction without supporting data.** Mark the stretch-goal probabilities as illustrative when appropriate.
- **Preserve the German source text and technical units.** Normalized search terms should not replace original tender evidence.
- **Make limitations visible.** A first estimate is an informed starting point, not a final binding offer.

## 15. Definition of done for the prototype

The current-phase pipeline is ready when:

1. A command or function can load the supplied Oberglatt project data.
2. The pipeline attempts extraction across the full tender and retains source-page references.
3. It emits structured positions, match proposals, calculation breakdowns and explicit statuses as machine-readable output.
4. It produces project-level costs and an indicative selling price with assumptions documented.
5. The 22 verified examples are tested against the reference JSON, with discrepancies explained.
6. A match or assumption can be changed through a function/configuration input and the estimate recalculated.
7. Outputs distinguish verified, provisional, assumed, uncertain and illustrative values.
8. The Python pipeline is tested independently of n8n; the first n8n workflow calls the backend; long-running jobs return a job ID and expose status/results endpoints.
9. No web UI is built in this phase; the output contract is ready for a future UI implementation.

The central product principle is: **automate the groundwork, show the evidence, and leave commercial judgement with the estimator.**
