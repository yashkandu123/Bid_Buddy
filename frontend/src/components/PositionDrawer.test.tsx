import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PositionDrawer } from "./PositionDrawer";
import type { CatalogItem, TenderPosition, TenderResult } from "../app/types";
import { updatePositionReview } from "../app/apiClient";

vi.mock("../app/apiClient", () => ({
  updatePositionReview: vi.fn()
}));

describe("PositionDrawer", () => {
  beforeEach(() => {
    vi.mocked(updatePositionReview).mockReset();
  });

  it("saves a manual unit cost through the calculation API", async () => {
    const user = userEvent.setup();
    vi.mocked(updatePositionReview).mockResolvedValue(result());
    render(<PositionDrawer position={position()} catalog={catalog()} jobId="abc123" onClose={vi.fn()} onSaved={vi.fn()} />);
    await user.clear(screen.getByLabelText(/unit cost/i));
    await user.type(screen.getByLabelText(/unit cost/i), "100");
    await user.click(screen.getByRole("button", { name: /save and recalculate/i }));
    expect(updatePositionReview).toHaveBeenCalledWith("abc123", "PDF001-01", expect.objectContaining({ net_unit_cost_chf: 100 }));
    expect(screen.getByText(/edited unit cost/i)).toBeInTheDocument();
  });

  it("automatically recalculates quantity edits and surfaces backend errors", async () => {
    const user = userEvent.setup();
    vi.mocked(updatePositionReview).mockRejectedValue(new Error("Recalculation failed"));
    render(<PositionDrawer position={position()} catalog={catalog()} jobId="abc123" onClose={vi.fn()} onSaved={vi.fn()} />);
    await user.clear(screen.getByLabelText(/quantity/i));
    await user.type(screen.getByLabelText(/quantity/i), "8");
    await waitFor(() => expect(updatePositionReview).toHaveBeenCalledWith("abc123", "PDF001-01", expect.objectContaining({ quantity: 8 })));
    expect(await screen.findByText("Recalculation failed")).toBeInTheDocument();
  });

  it("saves supported estimator fields through the backend API", async () => {
    const user = userEvent.setup();
    const updated = result();
    vi.mocked(updatePositionReview).mockResolvedValue(updated);
    const onSaved = vi.fn();

    render(
      <PositionDrawer
        position={position()}
        catalog={catalog()}
        jobId="abc123"
        onClose={vi.fn()}
        onSaved={onSaved}
      />
    );

    await user.clear(screen.getByLabelText(/quantity/i));
    await user.type(screen.getByLabelText(/quantity/i), "7");
    await user.selectOptions(screen.getByLabelText(/catalogue product/i), "P-AIR-002");
    await user.type(screen.getByLabelText(/estimator notes/i), "Checked by estimator");
    await user.click(screen.getByRole("button", { name: /save and recalculate/i }));

    expect(updatePositionReview).toHaveBeenCalledWith("abc123", "PDF001-01", {
      quantity: 7,
      unit: "pc",
      matched_product_id: "P-AIR-002",
      estimator_notes: "Checked by estimator"
    });
    expect(onSaved).toHaveBeenCalledWith(updated);
  });
});

function catalog(): CatalogItem[] {
  return [
    {
      product_id: "P-AIR-001",
      category: "Air terminal",
      subcategory: "Supply valve",
      manufacturer: "Demo",
      model: "DV-Z-100",
      description: "Supply air valve DN100",
      unit: "pc",
      list_price_chf: "85",
      discount_pct: "12",
      net_cost_chf: "74.8",
      install_code: "DIFFUSER",
      source_type: "catalog",
      supplier_quote_required: "false"
    },
    {
      product_id: "P-AIR-002",
      category: "Air terminal",
      subcategory: "Supply valve",
      manufacturer: "Demo",
      model: "DV-Z-125",
      description: "Supply air valve DN125",
      unit: "pc",
      list_price_chf: "98",
      discount_pct: "12",
      net_cost_chf: "86.24",
      install_code: "DIFFUSER",
      source_type: "catalog",
      supplier_quote_required: "false"
    }
  ];
}

function position(): TenderPosition {
  return {
    lv_id: "PDF001-01",
    source_page: 1,
    system: null,
    source_language: "de",
    original_description: "Zuluft - Tellerventil",
    quantity: 5,
    unit: "pc",
    original_unit: "Stk",
    source_line: "Stk 5",
    evidence: "",
    technical_attributes: {},
    matched_product_id: "P-AIR-001",
    match_confidence: 0.9,
    match_method: "test",
    match_reason: "",
    classification: "priceable_candidate",
    classification_reason_code: "",
    classification_reason: "",
    status: "calculated",
    review_required: false,
    conflict_flags: [],
    duplicate_group_id: null,
    duplicate_count: 1,
    duplicate_classification: "unique",
    duplicate_review_required: false,
    supplier_quote_required: false,
    catalogue_traceability: null,
    productivity_traceability: null,
    accepted_direct_position_cost_chf: 806.26
  };
}

function result(): TenderResult {
  return {
    schema_version: "phase4.v1",
    job_id: "abc123",
    scope: "test",
    positions: [position()],
    position_count: 1,
    status_counts: { calculated: 1 },
    project_totals: {
      summary: { material_cost_chf: 1, labour_cost_chf: 1, direct_cost_chf: 2, cost_baseline_chf: 3 },
      confirmed: segment(),
      provisional: segment(),
      combined_estimate: segment(),
      supplier_quotes_outstanding: 0,
      supplier_quote_note: ""
    },
    baseline_reconciliation_warning: {
      code: "warning",
      severity: "warning",
      documented_in: "",
      current_formula_cost_baseline_chf: 1,
      expected_reference_cost_baseline_chf: 1,
      difference_chf: 0,
      message: ""
    },
    warnings: []
  };
}

function segment() {
  return {
    label: "segment",
    summary: { material_cost_chf: 1, labour_cost_chf: 1, direct_cost_chf: 2, cost_baseline_chf: 3 },
    included_position_count: 1,
    excluded_position_count: 0,
    included_statuses: ["calculated"],
    formula_note: ""
  };
}
