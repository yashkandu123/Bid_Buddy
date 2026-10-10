# Phase 2 Extraction and Matching Failure Analysis

This audit was performed before any AI integration. No LLM calls, API credentials, frontend work or arbitrary pricing changes were added.

## Scope

Inputs inspected:

- `PHASE2_QUALITY_AUDIT.md`
- `PHASE2_AI_MATCHING_EXPERIMENT.md`
- `src/tender_pricing/pdf_ingestion.py`
- `src/tender_pricing/position_parser.py`
- `src/tender_pricing/product_matching.py`
- `tests/test_phase2_extraction.py`
- `outputs/phase2_full/priced_positions.json`
- `BKP_244_LV_Lueftung_260804.pdf`

The sample dataset is stored at:

```text
evaluation/phase2_failure_analysis_sample.jsonl
```

## Method

1. Selected 16 rows from current `insufficient_information` and `review_required` records.
2. Included all 8 current `review_required` rows and 8 representative `insufficient_information` rows.
3. Traced every sample to its extracted PDF page text with bundled-Python `pdfplumber`.
4. Compared source text, extracted quantity/unit, technical attributes, current status, catalogue candidates and conflict flags.
5. Classified each failure cause and recorded recommended correction.

## Sample Summary

Sampled rows:

```text
review_required:          8
insufficient_information: 8
total:                   16
```

Failure categories in the dataset:

```text
catalogue_coverage:            11
matching_logic:                 2
duplicate/composite_position:   1
missing_technical_information:  1
```

No sampled row was classified as a pure OCR failure. No sampled row justified a production pricing upgrade.

## Confirmed Issues

Confirmed review-only matching defect:

```text
PDF115-01, page 115
Source: round EI30 penetration, "Grösse 25 Ø cm Stk 6"
Current candidate: P-FIR-002, rectangular EI30 fire seal 300x200 mm
```

Before this audit, the row was already `review_required`, but the conflict flags did not expose the round-vs-rectangular geometry mismatch. The fix adds a review-only `geometry_mismatch` conflict when extracted diameter evidence is compared with a catalogue item that only has rectangular dimensions.

This does not change Phase 1 formulas, golden examples, calculated rows, supplier-package provisional semantics or project totals.

Confirmed non-defects:

- DN125/DN160 air-valve and damper rows are correctly prevented from calculated pricing because catalogue coverage is missing or dimension conflicts exist.
- 400x300 BS-Dämmungen inspection-cover rows are correctly review-only against a 400x200 catalogue item.
- Regenhut and grille rows are correctly `insufficient_information` because the catalogue lacks those product families.
- Ventaflex underground duct rows should not be mapped to generic galvanized ductwork.
- VFC 8 rows are correctly not priced as CAV DN250.
- Round CA silencer table rows need table-aware parsing and/or catalogue confirmation before pricing.
- Kitchen hood/package rows are composite supplier-package content and should not be decomposed by the current matcher.

## Uncertain Issues Requiring Human Review

Controls rows such as `Kanaltemperaturfühler Stk 6` may be matchable to existing controls catalogue rows, but the current extracted context includes nearby smoke detector and field-device text. A human-labelled controls sample should be created before adding deterministic controls synonyms or pricing these automatically.

Round silencer rows may have enough table structure for future deterministic parsing, but the extracted table line does not establish equivalence with `P-SIL-002`.

Composite supplier offers, including kitchen hood packages, need dedicated supplier-package catalogue entries or a supplier-quote workflow. They should not be inferred from component dimensions alone.

## Output Impact

After regenerating `outputs/phase2_full/priced_positions.json`:

```text
position candidates:          216
calculated:                    34
supplier_quote_required:       10
review_required:                8
insufficient_information:     127
non_priceable:                 37
conflict flag instances:       11
```

The status counts are unchanged. The only output-level change is the added `geometry_mismatch` conflict flag for `PDF115-01`.

## Regression Tests

Added:

```text
test_round_penetration_does_not_hide_rectangular_catalogue_conflict
```

Updated:

```text
test_full_tender_output_endpoint_returns_phase2_structure
```

The API structure test now expects 11 conflict-flagged rows, reflecting the new review-only geometry conflict.

## Test Results

Bundled Codex Python:

```text
Ran 43 tests in 3.720s
OK
```

Default Python:

```text
Failed to find real location of C:\Python314\python.exe
Ran 43 tests in 0.059s
OK (skipped=21)
```

Default Python skips environment-dependent tests because required PDF/API dependencies are unavailable there.

## Recommended Next Step

Do not integrate AI yet. First, have a human estimator review `evaluation/phase2_failure_analysis_sample.jsonl` and mark accepted products, rejected candidates and true no-match cases. Use that labelled dataset as the first benchmark for the planned AI-assisted candidate ranker.
