import { AlertCircle, CheckCircle2, UploadCloud } from "lucide-react";
import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { uploadTenderPdf } from "../app/apiClient";
import { PageHeader } from "../components/PageHeader";

export function WelcomeUploadPage() {
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isUploading, setUploading] = useState(false);

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

    setUploading(true);
    setError(null);
    try {
      const job = await uploadTenderPdf(file!);
      window.localStorage.setItem("lastTenderJobId", job.job_id);
      navigate(`/processing/${job.job_id}`);
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="page-stack">
      <PageHeader eyebrow="01 · Ingest" title="Welcome & tender upload">
        Upload a tender PDF to start the existing backend extraction job. The app waits for the FastAPI response
        before showing processing or estimate results.
      </PageHeader>

      <section className="hero-panel">
        <div>
          <p className="eyebrow">Estimator workflow</p>
          <h3>Upload a tender. Get a traceable first estimate.</h3>
          <p>
            The current backend extracts German LV text, matches supported catalogue items, separates confirmed and
            provisional costs, and keeps uncertain rows reviewable.
          </p>
        </div>
        <form className="upload-panel" onSubmit={handleSubmit}>
          <label className="drop-zone">
            <UploadCloud size={34} aria-hidden="true" />
            <span>{file ? file.name : "Choose tender PDF"}</span>
            <input
              type="file"
              accept="application/pdf,.pdf"
              onChange={(event) => {
                const nextFile = event.target.files?.[0] ?? null;
                setFile(nextFile);
                setError(validateFile(nextFile));
              }}
            />
          </label>
          {file && !error ? (
            <p className="inline-message success">
              <CheckCircle2 size={18} /> Ready to upload. Processing starts only after submit.
            </p>
          ) : null}
          {error ? (
            <p className="inline-message error">
              <AlertCircle size={18} /> {error}
            </p>
          ) : null}
          <button className="primary-button" type="submit" disabled={isUploading}>
            {isUploading ? "Uploading..." : "Start processing"}
          </button>
        </form>
      </section>
    </div>
  );
}
