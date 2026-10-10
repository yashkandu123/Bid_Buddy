import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getBidScenarios, updateBidSelection } from "../app/apiClient";
import { BidOptimizationPage } from "./BidOptimizationPage";

vi.mock("../app/apiClient", () => ({
  getBidScenarios: vi.fn(),
  updateBidSelection: vi.fn()
}));

describe("BidOptimizationPage", () => {
  beforeEach(() => {
    vi.mocked(getBidScenarios).mockReset();
    vi.mocked(updateBidSelection).mockReset();
    window.localStorage.clear();
  });

  it("renders backend scenarios and cost-basis warnings", async () => {
    vi.mocked(getBidScenarios).mockResolvedValue(samplePayload());

    renderBidPage("/bid/job-123");

    expect(await screen.findByRole("heading", { name: "Aggressive" })).toBeInTheDocument();
    expect(screen.getByText(/supplier-package catalogue estimates/i)).toBeInTheDocument();
    expect(screen.getAllByText(/heuristic/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/CHF\s*711['’]000\.00/)).toBeInTheDocument();
  });

  it("saves scenario selection through the backend", async () => {
    vi.mocked(getBidScenarios).mockResolvedValue(samplePayload());
    vi.mocked(updateBidSelection).mockResolvedValue({
      ...samplePayload(),
      selection: { scenario_name: "Target", updated_at: "2026-10-10T00:00:00+00:00" }
    });

    renderBidPage("/bid/job-123");
    await screen.findByRole("heading", { name: "Target" });
    await userEvent.click(screen.getAllByRole("button", { name: /select scenario/i })[1]);

    await waitFor(() => expect(updateBidSelection).toHaveBeenCalledWith("job-123", "Target"));
    expect(await screen.findByText(/saved target for this job/i)).toBeInTheDocument();
  });
});

function renderBidPage(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/bid/:jobId" element={<BidOptimizationPage />} />
      </Routes>
    </MemoryRouter>
  );
}

function samplePayload() {
  return {
    schema_version: "phase8d.bid_scenarios.v1",
    job_id: "job-123",
    currency: "CHF",
    cost_basis: {
      basis: "combined_confirmed_and_provisional_estimate",
      currency: "CHF",
      cost_baseline_chf: 692321.57,
      direct_cost_chf: 624023.72,
      confirmed_cost_baseline_chf: 192611.66,
      provisional_cost_baseline_chf: 499709.91,
      confirmed_direct_cost_chf: 173844.82,
      provisional_direct_cost_chf: 450178.9,
      included_statuses: ["calculated", "supplier_quote_required"],
      included_position_count: 44,
      excluded_position_count: 172,
      unresolved_position_counts: { insufficient_information: 127, review_required: 8 },
      supplier_quotes_outstanding: 10,
      non_priceable_position_count: 37,
      has_unresolved_positions: true,
      has_provisional_supplier_estimates: true,
      formula_note: "Uses the documented Phase 1 formula."
    },
    scenarios: [
      {
        scenario: "Aggressive",
        margin_pct: 2.5,
        cost_baseline_chf: 692321.57,
        raw_bid_price_chf: 710073.41,
        bid_price_chf: 711000,
        rounding_increment_chf: 1000,
        estimated_win_probability: 0.7,
        probability_available: true,
        probability_model: "Heuristic",
        expected_contribution_chf: 13074.9,
        expected_contribution_definition: "(rounded_bid_price_chf - cost_baseline_chf) * estimated_win_probability",
        complete: false,
        completion_reasons: ["Supplier-package estimates are provisional until supplier quotes are confirmed."]
      },
      {
        scenario: "Target",
        margin_pct: 4,
        cost_baseline_chf: 692321.57,
        raw_bid_price_chf: 721168.3,
        bid_price_chf: 722000,
        rounding_increment_chf: 1000,
        estimated_win_probability: 0.63,
        probability_available: true,
        probability_model: "Heuristic",
        expected_contribution_chf: 18697.41,
        expected_contribution_definition: "(rounded_bid_price_chf - cost_baseline_chf) * estimated_win_probability",
        complete: false,
        completion_reasons: ["Supplier-package estimates are provisional until supplier quotes are confirmed."]
      }
    ],
    selection: { scenario_name: null, updated_at: null },
    warnings: [
      {
        code: "supplier_quotes_outstanding",
        severity: "warning",
        message: "Scenario cost basis includes provisional supplier-package catalogue estimates."
      }
    ],
    formula_audit: {
      bid_price_formula: "round_up(cost_baseline_chf / (1 - margin_pct / 100), round_to_chf)",
      cost_basis: "Uses project_totals.combined_estimate.summary.cost_baseline_chf.",
      probability_model: "Heuristic probability.",
      expected_contribution_definition:
        "(rounded_bid_price_chf - cost_baseline_chf) * estimated_win_probability"
    }
  };
}
