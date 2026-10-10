import { AlertCircle, CheckCircle2, RefreshCcw, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getBidScenarios, updateBidSelection } from "../app/apiClient";
import { chf, pct } from "../app/format";
import type { BidScenariosResponse } from "../app/types";
import { PageHeader } from "../components/PageHeader";
import { UnavailablePanel } from "../components/UnavailablePanel";

export function BidOptimizationPage() {
  const params = useParams();
  const jobId = params.jobId ?? window.localStorage.getItem("lastTenderJobId");
  const [payload, setPayload] = useState<BidScenariosResponse | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [isLoading, setLoading] = useState(false);
  const [isSaving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) return;
    void loadScenarios(jobId);
  }, [jobId]);

  async function loadScenarios(id: string) {
    setLoading(true);
    setError(null);
    setSaveMessage(null);
    try {
      const response = await getBidScenarios(id);
      setPayload(response);
      setSelected(response.selection.scenario_name);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Could not load bid scenarios.");
    } finally {
      setLoading(false);
    }
  }

  async function saveSelection(name: string) {
    if (!jobId) return;
    setSaving(true);
    setError(null);
    setSaveMessage(null);
    try {
      const response = await updateBidSelection(jobId, name);
      setPayload(response);
      setSelected(response.selection.scenario_name);
      setSaveMessage(`Saved ${name} for this job.`);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Could not save bid selection.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="page-stack">
      <PageHeader eyebrow="04 · Decide" title="Bid optimization">
        Deterministic scenario prices come from the backend. Win probability is a configured heuristic, not a calibrated
        prediction from historical bid data.
      </PageHeader>

      {!jobId ? (
        <UnavailablePanel title="No processed job selected">
          Upload and process a tender before comparing bid scenarios.
          <div className="button-row">
            <Link className="secondary-button" to="/">
              Upload PDF
            </Link>
          </div>
        </UnavailablePanel>
      ) : null}

      {jobId && !payload ? (
        <section className="empty-state">
          <AlertCircle size={26} />
          <h3>{isLoading ? "Loading scenarios" : "No scenario data loaded"}</h3>
          <p>Scenario calculation requires a completed upload job.</p>
          <button className="primary-button" type="button" onClick={() => loadScenarios(jobId)} disabled={isLoading}>
            <RefreshCcw size={18} /> Load scenarios
          </button>
          {error ? <p className="inline-message error">{error}</p> : null}
        </section>
      ) : null}

      {payload ? (
        <>
          <section className="content-panel">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Cost basis</p>
                <h3>{chf(payload.cost_basis.cost_baseline_chf)}</h3>
              </div>
              <button className="secondary-button" type="button" onClick={() => loadScenarios(payload.job_id)}>
                <RefreshCcw size={18} /> Refresh
              </button>
            </div>
            <dl className="definition-grid">
              <dt>Confirmed baseline</dt>
              <dd>{chf(payload.cost_basis.confirmed_cost_baseline_chf)}</dd>
              <dt>Provisional baseline</dt>
              <dd>{chf(payload.cost_basis.provisional_cost_baseline_chf)}</dd>
              <dt>Included rows</dt>
              <dd>
                {payload.cost_basis.included_position_count} ({payload.cost_basis.included_statuses.join(", ")})
              </dd>
              <dt>Excluded rows</dt>
              <dd>{payload.cost_basis.excluded_position_count}</dd>
              <dt>Supplier quotes</dt>
              <dd>{payload.cost_basis.supplier_quotes_outstanding} outstanding</dd>
            </dl>
          </section>

          {payload.warnings.length ? (
            <section className="content-panel warning-panel">
              <strong>Scenario warnings</strong>
              {payload.warnings.map((warning) => (
                <span key={warning.code}>{warning.message}</span>
              ))}
            </section>
          ) : null}

          <section className="scenario-grid" aria-label="Bid scenarios">
            {payload.scenarios.map((scenario) => (
              <article
                className={`scenario-card${selected === scenario.scenario ? " selected" : ""}`}
                key={scenario.scenario}
              >
                <div className="scenario-heading">
                  <div>
                    <p className="eyebrow">{formatMargin(scenario.margin_pct)} margin</p>
                    <h3>{scenario.scenario}</h3>
                  </div>
                  {selected === scenario.scenario ? <CheckCircle2 size={22} /> : null}
                </div>
                <strong>{chf(scenario.bid_price_chf ?? undefined)}</strong>
                <dl className="definition-grid">
                  <dt>Raw bid</dt>
                  <dd>{chf(scenario.raw_bid_price_chf ?? undefined)}</dd>
                  <dt>Win estimate</dt>
                  <dd>{scenario.probability_available ? pct(scenario.estimated_win_probability ?? undefined) : "Unavailable"}</dd>
                  <dt>Expected contribution</dt>
                  <dd>{chf(scenario.expected_contribution_chf ?? undefined)}</dd>
                  <dt>Rounded to</dt>
                  <dd>{chf(scenario.rounding_increment_chf ?? undefined)}</dd>
                </dl>
                {scenario.complete ? (
                  <p className="inline-message success">No unresolved cost-basis warnings for this scenario.</p>
                ) : (
                  <ul className="flag-list">
                    {scenario.completion_reasons.map((reason) => (
                      <li key={reason}>
                        <strong>Review before final offer</strong>
                        <span>{reason}</span>
                      </li>
                    ))}
                  </ul>
                )}
                <button
                  className="primary-button"
                  type="button"
                  disabled={isSaving || selected === scenario.scenario || scenario.bid_price_chf === null}
                  onClick={() => saveSelection(scenario.scenario)}
                >
                  <Save size={18} /> Select scenario
                </button>
              </article>
            ))}
          </section>

          <section className="content-panel">
            <p className="eyebrow">Model assumptions</p>
            <dl className="definition-grid">
              <dt>Bid price</dt>
              <dd>{payload.formula_audit.bid_price_formula}</dd>
              <dt>Cost basis</dt>
              <dd>{payload.formula_audit.cost_basis}</dd>
              <dt>Probability</dt>
              <dd>{payload.formula_audit.probability_model}</dd>
              <dt>Contribution</dt>
              <dd>{payload.formula_audit.expected_contribution_definition}</dd>
            </dl>
            {saveMessage ? <p className="inline-message success">{saveMessage}</p> : null}
            {error ? <p className="inline-message error">{error}</p> : null}
          </section>
        </>
      ) : null}
    </div>
  );
}

function formatMargin(value: number | null): string {
  if (value === null || Number.isNaN(value)) return "Unavailable";
  return `${value.toFixed(1)}%`;
}
