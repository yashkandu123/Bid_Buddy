# Phase 8H Extraction Coverage Report

## Scope

This pass improves extraction coverage only. It does not add assumption-based pricing, change pricing formulas, change bid scenarios, or change PDF overlay eligibility.

## Parser Changes

- Added dotted unit support for `Stk.` and `Std.` while preserving the original source unit.
- Added symbol unit support for `m²` and `m³`, normalized internally to `m2` and `m3`.
- Added guarded reversed quantity/unit parsing for split layouts such as `1 Stk`.
- Added unit-without-quantity extraction for equipment rows such as `Zuluftgerät 1-1 Stk`; these keep `quantity=0.0` and are reviewable, not priceable.
- Added a separate `Bauteilliste Lüftung` component-table parser.
- Added `record_type` metadata:
  - `tender_position`
  - `tender_position_missing_quantity`
  - `component_list_row`
  - `labour_service`
- Component-list and labour-service rows are explicitly blocked from automatic catalogue pricing until a reviewed rule exists.

## Before / After Full-Tender Counts

The old baseline is the existing generated output at `outputs/phase2_full/priced_positions.json`. The new count is an in-memory parse/match of `BKP_244_LV_Lueftung_260804.pdf`; existing output files were not overwritten.

| Metric | Before | After |
|---|---:|---:|
| Candidate records | 216 | 568 |
| calculated | 34 | 34 |
| supplier_quote_required | 10 | 10 |
| review_required | 8 | 8 |
| insufficient_information | 127 | 469 |
| non_priceable | 37 | 47 |

New extraction by `record_type`:

| Record type | Count |
|---|---:|
| tender_position | 254 |
| tender_position_missing_quantity | 6 |
| component_list_row | 306 |
| labour_service | 2 |

Duplicate safeguards remain traceability-based:

| Duplicate classification | Count |
|---|---:|
| unique | 551 |
| repeated_source_line_different_context | 17 |

## Affected Page Examples

| PDF page | Before | After | New coverage |
|---:|---:|---:|---|
| 67 | 0 | 2 | `Zuluftgerät 1-1 Stk` as missing-quantity equipment row; `1 Leerteil Stk. 1` |
| 71 | 0 | 2 | `Fortluft 1-2 Stk` as missing-quantity equipment row; `- TW-1/70 A+-592-287-450-H 1 Stk` |
| 75 | 0 | 51 | `Bauteilliste Lüftung` component rows, for example `3938 L Luftleitung 150 500` |
| 110 | 3 | 7 | Dotted-unit controls such as `Drehantrieb, 20 Nm, Stk. 2` and `Kanalrauchmelder Stk. 1` |
| 131 | 0 | 56 | `Bauteilliste Lüftung` component rows, for example `3802 L Luftleitung 100 350` |
| 135 | 7 | 10 | `DSD-Lampenkassette Alu 1000x290mm Stk. 3`, `Std. 176`, `Einregulierung Std. 21` |
| 197 | 2 | 2 | Existing roof mounting rows remain extracted; no additional speculative rows added |

Largest page-level increases are component-list pages: page 156 (+56), page 131 (+56), page 75 (+51), page 100 (+45), page 157 (+41), page 182 (+34), page 132 (+13), and page 101 (+10).

## Safety Notes

- Newly extracted component-list rows are `insufficient_information` with reason code `component_list_requires_assumption_or_catalogue_rule`.
- Newly extracted labour-service rows are `insufficient_information` with reason code `labour_service_requires_productivity_rule`.
- Missing-quantity equipment rows are `insufficient_information` with reason code `missing_or_ambiguous_quantity_unit`.
- Specification numbers such as `700 m3/h`, filter area text such as `Filterfläche 6.5 m²`, dimensions such as `B x H`, and table placeholder dots are guarded against false positive pricing rows.
- Accepted pricing counts remain unchanged: 34 calculated and 10 supplier-quote-required.

## Remaining Limitations

- This still does not prove equivalence to the colleague's 720-position count; her source output/code is not available for a definitive unit-of-count comparison.
- Component-list rows are extracted as reviewable technical rows, not priced assumptions.
- Equipment rows with only a visible unit and no parsed quantity remain reviewable and unpriced.
- Some newly extracted tender rows are classified as `non_priceable`; this is intentional when existing German markers indicate service, total, note, or assembly-style rows.
