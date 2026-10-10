# Pricing Correctness Audit

Scope: focused audit before Phase 5. No frontend, database, n8n, LLM matching or review workflow was added.

## Supplier-Package Semantics

Rows with `supplier_quote_required=true` get numeric costs from `catalog.csv`, not from confirmed supplier quotes.

Source evidence:

```text
P-SIL-001 source_type=supplier_package supplier_quote_required=true net_cost_chf=2600.0
P-SIL-003 source_type=supplier_package supplier_quote_required=true net_cost_chf=5400.0
P-SIL-004 source_type=supplier_package supplier_quote_required=true net_cost_chf=3600.0
P-INS-003 source_type=supplier_package supplier_quote_required=true net_cost_chf=245.0
```

The calculation engine still applies the established Phase 1 position formula:

```text
material_cost_chf = quantity * net_cost_chf * (1 + material_waste_pct / 100)
labour_cost_chf = quantity * base_hours_per_unit * productivity_factors * hourly_rate
direct_position_cost_chf = material_cost_chf + labour_cost_chf
```

Example trace for `PDF080-03` / `P-SIL-001`:

```text
quantity: 4 pc
net unit cost: CHF 2,600.00 from catalog.csv
material waste: 4%
material cost: 4 * 2,600.00 * 1.04 = CHF 10,816.00
labour: SILENCER productivity rule estimate = CHF 1,078.56
direct position estimate: CHF 11,894.56
status: supplier_quote_required
cost confirmation: provisional_supplier_quote_required
```

Implemented distinction:

```text
material_cost_basis = supplier_package_catalogue_estimate_pending_quote
labour_cost_basis = productivity_rule_estimate
direct_cost_basis = provisional_material_estimate_plus_labour_estimate
cost_confirmation_status = provisional_supplier_quote_required
```

Confirmed catalogue rows use:

```text
material_cost_basis = catalogue_net_cost
cost_confirmation_status = confirmed_catalogue_cost_basis
```

## Totals

Before this pass, API totals exposed one combined estimate:

```text
combined material: CHF 435,880.80
combined labour:   CHF 188,142.92
combined direct:   CHF 624,023.72
combined baseline: CHF 692,321.57
included rows: 44
```

After this pass, the combined estimate is preserved but split into confirmed and provisional subtotals:

```text
confirmed rows: 34 calculated
confirmed material: CHF 114,000.80
confirmed labour:   CHF  59,844.02
confirmed direct:   CHF 173,844.82
confirmed baseline: CHF 192,611.66

provisional rows: 10 supplier_quote_required
provisional material: CHF 321,880.00
provisional labour:   CHF 128,298.90
provisional direct:   CHF 450,178.90
provisional baseline: CHF 499,709.91

supplier quotes outstanding: 10
```

Rows with `review_required`, `insufficient_information` or `non_priceable` remain excluded from both confirmed and provisional totals.

The Phase 1 22-example combined/golden summary remains unchanged:

```text
material: CHF 277,626.29
labour:   CHF  95,073.83
direct:   CHF 372,700.12
baseline under documented formula: CHF 414,096.55
reference baseline: CHF 414,489.12
unresolved discrepancy: CHF 392.57
```

## Dimension Parsing Findings

Defect found: `PDF080-03` on page 80 parsed model-code dimensions as centimetres:

```text
MS-F/300x400x1250/1x230/P
```

Old extraction treated `300x400x1250` as:

```text
unit=cm
values_mm=[3000, 4000, 12500]
```

Corrected extraction separates:

```text
model_code_dimensions:
  raw=300x400x1250
  unit=model_code_mm
  values_mm=[300, 400, 1250]

dimensions:
  raw=40 x 30 x 125 cm
  values_mm=[400, 300, 1250]

ambiguous_dimensions:
  raw=1x230
  unit=null
  no values_mm
```

Similar silencer rows `PDF107-04` and `PDF163-01` now also preserve model-code dimensions separately and flag `2x200` as ambiguous rather than inventing a unit.

## Catalogue Match Validation

Reviewed supplier-package matches:

```text
P-SIL-001: source has MS-F/300x400x1250 and explicit 40 x 30 x 125 cm; kept as supplier_quote_required.
P-SIL-003: source has MS-F/600x600x1750 and explicit 60 x 60 x 175 cm; kept as supplier_quote_required.
P-SIL-004: source has MS-F/540x400x1250 and explicit 54 x 40 x 125 cm; kept as supplier_quote_required.
P-INS-003: source rows are 100 mm external insulation / weatherproof cladding variants; kept as supplier_quote_required.
```

Equivalence is not treated as confirmed for these rows. They remain estimator/supplier-review candidates with provisional material estimates and productivity-rule labour estimates.

## Full Tender Re-Run

After regenerating `outputs/phase2_full`:

```text
candidates: 216
calculated: 34
supplier_quote_required: 10
review_required: 8
insufficient_information: 127
non_priceable: 37
```

Status counts did not change.

Conflict/review flags changed:

```text
before: 7 conflict-flagged rows
after:  10 conflict-flagged rows

diameter_mismatch: 5
dimension_mismatch: 2
ambiguous_dimension_unit: 3
```

The three new `ambiguous_dimension_unit` flags are silencer supplier-package rows with ambiguous model/accessory fragments such as `1x230` or `2x200`.

## Tests

Regression tests now cover:

```text
supplier package cost basis labels
confirmed vs provisional API totals
silencer model-code dimensions not parsed as centimetres
German decimal-comma dimensions with metre units
ambiguous dimensions preserved without invented units
supplier-package silencer kept provisional with review flags
real tender status/count expectations after re-run
```

Bundled Codex Python:

```text
Ran 42 tests in 3.589s
OK
```

Default Python:

```text
Ran 42 tests in 0.058s
OK (skipped=21)
```

## Remaining Risks

The supplier-package values remain catalogue estimates, not supplier-confirmed quotes. The API now exposes that distinction, but a future review workflow still needs estimator confirmation.

`P-INS-003` covers several 100 mm external insulation/cladding variants. The current deterministic match is useful as a candidate but still requires estimator/supplier review.

Some ambiguous dimension fragments may be product configuration rather than physical dimensions. They are intentionally review flags only and do not change pricing formulas.
