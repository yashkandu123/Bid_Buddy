# Phase 1 Pricing Baseline

This phase prices only the verified 22-position example subset. It does not parse the full PDF, expose an API, call n8n, or build a UI.

## Run tests

```powershell
python -m unittest discover -s tests
```

## Run the CLI

```powershell
python -m src.tender_pricing.cli --project-root . --output-dir outputs
```

The CLI writes `outputs/example_pricing_results.json`.
It also writes `outputs/example_priced_positions.csv`.

## Project-Level Cost Baseline

All 22 position rows and the aggregate material, labour, and direct-cost totals are calculated from `catalog.csv`, `productivity.csv`, `example_lv_positions.csv`, and `project_parameters.json`.

The implemented Phase 1 baseline is:

```text
direct cost + small-material allowance on material + overhead on direct cost
```

Arithmetic for the verified subset:

```text
material cost:                  277,626.29
labour cost:                     95,073.83
direct cost:                    372,700.12
small material, 3.5% material:    9,716.92
overhead, 8.5% direct:           31,679.51
calculated cost baseline:       414,096.55
expected cost baseline:         414,489.12
unexplained gap:                    392.57
```

The source files do not uniquely explain the CHF 392.57 gap. Other defined components are much larger and would overshoot the reference baseline if included:

```text
transport/equipment, 2.5% direct:        9,317.50
supplier-package contingency, 3.0%:      6,140.16
engineering:                            60,900.00
commissioning:                          24,800.00
hygiene inspection:                      18,000.00
documentation:                           12,000.00
```

So the discrepancy appears to be an inconsistency in the reference aggregate or an omitted formula convention, not a missing full project-cost component. The code keeps this visible and does not apply an unexplained adjustment.
