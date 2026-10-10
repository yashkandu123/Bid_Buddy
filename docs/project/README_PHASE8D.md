# Phase 8D Bid Optimization

Phase 8D adds deterministic bid scenarios for completed upload jobs. It does not change Phase 1 pricing formulas, Phase 2 matching/classification, golden outputs, LLM behavior, or priced-PDF generation.

## Formula Audit

Supported cost basis:

- The scenario service uses the saved job result after estimator review state has been applied.
- The active scenario base is `project_totals.combined_estimate.summary.cost_baseline_chf`.
- Confirmed catalogue costs and provisional supplier-package estimates are returned separately.
- Rows with `review_required` or `insufficient_information` remain excluded from the scenario cost basis.
- `non_priceable` rows are counted separately and are not included in bid costs.

Implemented cost baseline:

```text
cost_baseline = direct_cost + small_material_allowance_on_material + overhead_on_direct_cost
```

This is the existing Phase 1 implementation. Engineering, commissioning, hygiene, documentation, transport/equipment, and supplier-package contingency are still reported in the project breakdown but are not included in the implemented baseline. The unresolved CHF 392.57 baseline discrepancy remains documented separately.

Scenario bid price:

```text
raw_bid_price = cost_baseline / (1 - scenario_margin_pct / 100)
bid_price = round up raw_bid_price to commercial.round_to_chf
```

With the current `project_parameters.json`, the three configured margins are:

```text
Aggressive:   2.5%
Target:       4.0%
Conservative: 6.5%
```

Probability:

```text
probability =
  reference_win_probability
  + (commercial.target_margin_pct - scenario_margin_pct)
    * price_sensitivity_probability_points_per_1pct_price
  + strategic_appetite_adjustment
  + competition_adjustment

then clamped to minimum_probability and maximum_probability
```

This is a heuristic based only on configured parameters. It is not calibrated with historical bids, competitor prices, client budgets, or market data.

Expected contribution:

```text
expected_contribution = (rounded_bid_price - cost_baseline) * estimated_win_probability
```

This is an expected contribution over the selected cost basis, not a commercially confirmed profit forecast.

## Backend API

```text
GET   /jobs/{job_id}/bid-scenarios
PATCH /jobs/{job_id}/bid-selection
```

`GET /jobs/{job_id}/bid-scenarios` returns:

- scenario name and configured margin;
- cost baseline, raw bid, rounded bid, win probability estimate, and expected contribution;
- cost-basis warnings for unresolved rows and provisional supplier-package estimates;
- formula audit text;
- job-scoped selected scenario, if one has been saved.

`PATCH /jobs/{job_id}/bid-selection` accepts only:

```json
{
  "scenario_name": "Target"
}
```

The API rejects unknown scenario names and extra fields. The browser cannot submit authoritative totals or prices.

## Frontend Behavior

The Bid Optimization page now loads scenarios for the current uploaded job, displays three comparable cards, and saves the selected scenario through the backend. Selection is job-scoped and survives page refresh while the backend job directory and in-memory job registry remain available.

Known limitation: selection is still local job storage, not durable multi-user persistence.

## Commands

Backend:

```powershell
& 'C:\Users\saiya\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m uvicorn src.tender_pricing.api:app --host 127.0.0.1 --port 8000
```

Frontend:

```powershell
cd frontend
npm install
npm run dev
```

Tests:

```powershell
& 'C:\Users\saiya\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests
cd frontend
npm test
npm run build
```
