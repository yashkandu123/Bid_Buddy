import { AlertCircle, Download, FileCheck2, RefreshCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { finalOfferPdfUrl, generateFinalOffer, getFinalOfferReport } from "../app/apiClient";
import type { FinalOfferReport } from "../app/types";
import { PageHeader } from "../components/PageHeader";
import { UnavailablePanel } from "../components/UnavailablePanel";

export function FinalOfferPage() {
  const params = useParams();
  const jobId = params.jobId ?? window.localStorage.getItem("lastTenderJobId");
  const [report, setReport] = useState<FinalOfferReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setLoading] = useState(false);
  const [isGenerating, setGenerating] = useState(false);

  useEffect(() => {
    if (!jobId) return;
    void loadExistingReport(jobId);
  }, [jobId]);

  async function loadExistingReport(id: string) {
    setLoading(true);
    setError(null);
    try {
      setReport(await getFinalOfferReport(id));
    } catch (loadError) {
      setReport(null);
      const message = loadError instanceof Error ? loadError.message : "Could not load final offer status.";
      if (!message.toLowerCase().includes("not been generated")) setError(message);
    } finally {
      setLoading(false);
    }
  }

  async function handleGenerate() {
    if (!jobId) return;
    setGenerating(true);
    setError(null);
    try {
      setReport(await generateFinalOffer(jobId));
    } catch (generateError) {
      setError(generateError instanceof Error ? generateError.message : "Could not generate final offer PDF.");
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div className="page-stack">
      <PageHeader eyebrow="05 · Validate" title="Final offer">
        Generate a priced PDF from the uploaded tender using only accepted calculated rows from the current review
        state. Review-only and provisional supplier rows stay visible in the validation summary.
      </PageHeader>

      {!jobId ? (
        <UnavailablePanel title="No processed job selected">
          Upload and process a tender before generating the final offer PDF.
          <div className="button-row">
            <Link className="secondary-button" to="/">
              Upload PDF
            </Link>
          </div>
        </UnavailablePanel>
      ) : null}

      {jobId ? (
        <section className="content-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">PDF export</p>
              <h3>{report ? "Generated final offer" : "Generate priced tender PDF"}</h3>
            </div>
            <div className="button-row">
              <button className="secondary-button" type="button" onClick={() => loadExistingReport(jobId)} disabled={isLoading}>
                <RefreshCcw size={18} /> Refresh
              </button>
              <button className="primary-button" type="button" onClick={handleGenerate} disabled={isGenerating}>
                <FileCheck2 size={18} /> {isGenerating ? "Generating..." : "Generate PDF"}
              </button>
            </div>
          </div>
          <p>
            The export overlays unit and position totals only where the backend validates a unique price-cell mapping.
            Ambiguous rows are left blank.
          </p>
          {error ? (
            <p className="inline-message error">
              <AlertCircle size={18} /> {error}
            </p>
          ) : null}
          {!report && !error ? <p className="inline-message">No final-offer PDF has been generated for this job yet.</p> : null}
        </section>
      ) : null}

      {report ? (
        <>
          <section className="totals-grid" aria-label="Final offer export summary">
            <SummaryCard label="Accepted rows" value={report.summary.accepted_position_count} />
            <SummaryCard label="Mapped prices" value={report.summary.mapped_position_count} />
            <SummaryCard label="Skipped mappings" value={report.summary.skipped_mapping_count} />
            <SummaryCard label="Supplier quotes" value={report.summary.supplier_quotes_outstanding} />
          </section>

          <section className="content-panel">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Output</p>
                <h3>{report.page_count} pages</h3>
              </div>
              <a className="primary-button" href={finalOfferPdfUrl(report.job_id)} target="_blank" rel="noreferrer">
                <Download size={18} /> Open priced PDF
              </a>
            </div>
            <dl className="definition-grid">
              <dt>Source PDF</dt>
              <dd>{report.source_pdf}</dd>
              <dt>Output file</dt>
              <dd>{report.output_pdf}</dd>
              <dt>Validation report</dt>
              <dd>{report.validation_report}</dd>
              <dt>Policy</dt>
              <dd>{report.pricing_policy}</dd>
            </dl>
          </section>

          {report.warnings.length ? (
            <section className="content-panel warning-panel">
              <strong>Export warnings</strong>
              {report.warnings.map((warning) => (
                <span key={warning.code}>{warning.message}</span>
              ))}
            </section>
          ) : null}

          <section className="content-panel">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Validation</p>
                <h3>Mapped positions</h3>
              </div>
              <p>{report.mapped_positions.length} rows placed in price cells.</p>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Page</th>
                    <th>Unit price</th>
                    <th>Total</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {report.mapped_positions.slice(0, 25).map((position) => (
                    <tr key={position.lv_id}>
                      <td>{position.lv_id}</td>
                      <td>{position.source_page}</td>
                      <td>{formatPrice(position.unit_price_chf)}</td>
                      <td>{formatPrice(position.position_total_chf)}</td>
                      <td>{position.placement_status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {report.skipped_positions.length ? (
              <ul className="flag-list">
                {report.skipped_positions.map((position) => (
                  <li key={position.lv_id}>
                    <strong>{position.lv_id}</strong>
                    <span>{position.placement_status}: {position.placement_reason}</span>
                  </li>
                ))}
              </ul>
            ) : null}
          </section>
        </>
      ) : null}
    </div>
  );
}

function SummaryCard({ label, value }: { label: string; value: number }) {
  return (
    <article className="total-card">
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function formatPrice(value: number | null) {
  if (value === null) return "-";
  return value.toLocaleString("de-CH", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
