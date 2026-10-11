import { AlertCircle, CheckCircle2, Loader2, UploadCloud } from "lucide-react";
import { FormEvent, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getJobStatus, uploadTenderPdf } from "../app/apiClient";
import type { JobStatusResponse } from "../app/types";
import { WorkflowFooter } from "../components/WorkflowFooter";
import { PageHeader } from "../components/PageHeader";

export function WelcomeUploadPage() {
  const { jobId } = useParams();
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [requestStage, setRequestStage] = useState<"idle" | "restoring" | "uploading" | "processing">("idle");
  const [job, setJob] = useState<JobStatusResponse | null>(null);
  const [retry, setRetry] = useState(0);
  const requestVersion = useRef(0);

  useEffect(() => {
    if (file || !jobId) return;
    let cancelled = false;
    const version = ++requestVersion.current;
    setJob(null);
    setError(null);
    setRequestStage("restoring");
    getJobStatus(jobId)
      .then(status => { if (!cancelled && requestVersion.current === version) setJob(status); })
      .catch(failure => {
        if (!cancelled && requestVersion.current === version) setError(failure instanceof Error ? failure.message : "Could not read processing status.");
      })
      .finally(() => { if (!cancelled && requestVersion.current === version) setRequestStage("idle"); });
    return () => { cancelled = true; };
  }, [file, jobId]);

  useEffect(() => {
    if (!job || !["queued", "processing"].includes(job.status)) return;
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const updated = await getJobStatus(job.job_id);
        if (!cancelled) { setJob(updated); setError(null); }
      } catch (failure) {
        if (!cancelled) setError(failure instanceof Error ? failure.message : "Could not read processing status.");
      }
    }, 1800);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [job, retry]);

  function validateFile(candidate: File | null) {
    if (!candidate) return "Select a PDF tender file.";
    if (candidate.type && candidate.type !== "application/pdf") return "Only PDF files can be uploaded.";
    if (!candidate.name.toLowerCase().endsWith(".pdf")) return "The selected file must use a .pdf extension.";
    return null;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const validationError = validateFile(file);
    if (validationError) {
      setError(validationError);
      return;
    }

    setJob(null);
    requestVersion.current += 1;
    window.localStorage.removeItem("lastTenderJobId");
    setRequestStage("uploading");
    setError(null);
    try {
      const createdJob = await uploadTenderPdf(file!);
      window.localStorage.setItem("lastTenderJobId", createdJob.job_id);
      setRequestStage("processing");
      setJob(await getJobStatus(createdJob.job_id));
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : "Upload failed.");
    } finally {
      setRequestStage("idle");
    }
  }

  const lifecycle = requestStage === "uploading"
    ? "uploading"
    : requestStage === "processing" || requestStage === "restoring"
      ? "processing"
      : job?.status === "failed" || error
        ? "failed"
        : job?.status === "queued" || job?.status === "processing"
          ? "processing"
          : job?.status === "completed"
            ? "completed"
            : file
              ? "ready"
              : "empty";
  const isBusy = lifecycle === "uploading" || lifecycle === "processing";
  const isSubmissionBusy = requestStage === "uploading" || requestStage === "processing" || job?.status === "queued" || job?.status === "processing";
  const failureMessage = job?.status === "failed"
    ? job.error?.message ?? "Processing failed. Retry the upload."
    : error;

  return (
    <div className="page-stack home-page">
      <PageHeader eyebrow="01 · Ingest" title="Welcome - Let's price your tender">
        Upload your ventilation tender PDF to get started. We’ll extract the tender positions,
        match them with catalogue products, and prepare a priced offer for your review.
      </PageHeader>

      <section className="hero-panel">
        <div>
          <p className="eyebrow">Estimator workflow</p>
          <h3>Upload a tender. Get a traceable first estimate.</h3>
          <p>
              Upload your ventilation tender PDF to extract German-language tender positions,
              match supported catalogue products, and prepare an initial cost estimate.
              Confirmed prices and provisional costs are clearly distinguished,
              and uncertain positions remain available for review.
          </p>
        </div>
        <form className="upload-panel" onSubmit={handleSubmit}>
          <label className="drop-zone">
            <UploadCloud size={34} aria-hidden="true" />
            <span>{file ? file.name : "Choose tender PDF"}</span>
            <input
              type="file"
              accept="application/pdf,.pdf"
              disabled={isSubmissionBusy}
              onChange={(event) => {
                const nextFile = event.target.files?.[0] ?? null;
                requestVersion.current += 1;
                setFile(nextFile);
                setJob(null);
                setRequestStage("idle");
                setError(validateFile(nextFile));
              }}
            />
          </label>
          {lifecycle === "completed" ? (
            <button className="primary-button" type="button" onClick={() => navigate(`/review/${job!.job_id}`)}>
              Proceed to Estimate & Review
            </button>
          ) : (
            <button className="primary-button" type="submit" disabled={isBusy || lifecycle === "empty" || (lifecycle === "failed" && !file)}>
              {isBusy ? <Loader2 className="spin" size={18} aria-hidden="true" /> : null}
              {isBusy ? "Processing..." : lifecycle === "failed" ? (file ? "Retry processing" : "Choose tender PDF") : lifecycle === "empty" ? "Choose tender PDF" : "Start processing"}
            </button>
          )}
        </form>
      </section>
      {lifecycle === "empty" ? <p className="inline-message" role="status">Upload a tender PDF to get started.</p> : null}
      {lifecycle === "ready" ? <p className="inline-message" role="status">Ready to process.</p> : null}
      {lifecycle === "uploading" ? <p className="inline-message" role="status"><Loader2 className="spin" size={18} /> Uploading tender...</p> : null}
      {lifecycle === "processing" ? <p className="inline-message" role="status"><Loader2 className="spin" size={18} /> Processing tender...</p> : null}
      {lifecycle === "completed" ? <p className="inline-message success" role="status"><CheckCircle2 size={18} /> Processing complete. Your estimate is ready.</p> : null}
      {lifecycle === "failed" ? <p className="inline-message error" role="alert"><AlertCircle size={18} /> {failureMessage}</p> : null}
      {error && job ? <button className="secondary-button" onClick={() => { setError(null); setRetry(retry + 1); }}>Retry status check</button> : null}
      <WorkflowFooter next={{ to: `/review/${job?.job_id ?? ""}`, label: "Estimate & Review" }} disabledReason={job?.status === "completed" ? undefined : "Upload and complete processing to continue."} />
    </div>
  );
}
