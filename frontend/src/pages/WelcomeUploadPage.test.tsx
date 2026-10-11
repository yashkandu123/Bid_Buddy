import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { getJobStatus, uploadTenderPdf } from "../app/apiClient";
import { WelcomeUploadPage } from "./WelcomeUploadPage";

vi.mock("../app/apiClient", () => ({ getJobStatus: vi.fn(), uploadTenderPdf: vi.fn() }));
beforeEach(() => { vi.clearAllMocks(); window.localStorage.clear(); });

function renderUpload(path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/" element={<WelcomeUploadPage />} />
        <Route path="/processing/:jobId" element={<WelcomeUploadPage />} />
      </Routes>
    </MemoryRouter>
  );
}

it("shows a neutral status before any tender is uploaded", () => {
  renderUpload();

  expect(screen.getByRole("status")).toHaveTextContent("Upload a tender PDF to get started.");
  expect(screen.queryByText("Processing complete. Your estimate is ready.")).not.toBeInTheDocument();
});

it("ignores a stale stored job on a fresh upload visit", () => {
  window.localStorage.setItem("lastTenderJobId", "old-job");
  vi.mocked(getJobStatus).mockResolvedValue({ job_id: "old-job", status: "completed", created_at: "today", started_at: "today", completed_at: "today", error: null, position_counts_by_status: {} });

  renderUpload();

  expect(getJobStatus).not.toHaveBeenCalled();
  expect(screen.queryByText("Processing complete. Your estimate is ready.")).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("Upload a tender PDF to get started.");
});

it("restores a completed job only after the backend confirms it", async () => {
  window.localStorage.setItem("lastTenderJobId", "job1");
  vi.mocked(getJobStatus).mockResolvedValue({ job_id: "job1", status: "completed", created_at: "today", started_at: "today", completed_at: "today", error: null, position_counts_by_status: {} });

  renderUpload("/processing/job1");

  expect(await screen.findByText("Processing complete. Your estimate is ready.")).toBeInTheDocument();
});

it("enables review only after backend completion", async () => {
  vi.mocked(uploadTenderPdf).mockResolvedValue({ job_id: "job1", status: "completed", created_at: "today" });
  vi.mocked(getJobStatus).mockResolvedValue({ job_id: "job1", status: "completed", created_at: "today", started_at: null, completed_at: null, error: null, position_counts_by_status: {} });
  renderUpload();
  const user = userEvent.setup();
  await user.upload(document.querySelector('input[type="file"]')!, new File(["pdf"], "tender.pdf", { type: "application/pdf" }));
  await user.click(screen.getByRole("button", { name: /start processing/i }));
  expect(await screen.findByText("Processing complete. Your estimate is ready.")).toBeInTheDocument();
  expect(within(document.querySelector(".upload-panel")!).getByRole("button", { name: /proceed to estimate & review/i })).toBeEnabled();
  expect(await screen.findByRole("link", { name: /proceed to estimate & review/i })).toHaveAttribute("href", "/review/job1");
});

it("shows loading until the backend status confirms failure", async () => {
  let resolveUpload!: (job: Awaited<ReturnType<typeof uploadTenderPdf>>) => void;
  let resolveStatus!: (status: Awaited<ReturnType<typeof getJobStatus>>) => void;
  vi.mocked(uploadTenderPdf).mockReturnValue(new Promise(resolve => { resolveUpload = resolve; }));
  vi.mocked(getJobStatus).mockReturnValue(new Promise(resolve => { resolveStatus = resolve; }));
  renderUpload();
  const user = userEvent.setup();
  await user.upload(document.querySelector('input[type="file"]')!, new File(["pdf"], "tender.pdf", { type: "application/pdf" }));
  await user.click(screen.getByRole("button", { name: /start processing/i }));

  expect(await screen.findByText("Uploading tender...")).toBeInTheDocument();
  expect(screen.queryByText("Ready to process.")).not.toBeInTheDocument();
  expect(within(document.querySelector(".upload-panel")!).getByRole("button", { name: /processing/i })).toBeDisabled();
  expect(screen.queryByText("Processing complete. Your estimate is ready.")).not.toBeInTheDocument();
  await act(async () => {
    resolveUpload({ job_id: "job1", status: "queued", created_at: "today" });
  });
  expect(await screen.findByText("Processing tender...")).toBeInTheDocument();
  await act(async () => {
    resolveStatus({ job_id: "job1", status: "failed", created_at: "today", started_at: "today", completed_at: null, error: { code: "processing_failed", message: "Tender parsing failed." }, position_counts_by_status: {} });
  });
  expect(await screen.findByText("Tender parsing failed.")).toBeInTheDocument();
  expect(screen.queryByText("Processing complete. Your estimate is ready.")).not.toBeInTheDocument();
});

it("shows backend processing without reverting to the ready state", async () => {
  vi.mocked(uploadTenderPdf).mockResolvedValue({ job_id: "job1", status: "queued", created_at: "today" });
  vi.mocked(getJobStatus).mockResolvedValue({ job_id: "job1", status: "processing", created_at: "today", started_at: "today", completed_at: null, error: null, position_counts_by_status: {} });
  renderUpload();
  const user = userEvent.setup();
  await user.upload(document.querySelector('input[type="file"]')!, new File(["pdf"], "tender.pdf", { type: "application/pdf" }));
  await user.click(screen.getByRole("button", { name: /start processing/i }));

  expect(await screen.findByText("Processing tender...")).toBeInTheDocument();
  expect(screen.queryByText("Ready to process.")).not.toBeInTheDocument();
  expect(within(document.querySelector(".upload-panel")!).getByRole("button", { name: /processing/i })).toBeDisabled();
});

it("does not restore stale success after a new file is selected", async () => {
  window.localStorage.setItem("lastTenderJobId", "old-job");
  let resolveStatus!: (status: Awaited<ReturnType<typeof getJobStatus>>) => void;
  vi.mocked(getJobStatus).mockReturnValue(new Promise(resolve => { resolveStatus = resolve; }));
  renderUpload("/processing/old-job");
  const user = userEvent.setup();

  await user.upload(document.querySelector('input[type="file"]')!, new File(["pdf"], "new-tender.pdf", { type: "application/pdf" }));
  await act(async () => {
    resolveStatus({ job_id: "old-job", status: "completed", created_at: "today", started_at: "today", completed_at: "today", error: null, position_counts_by_status: {} });
  });

  expect(screen.queryByText("Processing complete. Your estimate is ready.")).not.toBeInTheDocument();
  expect(screen.getByText("Ready to process.")).toBeInTheDocument();
  expect(within(document.querySelector(".upload-panel")!).getByRole("button", { name: /start processing/i })).toBeEnabled();
});

it("keeps advancement disabled after an upload failure and permits retry", async () => {
  vi.mocked(uploadTenderPdf).mockRejectedValue(new Error("Backend unavailable"));
  renderUpload();
  const user = userEvent.setup();
  await user.upload(document.querySelector('input[type="file"]')!, new File(["pdf"], "tender.pdf", { type: "application/pdf" }));
  await user.click(screen.getByRole("button", { name: /start processing/i }));
  expect(await screen.findByText("Backend unavailable")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /proceed to estimate & review/i })).toBeDisabled();
  expect(screen.getByRole("button", { name: /retry processing/i })).toBeEnabled();
});
