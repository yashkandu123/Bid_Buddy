import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { finalOfferPdfUrl, generateFinalOffer, getFinalOfferReport } from "../app/apiClient";
import { FinalOfferPage } from "./FinalOfferPage";

vi.mock("../app/apiClient", () => ({
  finalOfferPdfUrl: vi.fn(),
  generateFinalOffer: vi.fn(),
  getFinalOfferReport: vi.fn()
}));

describe("FinalOfferPage", () => {
  beforeEach(() => {
    vi.mocked(finalOfferPdfUrl).mockReturnValue("http://127.0.0.1:8000/jobs/job-123/final-offer/pdf");
    vi.mocked(generateFinalOffer).mockReset();
    vi.mocked(getFinalOfferReport).mockReset();
  });

  it("generates a final offer PDF and shows validation results", async () => {
    vi.mocked(getFinalOfferReport).mockRejectedValue(new Error("Final offer PDF has not been generated."));
    vi.mocked(generateFinalOffer).mockResolvedValue(sampleReport());

    renderFinalPage();
    await userEvent.click(await screen.findByRole("button", { name: /generate pdf/i }));

    await waitFor(() => expect(generateFinalOffer).toHaveBeenCalledWith("job-123"));
    expect(await screen.findByRole("link", { name: /open priced pdf/i })).toHaveAttribute(
      "href",
      "http://127.0.0.1:8000/jobs/job-123/final-offer/pdf"
    );
    expect(screen.getByText(/supplier-package rows remain provisional/i)).toBeInTheDocument();
    expect(screen.getByText("PDF001-06")).toBeInTheDocument();
  });
});

function renderFinalPage() {
  render(
    <MemoryRouter initialEntries={["/final/job-123"]}>
      <Routes>
        <Route path="/final/:jobId" element={<FinalOfferPage />} />
      </Routes>
    </MemoryRouter>
  );
}

function sampleReport() {
  return {
    schema_version: "phase8f.pdf_overlay_export.v1",
    job_id: "job-123",
    status: "completed",
    created_at: "2026-10-10T00:00:00+00:00",
    source_pdf: "demo.pdf",
    page_count: 20,
    output_pdf: "job-123/final_offer/priced_offer.pdf",
    download_url: "/jobs/job-123/final-offer/pdf",
    validation_report: "job-123/final_offer/validation_report.json",
    mapping_report: "job-123/final_offer/overlay_mapping.json",
    pricing_policy: "Only pricing_authorized calculated rows with accepted direct costs are overlaid.",
    summary: {
      accepted_position_count: 1,
      mapped_position_count: 1,
      skipped_mapping_count: 0,
      supplier_quotes_outstanding: 1,
      unresolved_position_counts: { review_required: 2 }
    },
    mapped_positions: [
      {
        lv_id: "PDF001-06",
        source_page: 1,
        unit_price_chf: 161.25,
        position_total_chf: 806.26,
        placement_status: "mapped",
        placement_reason: "Unique source_line match on the same PDF page."
      }
    ],
    skipped_positions: [],
    warnings: [
      {
        code: "supplier_quotes_outstanding",
        severity: "warning",
        message: "1 supplier-package rows remain provisional and were not overlaid as final prices."
      }
    ]
  };
}
