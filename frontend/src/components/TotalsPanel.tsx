import { chf } from "../app/format";
import type { TenderResult } from "../app/types";

export function TotalsPanel({ result }: { result: TenderResult }) {
  const totals = result.project_totals;
  return (
    <section className="totals-grid" aria-label="Project totals">
      <TotalCard
        label="Confirmed calculated"
        value={totals.confirmed.summary.direct_cost_chf}
        baseline={totals.confirmed.summary.cost_baseline_chf}
        count={totals.confirmed.included_position_count}
      />
      <TotalCard
        label="Provisional supplier packages"
        value={totals.provisional.summary.direct_cost_chf}
        baseline={totals.provisional.summary.cost_baseline_chf}
        count={totals.provisional.included_position_count}
      />
      <TotalCard
        label="Combined estimate"
        value={totals.combined_estimate.summary.direct_cost_chf}
        baseline={totals.combined_estimate.summary.cost_baseline_chf}
        count={totals.combined_estimate.included_position_count}
      />
    </section>
  );
}

function TotalCard({
  label,
  value,
  baseline,
  count
}: {
  label: string;
  value: number;
  baseline: number;
  count: number;
}) {
  return (
    <article className="total-card">
      <span>{label}</span>
      <strong>{chf(value)}</strong>
      <small>
        Baseline {chf(baseline)} · {count} rows
      </small>
    </article>
  );
}
