import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PositionTable } from "./PositionTable";
import type { TenderPosition } from "../app/types";

describe("PositionTable", () => {
  it("does not display review-required preview costs as accepted prices", () => {
    render(
      <PositionTable
        positions={[
          position({
            status: "review_required",
            direct_position_cost_chf: 1234.56,
            accepted_direct_position_cost_chf: null
          })
        ]}
        onSelect={vi.fn()}
      />
    );

    expect(screen.queryByText(/1’234\.56|1,234\.56/)).not.toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

function position(overrides: Partial<TenderPosition>): TenderPosition {
  return {
    lv_id: "PDF001-01",
    source_page: 1,
    system: null,
    source_language: "de",
    original_description: "Abluft - Tellerventil",
    quantity: 1,
    unit: "pc",
    original_unit: "Stk",
    source_line: "Stk 1",
    evidence: "",
    technical_attributes: {},
    matched_product_id: "P-AIR-003",
    match_confidence: 0.7,
    match_method: "test",
    match_reason: "",
    classification: "priceable_candidate",
    classification_reason_code: "",
    classification_reason: "",
    status: "review_required",
    review_required: true,
    conflict_flags: [],
    duplicate_group_id: null,
    duplicate_count: 1,
    duplicate_classification: "unique",
    duplicate_review_required: false,
    supplier_quote_required: false,
    catalogue_traceability: null,
    productivity_traceability: null,
    ...overrides
  };
}
