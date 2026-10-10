# Baseline Reconciliation

## 1. Executive Summary

The project cost-baseline discrepancy is isolated to `cost_baseline_chf` in `expected_output_example.json`.

The supplied files establish the 22-position subset totals as:

```text
material cost: 277,626.29
labour cost:    95,073.83
direct cost:   372,700.12
```

The current implementation independently reproduces those totals from `example_lv_positions.csv`, `catalog.csv`, `productivity.csv`, and `project_parameters.json`. It then calculates:

```text
direct cost + small-material allowance on material + overhead on direct cost
= 372,700.12 + 9,716.92 + 31,679.51
= 414,096.55
```

The expected output says:

```text
cost_baseline_chf = 414,489.12
```

The unexplained difference is:

```text
414,489.12 - 414,096.55 = 392.57
```

The source files do not uniquely define a formula that produces CHF 414,489.12. The best root-cause assessment is unresolved: either the reference aggregate contains an inconsistency, or it was generated using an undocumented project-level convention. It is not explained by ordinary rounding, by a missed full project-cost component, or by a position-level calculation defect.

## 2. Source-of-Truth Inventory

Inspected files:

```text
project_parameters.json
expected_output_example.json
example_lv_positions.csv
catalog.csv
productivity.csv
from_tender_to_first_price_implementation_guide.md
README.md
README_PHASE1.md
src/tender_pricing/calculation_engine.py
src/tender_pricing/data_loading.py
tests/test_golden_examples.py
outputs/example_pricing_results.json
```

Relevant values from `project_parameters.json`:

```text
material_waste_pct:                 4.0
small_material_pct:                 3.5
transport_equipment_pct:            2.5
supplier_package_contingency_pct:   3.0
overhead_pct:                       8.5
target_margin_pct:                  5.5
round_to_chf:                       1000

engineering:        420 h * 145 CHF/h = 60,900.00
commissioning:      160 h * 155 CHF/h = 24,800.00
hygiene inspection:                    = 18,000.00
documentation:                         = 12,000.00
```

Relevant values from `expected_output_example.json`:

```text
scope: "Verified example subset; product target is the full tender."
position_results count: 22
example_subset_summary.material_cost_chf: 277,626.29
example_subset_summary.labour_cost_chf:    95,073.83
example_subset_summary.direct_cost_chf:   372,700.12
example_subset_summary.cost_baseline_chf: 414,489.12
```

The expected output contains final position rows, aggregate totals, and bid scenarios. It does not contain intermediate baseline components such as small material, transport/equipment, supplier contingency, project fixed costs, or overhead.

## 3. Calculation Trace

Position-level formulas from the README and implementation guide:

```text
material cost = quantity * net unit cost * (1 + material waste pct)
installation hours = quantity * base hours per unit * project factors
labour cost = installation hours * hourly rate
direct position cost = material cost + labour cost
```

`site_efficiency` is applied as `1 / site_efficiency`; other factors are multiplied directly.

Aggregating the 22 position rows:

```text
material cost = 277,626.29
labour cost   =  95,073.83
direct cost   = material + labour
              = 277,626.29 + 95,073.83
              = 372,700.12
```

Supplier package material is already included in material/direct cost:

```text
catalog material:          72,954.29
supplier package material: 204,672.00
total material:            277,626.29
```

Current implemented Phase 1 baseline:

```text
small material allowance = material cost * 3.5%
                         = 277,626.29 * 0.035
                         = 9,716.92

overhead = direct cost * 8.5%
         = 372,700.12 * 0.085
         = 31,679.51

cost baseline = direct cost + small material allowance + overhead
              = 372,700.12 + 9,716.92 + 31,679.51
              = 414,096.55
```

This is the value emitted in `outputs/example_pricing_results.json`.

## 4. Expected-Output Trace

The expected baseline is located at:

```text
expected_output_example.json
example_subset_summary.cost_baseline_chf = 414489.12
```

The expected output labels the scope as:

```text
"Verified example subset; product target is the full tender."
```

The aggregate uses the same material, labour, and direct-cost totals as the implementation:

```text
material: 277,626.29
labour:    95,073.83
direct:   372,700.12
```

Therefore, the mismatch is not caused by a different set of positions for material/labour/direct cost. The file does not state how `cost_baseline_chf` was derived from those totals.

The bid scenarios in `recommended_bid_range` are consistent with the expected baseline being used as the scenario cost base:

```text
414,489.12 / (1 - 0.025) = 425,117.05 -> rounded to 426,000
414,489.12 / (1 - 0.040) = 431,759.50 -> rounded to 432,000
414,489.12 / (1 - 0.065) = 443,303.87 -> rounded to 444,000
```

This shows the expected baseline is intentional enough to feed downstream scenario outputs, but it does not explain the missing CHF 392.57.

## 5. Rounding Analysis

An independent diagnostic script was added at:

```text
scripts/baseline_reconciliation.py
```

It recalculates from raw CSV/JSON inputs without importing `src/tender_pricing/calculation_engine.py`.

Raw unrounded aggregate totals:

```text
raw material: 277,626.2944
raw labour:    95,073.82669090909090909090909
raw direct:   372,700.12109090909090909090909
```

Rounded raw totals:

```text
material: 277,626.29
labour:    95,073.83
direct:   372,700.12
```

Sum of individually rounded position material and labour:

```text
material: 277,626.29
labour:    95,073.83
direct:   372,700.12
```

Rounding deltas:

```text
rounded raw material - sum rounded material = 0.00
rounded raw labour - sum rounded labour     = 0.00
rounded raw direct - summary direct         = 0.00
```

Using unrounded position values in the current baseline formula still gives:

```text
414,096.55
```

Rounding cannot plausibly explain the CHF 392.57 discrepancy.

Small per-row display differences exist within one cent in at least one direct position total because expected rows store rounded display values, but the aggregate material/labour/direct totals are still identical to the cent. This does not affect the baseline gap.

## 6. Alternative Interpretations

All alternatives below use the verified 22-position subset totals. Differences are against CHF 414,489.12.

| Interpretation | Formula | Result | Difference | Support | Status |
|---|---:|---:|---:|---|---|
| A. Current Phase 1 | direct + 3.5% material + 8.5% direct | 414,096.55 | -392.57 | `small_material_pct`, `overhead_pct`; bases inferred | Partly documented |
| B. README minimal | direct + 8.5% direct | 404,379.63 | -10,109.49 | README says cost baseline = project direct cost + overhead | Explicit but omits allowance params |
| C. Overhead after small material | (direct + 3.5% material) * 1.085 | 414,922.49 | +433.37 | Possible if small material is part of overhead base | Inferred |
| D. Add transport/equipment | A + 2.5% direct | 423,414.05 | +8,924.93 | `transport_equipment_pct`; guide mentions transport/equipment | Explicit component, base inferred |
| E. Add supplier contingency | A + 3.0% supplier material | 420,236.71 | +5,747.59 | `supplier_package_contingency_pct` | Explicit component, base inferred |
| F. Direct + transport + overhead | direct + 2.5% direct + 8.5% direct | 413,697.13 | -791.99 | README mentions transport/equipment and overhead | Explicit components, base inferred |
| G. Add fixed project costs | direct + engineering + commissioning + hygiene + documentation + overhead | 520,079.63 | +105,590.51 | guide lists fixed project costs | Explicit components, scope questionable |

No documented interpretation produces CHF 414,489.12. Producing the exact reference number would require an arbitrary extra CHF 392.57, or an undocumented base/rate convention. That would violate the project guardrail against unexplained adjustments.

## 7. Root-Cause Assessment

Assessment by category:

```text
implementation defect:       not established
scope mismatch:              unlikely for material/labour/direct; same 22-position scope is used
rounding difference:          ruled out by independent raw calculation
missed full project cost:     unlikely; documented components overshoot materially
undocumented convention:      possible
source inconsistency:         possible
unresolved:                   yes
```

The strongest evidence is:

1. `expected_output_example.json` and the implementation agree on material, labour, and direct cost.
2. The expected file provides no intermediate cost-baseline components.
3. Independently recalculating from raw CSV/JSON reproduces the implementation's CHF 414,096.55 baseline under the current documented Phase 1 formula.
4. Rounding deltas are zero at the aggregate level.
5. Every named project-level component in `project_parameters.json` is too large to explain a CHF 392.57 gap if added directly.

## 8. Recommended Decision

Do not change the pricing formula to force CHF 414,489.12.

Recommended current behavior:

1. Keep position-level calculations unchanged.
2. Keep the explicit project-cost breakdown in outputs.
3. Keep tests that document the source gap.
4. Treat `expected_output_example.json`'s `cost_baseline_chf` as unresolved pending clarification.
5. Before Phase 2 project-level pricing, choose one of these policies:

```text
Policy 1: Use the documented current formula:
  cost baseline = direct + small material on material + overhead on direct

Policy 2: Use README minimal formula:
  cost baseline = project direct cost + overhead
  but first define which allowances and project costs are inside project direct cost.

Policy 3: Treat expected_output_example.json as authoritative:
  add a named, documented project-level adjustment only after the business meaning of CHF 392.57 is provided.
```

I recommend Policy 1 until the missing convention is clarified, because it is explicit, reproducible, and avoids fabricating a cost component.

## 9. Evidence and Limitations

Evidence available:

```text
the 22 source example rows
the matched product IDs and install codes
catalog net costs and supplier package flags
productivity base hours/rates/factor keys
project factors, allowances, overhead, margin, and fixed costs
expected final position rows and aggregate summary
```

Information not provided:

```text
the formula used to derive expected_output_example.json/example_subset_summary.cost_baseline_chf
the base for small_material_pct
the base for transport_equipment_pct
the base for supplier_package_contingency_pct
whether fixed project costs apply to the 22-position subset or only to full-tender pricing
whether overhead applies before or after allowances/project costs
whether expected_output_example.json includes a hidden adjustment, minimum allowance, risk item, or manual correction
```

Precise missing information needed to resolve the discrepancy:

```text
For the 22-position reference subset, define the intended cost_baseline_chf formula and the base for each included percentage:
- small_material_pct
- transport_equipment_pct
- supplier_package_contingency_pct
- overhead_pct

Also state whether engineering, commissioning, hygiene inspection, and documentation are included in the 22-position subset baseline or only in full-project pricing.
```

