# Phase 8E Original Tender PDF Overlay Prototype

This phase tests whether prices can be overlaid onto the original tender PDF while preserving its appearance. It does not implement full-document generation, frontend integration, new pricing formulas, supplier-quote confirmation, or LLM behavior.

## PDF Inspection

Source file:

```text
BKP_244_LV_Lueftung_260804.pdf
```

Observed structure:

- 202 pages.
- All pages have rotation `0`.
- Most pages are A4 portrait, approximately `595.38 x 841.98` points.
- Two pages are wider landscape-like pages, approximately `1190 x 842` points.
- Sampled pages 78, 79, 105, 107 and 169 are digitally structured, not scanned.
- Price-table headers are extractable on sampled pages.
- Sampled price columns are stable:
  - `Einheits-Preis` around x `448-480`.
  - `Betrag Fr.` around x `513-537`.
- Source quantity lines usually end around x `432`, leaving blank unit-price and amount columns to the right.

Known layout variation:

- Some pages split unit and quantity into separate visual columns while the extracted line merges or reorders them.
- Some descriptions span many text lines.
- Some source lines repeat on the same page.
- Some rows are supplier-package or unresolved and must remain blank for final overlay purposes.
- Full-document generation must check the two wide pages separately before expansion.

## Prototype Scope

Prototype pages:

```text
78, 79, 105, 107, 169
```

These cover air valves, fire damper ambiguity, VFC/control rows, silencers, and insulation.

Output folder:

```text
outputs/phase8e_overlay/
```

Generated artifacts:

```text
outputs/phase8e_overlay/prototype_price_overlay_pages_78_79_105_107_169.pdf
outputs/phase8e_overlay/prototype_price_overlay_mapping.json
outputs/phase8e_overlay/renders/
```

## Mapping Rules

The mapping code is isolated in `src/tender_pricing/pdf_overlay.py`.

Eligibility:

- Overlay only `calculated` rows.
- Exclude `supplier_quote_required`, `review_required`, `insufficient_information`, and `non_priceable`.
- Exclude supplier-package estimates even when they contain provisional cost fields.

Cell mapping:

1. Group extracted PDF words into visual lines.
2. Match each eligible position's `source_line` against lines on its `source_page`.
3. Require exactly one matching line.
4. Derive the unit-price and amount cells from the page's vertical table lines.
5. Place unit price in the `Einheits-Preis` column, right-aligned with a small inner margin.
6. Place position total in the `Betrag Fr.` column, right-aligned with the same margin.
7. Check formatted text width against the cell width and reduce font size only if necessary.
8. Leave ambiguous or unmatched rows blank and record the reason in mapping JSON.

Prototype value definitions:

```text
unit price = direct_position_cost_chf / quantity
position total = direct_position_cost_chf
```

These are accepted direct-cost prototype values, not final commercial selling prices.

## Prototype Result

For the sampled pages:

```text
eligible calculated rows: 10
mapped rows:              9
left blank by rule:       1
```

The deliberately blank row is:

```text
PDF079-03: ambiguous_line_match
```

Reason: page 79 contains two visually identical `Grösse (B x H) 10 Ø cm Stk 4` lines, so the prototype refuses to guess which cell belongs to the calculated row.

Supplier-package rows such as `PDF107-04` and `PDF169-04` are not eligible and remain blank.

## Visual Validation

Rendered prototype pages were inspected from:

```text
outputs/phase8e_overlay/renders/
```

Observed:

- Original page content and geometry are preserved.
- Prototype PDF has 5 pages matching the selected source-page dimensions.
- Overlaid values appear in the correct right-side price columns.
- Overlaid values are inset from the unit-price and amount column borders.
- Unit prices and total prices are visually distinct.
- No clipping or page rotation problems were observed on inspected rendered pages.
- No supplier-package estimate was overlaid.
- Ambiguous page 79 fire-damper row remains blank.

Limitations:

- Font is a close Helvetica overlay, not guaranteed to match the original PDF font exactly.
- Pixel-perfect full-document preservation is not yet proven.
- Coordinate rules are calibrated for sampled portrait tender pages only.
- Wide pages and pages without standard price headers still need a separate pass.
- Final commercial price allocation across positions is not yet defined.

## Commands

Generate the prototype:

```powershell
& 'C:\Users\saiya\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' scripts\prototype_pdf_overlay.py
```

Run tests:

```powershell
& 'C:\Users\saiya\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests
```

## Feasibility Finding

Original-layout price overlay is feasible for representative standard portrait tender pages, provided row-to-cell mapping is unique and the row has accepted calculated pricing.

The next experiment before full generation should add coordinate extraction for all pages, classify page layouts, and produce a report of unmapped, duplicate, rotated, wide, supplier-package, and unresolved rows before generating any full tender PDF.
