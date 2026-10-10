# Phase 2 Quality Audit

## 1. Test Results and Environment

The intended project environment for PDF-related Phase 2 work is the bundled Codex Python runtime:

```text
C:\Users\saiya\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe
```

Reason: this runtime includes `pdfplumber`, `pdfminer`, and `pypdf`. The default local Python used by `python` does not have `pdfplumber`, so real-PDF extraction tests are skipped there rather than falsely passing.

Actual test results after this pass:

```text
Bundled Codex Python:
Ran 20 tests in 2.916s
OK

Default Python:
Failed to find real location of C:\Python314\python.exe
Ran 20 tests in 0.052s
OK (skipped=2)
```

The skipped default-Python tests are the PDF-integration tests that require `pdfplumber`. Parser, matcher, classification, duplicate and conflict tests still run there.

## 2. Audit Scope and Methodology

Inputs inspected:

```text
BKP_244_LV_Lueftung_260804.pdf
catalog.csv
productivity.csv
example_lv_positions.csv
expected_output_example.json
outputs/phase2_full/extracted_positions.json
outputs/phase2_full/priced_positions.json
```

Method:

1. Re-ran the complete test suite in bundled and default Python.
2. Re-ran the full 202-page PDF extraction.
3. Reviewed status counts, duplicate groups, non-priceable classifications and conflict flags from the generated JSON.
4. Compared representative rows against German source text, quantities, units, attributes and selected catalogue/productivity records.
5. Programmatically checked every calculated row for quantity, unit, source page, catalogue match, install code, productivity rule, price basis and arithmetic fields.
6. Rechecked all 22 supplied examples by source page, quantity, unit and suggested product ID.

## 3. Current Extraction Coverage

Full run after this pass:

```text
PDF pages processed:                    202
position candidates extracted:          216
distinct confirmed position candidates: 179
confirmed non-priceable records:         37
calculated:                              34
supplier_quote_required:                 10
review_required status:                   8
insufficient_information:               127
duplicate candidate rows:                12
duplicate groups:                         6
rows with review_required=true:         145
rows with conflict flags:                 7
```

Count changes against the previous baseline of `216 candidates / 34 calculated / 10 supplier_quote_required / 8 review_required / 164 insufficient_information`:

```text
candidate count: unchanged
calculated count: unchanged
supplier_quote_required count: unchanged
review_required status count: unchanged
insufficient_information: 164 -> 127
new non_priceable status: 37
```

The 37-row reduction in `insufficient_information` is classification-only: rows already carrying `non_priceable_or_assembly_entry` evidence are now explicit `non_priceable` records instead of failed catalogue matches. No new row was automatically priced.

`distinct confirmed position candidates` is defined here as all emitted candidates except confirmed non-priceable records and exact duplicate extractions. There are no exact duplicate extractions in the current full output.

The 22 verified examples are still linked:

```text
22 / 22 found by source page, quantity, unit and suggested product ID.
```

This linking does not use hardcoded `LV0001` IDs. The PDF does not expose those IDs directly. The regression check links by independent evidence: source page, parsed quantity, normalized unit and suggested catalogue product.

## 4. Classification Rules

Confirmed non-priceable records are only assigned when explicit source-text markers indicate they are not standalone priced products. Failed matching alone is not enough.

Current confirmed non-priceable markers include German surcharge, colour, total, commissioning/documentation/table-detail and assembly-detail cues such as:

```text
sonderfarbzuschlag
farbbeschichtung
farbe ncs
total aller
einregulierung
inbetriebsetzen
nachkontrolle
anzahl kulissen
druckverlust
schallleistungspegel
verlaengerung
sockelrohr
standrohr
kulissendicke
spaltbreite
luftmenge
dokumentation
protokoll
```

Status and reason codes:

```text
non_priceable + confirmed_non_priceable + non_priceable_or_assembly_entry
insufficient_information + ambiguous_priceable_candidate + no_plausible_catalogue_match
insufficient_information + ambiguous_extraction + parsing_incomplete_or_low_context
review_required + technical_conflict_review_required
```

Example confirmed non-priceable record:

```text
page 78, "exkl. Sonderfarbzuschlag Stk 1"
status: non_priceable
classification: confirmed_non_priceable
```

Example intentionally not classified as non-priceable:

```text
page 80, "Zuluftgitter ... 25 x 10 cm Stk 2"
status: insufficient_information
reason: no_plausible_catalogue_match
```

## 5. Insufficient-Information Rows

Current `insufficient_information` count:

```text
127
```

Reason-code counts:

| Category | Reason Code | Count |
|---|---|---:|
| Parsing failure or incomplete extraction | `parsing_incomplete_or_low_context` | 35 |
| Missing or ambiguous quantity/unit | `missing_or_ambiguous_quantity_unit` | 0 |
| No plausible catalogue match | `no_plausible_catalogue_match` | 92 |
| Missing productivity rule | `missing_productivity_rule` | 0 |
| Conflicting technical specifications | handled as `review_required`, not insufficient | 7 |
| Supplier information required | handled as `supplier_quote_required`, not insufficient | 10 |
| Heading/assembly/non-priceable | handled as `non_priceable`, not insufficient | 37 |
| Other | none identified | 0 |

Representative examples:

```text
no_plausible_catalogue_match:
PDF080-04 page 80, Zuluftgitter, 25 x 10 cm, Stk 2.
No matching grille catalogue item exists.

parsing_incomplete_or_low_context:
PDF082-02 page 82, "Kanaltemperaturfühler Stk 6".
Likely controls/sensor content, but current evidence is too weak for reliable pricing.
```

## 6. Duplicate Handling

Current duplicate result:

```text
duplicate candidate rows: 12
duplicate groups: 6
exact_duplicate_extraction groups: 0
repeated_source_line_different_context groups: 6
```

Duplicate grouping uses source page, exact source line, quantity and unit. It does not delete or merge records. Description similarity alone is not used.

Representative duplicate groups:

```text
page 78: source line "exkl. Sonderfarbzuschlag Stk 1" appears under repeated context; preserved as non-priceable.
page 79: source line "Grösse (B x H) 10 Ø cm Stk 4" appears under repeated context; preserved.
page 80: source line "Grösse (B x H) 25 x 10 cm Stk 2" appears under repeated context; preserved.
page 135: source line "Grösse Ø 10 cm Stk 2" appears under supply and exhaust valve contexts; preserved as legitimate repeated positions.
```

If an exact duplicate extraction is encountered later, it is flagged with `duplicate_review_required=true` and any calculated status is demoted to `review_required`. No such exact duplicate exists in the current full output.

## 7. Conflict Detection

Conflict detection is review-only. It never selects a different price and never upgrades a row to calculated.

Current conflict flags:

```text
rows with conflict flags: 7
diameter_mismatch: 5
dimension_mismatch: 2
```

Representative conflicts:

```text
PDF079-02 page 79:
"Ø 12.5 cm Stk 6" matched by weak semantic evidence to P-AIR-003, but P-AIR-003 is DN100.
status: review_required
conflict: diameter_mismatch

PDF080-02 page 80:
"Ø 16 cm Stk 4" matched to P-DAM-001, but P-DAM-001 is DN125.
status: review_required
conflict: diameter_mismatch

PDF116-01 and PDF144-01:
"400 x 300 Stk 4" matched to P-FIR-004, but P-FIR-004 is 400x200 mm.
status: review_required
conflict: dimension_mismatch
```

Conflict checks are deliberately conservative:

```text
diameter: extracted row-level Ø/DN vs catalogue DN/model
dimensions: extracted row-level B x H / B x H x L vs catalogue dimensions
fire rating: extracted EI rating vs catalogue EI rating
```

The parser now also treats the PDF replacement character `�` as a diameter marker, because the source text sometimes extracts `Ø` that way.

## 8. Representative Correct Results

### Air Terminal, Page 78

PDF source:

```text
Zuluft - Tellerventil
Fabrikat z.B Trox Hesco
Typ z.B Z-LVS
Grösse Ø 10 cm Stk 5
```

Output:

```text
matched_product_id: P-AIR-001
install_code: DIFFUSER
quantity/unit: 5 pc
technical diameter: Ø 10 cm -> 100 mm
status: calculated
direct_position_cost_chf: 806.26
```

Assessment: correct. German `Zuluft - Tellerventil`, model hint `Z-LVS`, unit and diameter support the English catalogue item `Supply air valve DN100`.

### Fire Damper, Page 79

PDF source includes:

```text
Brandschutzklappen eingemauert
Feuerwiderstandsklasse EI 90-S
Typ z.B.FKRS-EU / FK2-EU
Grösse (B x H) 10 Ø cm Stk 4
```

Output:

```text
matched_product_id: P-FIR-001
install_code: FIRE_DAMPER
quantity/unit: 4 pc
fire rating: EI90-S
model hints: FKRS-EU / FK2-EU
status: calculated
direct_position_cost_chf: 8,369.77
```

Assessment: correct. The match is supported by fire rating, model hints, diameter and the English catalogue item `Fire damper EI90-S DN100 with actuator`.

### VAV Controller Variants, Page 164

PDF source:

```text
TVR-D 12.5 60 200 150 Stk 10
TVR-D 16   120 400 150 Stk 6
TVR-D 20   180 600 150 Stk 12
```

Output:

```text
P-VAV-003, P-VAV-004, P-VAV-005
install_code: VAV_CONTROLLER
status: calculated
```

Assessment: correct for the verified example rows. The rows are matched by model `TVR-D`, diameter-size row and quantity, not by literal English description.

## 9. Pricing-Status Safety

All current `calculated` rows were checked programmatically for:

```text
positive parsed quantity
normalized unit
source_page
matched_product_id
install_code
price_source
net_unit_cost_chf
material_cost_chf
adjusted_install_hours
labour_cost_chf
direct_position_cost_chf
matching productivity rule
```

No missing required pricing fields were found.

Rows without adequate evidence remain one of:

```text
insufficient_information
review_required
supplier_quote_required
non_priceable
```

No pricing formula, Phase 1 golden output or project baseline calculation was changed.

## 10. Tests Added

Regression tests added in this pass:

```text
test_non_priceable_rows_are_classified_without_losing_traceability
test_failed_catalogue_match_is_not_automatically_non_priceable
test_duplicate_source_occurrences_are_preserved_and_annotated
test_catalogue_dimension_conflicts_are_review_only
```

Previously added Phase 2 safety tests remain active:

```text
test_unsupported_vfc_variants_are_not_priced_as_dn250_controller
test_round_pipe_silencer_variants_are_not_priced_as_kosd_package
test_uppercase_dimension_h_is_not_parsed_as_hour_unit
```

## 11. Remaining Risks and Next Actions

Verified findings:

```text
22 / 22 known example positions are linked.
All 34 calculated rows have required pricing and traceability fields.
37 rows are now explicitly non-priceable instead of ambiguous insufficient-information rows.
7 technically suspicious matches are review-only via conflict flags.
Duplicate source occurrences are preserved and annotated, not merged.
```

Known limitations:

```text
The full tender is not comprehensively priced.
Non-priceable classification is heuristic and marker-based.
Some duplicate groups may still need estimator interpretation.
Several likely priceable classes lack catalogue coverage or reliable matching rules.
No probabilistic or LLM matching is currently active.
```

Recommended next step: stay in Phase 2 and improve catalogue coverage or deterministic rules only for product families that are actually supported by the supplied catalogue, starting with the largest `no_plausible_catalogue_match` groups. Do not start API, n8n or UI yet.

## 12. Planned AI-Assisted Matching Experiment

The current production pipeline remains deterministic. No LLM calls, API credentials, AI ranking modules, frontend work or golden-output changes are implemented.

`PHASE2_AI_MATCHING_EXPERIMENT.md` defines a future offline evaluation track for a review-only AI-assisted candidate ranker. The planned experiment will use a human-labelled failure-analysis dataset sampled from `insufficient_information` and `review_required` rows, compare the existing rule-based matcher with AI-ranked candidates, and restrict all AI candidates to products already present in `catalog.csv`.

The planned structured AI output must include candidate product IDs, evidence, technical mismatches, ambiguity and a recommendation of `accept`, `review` or `abstain`. It must not invent catalogue items, prices, productivity rules or supplier quotes.

Any future integration must satisfy the documented stop/go criteria first, including zero unsafe accepts on the human-reviewed sample. Until then, AI output is only a proposed estimator-review aid and must not change production pricing status or totals.
