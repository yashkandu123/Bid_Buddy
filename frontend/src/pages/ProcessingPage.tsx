import { AlertCircle, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getJobStatus } from "../app/apiClient";
import type { JobStatusResponse } from "../app/types";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";

export function ProcessingPage() {
  const params = useParams();
  const navigate = useNavigate();
  const jobId = params.jobId ?? window.localStorage.getItem("lastTenderJobId");
  const [status, setStatus] = useState<JobStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    let timer: number | undefined;

    async function poll() {
      try {
        const nextStatus = await getJobStatus(jobId!);
        if (cancelled) return;
        setStatus(nextStatus);
        setError(null);
        if (nextStatus.status === "completed") {
          navigate(`/review/${nextStatus.job_id}`);
        } else if (nextStatus.status === "queued" || nextStatus.status === "processing") {
          timer = window.setTimeout(poll, 1800);
        }
      } catch (pollError) {
        if (!cancelled) {
          setError(pollError instanceof Error ? pollError.message : "Could not read job status.");
        }
      }
    }

    void poll();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [jobId, navigate]);

  return (
    <div className="page-stack">
      <PageHeader eyebrow="02 · Extract" title="Processing">
        Job state comes from the existing FastAPI job endpoint. Current backend jobs usually complete inside the upload
        request because processing is synchronous.
      </PageHeader>

      {!jobId ? (
        <section className="empty-state">
          <AlertCircle size={26} />
          <h3>No upload job selected</h3>
          <p>Upload a tender PDF before viewing processing status.</p>
          <Link className="secondary-button" to="/">
            Go to upload
          </Link>
        </section>
      ) : (
        <section className="content-panel">
          <div className="job-status-line">
            <Loader2 className={status?.status === "processing" ? "spin" : ""} size={24} />
            <div>
              <p className="eyebrow">Job ID</p>
              <h3>{jobId}</h3>
            </div>
            {status ? <StatusBadge status={status.status} /> : null}
          </div>
          {status ? (
            <dl className="definition-grid">
              <dt>Created</dt>
              <dd>{status.created_at}</dd>
              <dt>Started</dt>
              <dd>{status.started_at ?? "Not started"}</dd>
              <dt>Completed</dt>
              <dd>{status.completed_at ?? "Not completed"}</dd>
              <dt>Counts</dt>
              <dd>{Object.entries(status.position_counts_by_status).map(([key, value]) => `${key}: ${value}`).join(", ") || "None yet"}</dd>
            </dl>
          ) : null}
          {status?.status === "failed" ? <p className="inline-message error">{status.error?.message}</p> : null}
          {error ? <p className="inline-message error">{error}</p> : null}
        </section>
      )}
    </div>
  );
}
