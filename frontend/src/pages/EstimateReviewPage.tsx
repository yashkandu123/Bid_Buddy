import { AlertCircle, RefreshCcw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getCatalog, getJobResults, getPhase2FullTenderOutput } from "../app/apiClient";
import { PRODUCT_CATEGORIES, positionCategory } from "../app/category";
import type { CatalogItem, TenderPosition, TenderResult } from "../app/types";
import { PageHeader } from "../components/PageHeader";
import { PositionDrawer } from "../components/PositionDrawer";
import { PositionTable } from "../components/PositionTable";
import { ProductTypeTabs } from "../components/ProductTypeTabs";
import { TotalsPanel } from "../components/TotalsPanel";

export function EstimateReviewPage() {
  const params = useParams();
  const jobId = params.jobId ?? window.localStorage.getItem("lastTenderJobId");
  const [result, setResult] = useState<TenderResult | null>(null);
  const [selectedCategory, setSelectedCategory] = useState("all");
  const [selectedPosition, setSelectedPosition] = useState<TenderPosition | null>(null);
  const [catalog, setCatalog] = useState<CatalogItem[]>([]);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [installFilter, setInstallFilter] = useState("all");
  const [systemFilter, setSystemFilter] = useState("all");
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setLoading] = useState(false);

  useEffect(() => {
    if (!jobId || params.jobId === undefined) return;
    void loadJobResult(jobId);
  }, [jobId, params.jobId]);

  useEffect(() => {
    getCatalog()
      .then((payload) => setCatalog(payload.items))
      .catch(() => setCatalog([]));
  }, []);

  async function loadJobResult(id: string) {
    setLoading(true);
    setError(null);
    try {
      setResult(await getJobResults(id));
      setPage(1);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Could not load job results.");
    } finally {
      setLoading(false);
    }
  }

  async function loadReferenceOutput() {
    setLoading(true);
    setError(null);
    try {
      setResult(await getPhase2FullTenderOutput());
      setPage(1);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Could not load Phase 2 output.");
    } finally {
      setLoading(false);
    }
  }

  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = { all: result?.positions.length ?? 0 };
    for (const category of PRODUCT_CATEGORIES) counts[category.key] ??= 0;
    for (const position of result?.positions ?? []) counts[positionCategory(position)] += 1;
    return counts;
  }, [result]);

  const filteredPositions = useMemo(() => {
    if (!result) return [];
    const normalizedQuery = query.trim().toLowerCase();
    return result.positions.filter((position) => {
      if (selectedCategory !== "all" && positionCategory(position) !== selectedCategory) return false;
      if (statusFilter !== "all" && position.status !== statusFilter) return false;
      if (installFilter !== "all" && position.catalogue_traceability?.install_code !== installFilter) return false;
      if (systemFilter !== "all" && (position.system ?? "Unassigned") !== systemFilter) return false;
      if (!normalizedQuery) return true;
      return [
        position.lv_id,
        position.original_description,
        position.source_line,
        position.matched_product_id ?? "",
        String(position.source_page)
      ]
        .join(" ")
        .toLowerCase()
        .includes(normalizedQuery);
    });
  }, [result, selectedCategory, statusFilter, installFilter, systemFilter, query]);

  const pageSize = 25;
  const pageCount = Math.max(1, Math.ceil(filteredPositions.length / pageSize));
  const pagePositions = filteredPositions.slice((page - 1) * pageSize, page * pageSize);
  const statuses = useMemo(() => sortedUnique(result?.positions.map((position) => position.status) ?? []), [result]);
  const installCodes = useMemo(
    () => sortedUnique(result?.positions.map((position) => position.catalogue_traceability?.install_code).filter(Boolean) as string[]),
    [result]
  );
  const systems = useMemo(
    () => sortedUnique(result?.positions.map((position) => position.system ?? "Unassigned") ?? []),
    [result]
  );

  return (
    <div className="page-stack">
      <PageHeader eyebrow="03 · Structure and match" title="Estimate & human review">
        Read-only Phase 8B view of backend results. Product-type tabs organize positions without changing pricing status
        or accepting uncertain matches.
      </PageHeader>

      {!result ? (
        <section className="empty-state">
          <AlertCircle size={26} />
          <h3>No estimate loaded</h3>
          <p>Upload a tender and wait for processing, or load the fixed Phase 2 output from the backend.</p>
          <div className="button-row">
            {jobId ? (
              <button className="secondary-button" type="button" onClick={() => loadJobResult(jobId)} disabled={isLoading}>
                Load last upload job
              </button>
            ) : (
              <Link className="secondary-button" to="/">
                Upload PDF
              </Link>
            )}
            <button className="primary-button" type="button" onClick={loadReferenceOutput} disabled={isLoading}>
              <RefreshCcw size={18} /> Load Phase 2 output
            </button>
          </div>
          {error ? <p className="inline-message error">{error}</p> : null}
        </section>
      ) : (
        <>
          <TotalsPanel result={result} />
          <section className="content-panel warning-panel">
            <strong>Baseline warning</strong>
            <span>{result.baseline_reconciliation_warning.message}</span>
          </section>
          <ProductTypeTabs
            active={selectedCategory}
            counts={categoryCounts}
            onChange={(category) => {
              setSelectedCategory(category);
              setPage(1);
            }}
          />
          <section className="content-panel">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Rows</p>
                <h3>{filteredPositions.length} positions</h3>
              </div>
              <p>
                Calculated rows, supplier-package estimates, review rows, insufficient rows, and non-priceable records
                remain distinct.
              </p>
            </div>
            <div className="filter-grid">
              <label>
                Search
                <input value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} />
              </label>
              <label>
                Status
                <select value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value); setPage(1); }}>
                  <option value="all">All statuses</option>
                  {statuses.map((status) => <option key={status} value={status}>{status}</option>)}
                </select>
              </label>
              <label>
                Install code
                <select value={installFilter} onChange={(event) => { setInstallFilter(event.target.value); setPage(1); }}>
                  <option value="all">All install codes</option>
                  {installCodes.map((code) => <option key={code} value={code}>{code}</option>)}
                </select>
              </label>
              <label>
                System
                <select value={systemFilter} onChange={(event) => { setSystemFilter(event.target.value); setPage(1); }}>
                  <option value="all">All systems</option>
                  {systems.map((system) => <option key={system} value={system}>{system}</option>)}
                </select>
              </label>
            </div>
            <PositionTable positions={pagePositions} onSelect={setSelectedPosition} />
            <div className="pagination">
              <button className="secondary-button" type="button" disabled={page === 1} onClick={() => setPage(page - 1)}>
                Previous
              </button>
              <span>
                Page {page} of {pageCount}
              </span>
              <button
                className="secondary-button"
                type="button"
                disabled={page === pageCount}
                onClick={() => setPage(page + 1)}
              >
                Next
              </button>
            </div>
          </section>
          <PositionDrawer
            position={selectedPosition}
            catalog={catalog}
            jobId={result.job_id}
            onClose={() => setSelectedPosition(null)}
            onSaved={(updated) => {
              setResult(updated);
              setSelectedPosition(
                updated.positions.find((position) => position.lv_id === selectedPosition?.lv_id) ?? null
              );
            }}
          />
        </>
      )}
    </div>
  );
}

function sortedUnique(values: string[]): string[] {
  return Array.from(new Set(values)).sort((left, right) => left.localeCompare(right));
}
