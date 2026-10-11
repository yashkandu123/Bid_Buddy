import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getCatalog, getJobResults } from "../app/apiClient";
import type { TenderResult } from "../app/types";
import { EstimateReviewPage } from "./EstimateReviewPage";

vi.mock("../app/apiClient", () => ({
  getCatalog: vi.fn(),
  getJobResults: vi.fn(),
  getPhase2FullTenderOutput: vi.fn()
}));

describe("EstimateReviewPage", () => {
  beforeEach(() => {
    vi.mocked(getCatalog).mockResolvedValue({ items: [], count: 0 });
    vi.mocked(getJobResults).mockResolvedValue(correctedResult());
    window.localStorage.clear();
  });

  it("uses the backend user-facing inventory for the count and table rows", async () => {
    render(
      <MemoryRouter initialEntries={["/review/job-123"]}>
        <Routes>
          <Route path="/review/:jobId" element={<EstimateReviewPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByRole("heading", { name: "2 positions" })).toBeInTheDocument();
    expect(screen.getByText("PDF078-01")).toBeInTheDocument();
    expect(screen.getByText("PDF079-01")).toBeInTheDocument();
    expect(screen.queryByText("RAW-COMPONENT-ROW")).not.toBeInTheDocument();
  });
});

function correctedResult(): TenderResult {
  const segment = {
    summary: { direct_cost_chf: 0, cost_baseline_chf: 0 },
    included_position_count: 0,
    excluded_position_count: 2,
    included_statuses: [],
    formula_note: ""
  };
  return {
    schema_version: "phase3.v1",
    job_id: "job-123",
    scope: "Corrected inventory",
    positions: [
      position("PDF078-01", 78, "Zuluft Tellerventil"),
      position("PDF079-01", 79, "Abluft Tellerventil")
    ],
    position_count: 2,
    status_counts: { insufficient_information: 2 },
    project_totals: {
      summary: segment.summary,
      confirmed: segment,
      provisional: segment,
      combined_estimate: segment,
      supplier_quotes_outstanding: 0,
      supplier_quote_note: ""
    },
    baseline_reconciliation_warning: {
      code: "baseline",
      severity: "warning",
      documented_in: "BASELINE_RECONCILIATION.md",
      current_formula_cost_baseline_chf: 0,
      expected_reference_cost_baseline_chf: 0,
      difference_chf: 0,
      message: "Baseline warning"
    },
    warnings: []
  } as unknown as TenderResult;
}

function position(lvId: string, sourcePage: number, description: string) {
  return {
    lv_id: lvId,
    source_page: sourcePage,
    original_description: description,
    source_line: `${description} Stk 1`,
    quantity: 1,
    unit: "pc",
    status: "insufficient_information",
    match_confidence: 0,
    review_required: true,
    conflict_flags: []
  };
}
