import type {
  ApiErrorPayload,
  BidScenariosResponse,
  CatalogItem,
  FinalOfferReport,
  HealthResponse,
  JobCreateResponse,
  JobStatusResponse,
  PositionReviewPatch,
  TenderResult
} from "./types";

const LOCAL_API_BASE_URL = "http://127.0.0.1:8000";
const CLOUD_API_BASE_URL = "/api";

export function resolveApiBaseUrl(configuredUrl: string | undefined, isDevelopment: boolean): string {
  const configured = configuredUrl?.trim();
  if (configured) return configured.replace(/\/+$/, "");
  return isDevelopment ? LOCAL_API_BASE_URL : CLOUD_API_BASE_URL;
}

export const API_BASE_URL = resolveApiBaseUrl(import.meta.env.VITE_API_BASE_URL, import.meta.env.DEV);

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init);
  } catch (error) {
    throw new Error("Backend is unreachable. Start FastAPI and try again.");
  }

  if (!response.ok) {
    let message = `Request failed with HTTP ${response.status}.`;
    try {
      const payload = (await response.json()) as ApiErrorPayload;
      if (typeof payload.detail === "string") {
        message = payload.detail;
      } else if (payload.detail?.message) {
        message = payload.detail.message;
      }
    } catch {
      // Keep the generic HTTP message.
    }
    throw new Error(message);
  }

  return response.json() as Promise<T>;
}

export function getHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>("/health");
}

export function uploadTenderPdf(file: File): Promise<JobCreateResponse> {
  const formData = new FormData();
  formData.append("file", file);
  return requestJson<JobCreateResponse>("/jobs", {
    method: "POST",
    body: formData
  });
}

export function getJobStatus(jobId: string): Promise<JobStatusResponse> {
  return requestJson<JobStatusResponse>(`/jobs/${encodeURIComponent(jobId)}`);
}

export function getJobResults(jobId: string): Promise<TenderResult> {
  return requestJson<TenderResult>(`/jobs/${encodeURIComponent(jobId)}/results`);
}

export function getPhase2FullTenderOutput(): Promise<TenderResult> {
  return requestJson<TenderResult>("/process/full-tender-output", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dataset_id: "phase2_full" })
  });
}

export function getCatalog(): Promise<{ items: CatalogItem[]; count: number }> {
  return requestJson<{ items: CatalogItem[]; count: number }>("/catalog");
}

export function updatePositionReview(
  jobId: string,
  lvId: string,
  patch: PositionReviewPatch
): Promise<TenderResult> {
  return requestJson<TenderResult>(`/jobs/${encodeURIComponent(jobId)}/positions/${encodeURIComponent(lvId)}/review`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch)
  });
}

export function getBidScenarios(jobId: string): Promise<BidScenariosResponse> {
  return requestJson<BidScenariosResponse>(`/jobs/${encodeURIComponent(jobId)}/bid-scenarios`);
}

export function updateBidSelection(jobId: string, scenarioName: string): Promise<BidScenariosResponse> {
  return requestJson<BidScenariosResponse>(`/jobs/${encodeURIComponent(jobId)}/bid-selection`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenario_name: scenarioName })
  });
}

export function getFinalOfferReport(jobId: string): Promise<FinalOfferReport> {
  return requestJson<FinalOfferReport>(`/jobs/${encodeURIComponent(jobId)}/final-offer`);
}

export function generateFinalOffer(jobId: string): Promise<FinalOfferReport> {
  return requestJson<FinalOfferReport>(`/jobs/${encodeURIComponent(jobId)}/final-offer`, {
    method: "POST"
  });
}

export function finalOfferPdfUrl(jobId: string): string {
  return `${API_BASE_URL}/jobs/${encodeURIComponent(jobId)}/final-offer/pdf`;
}
