import { describe, expect, it } from "vitest";
import { positionCategory } from "./category";
import type { TenderPosition } from "./types";

function position(overrides: Partial<TenderPosition>): TenderPosition {
  return {
    lv_id: "PDF001-01",
    source_page: 1,
    system: null,
    source_language: "de",
    original_description: "",
    quantity: 1,
    unit: "pc",
    original_unit: "Stk",
    source_line: "",
    evidence: "",
    technical_attributes: {},
    matched_product_id: null,
    match_confidence: 0,
    match_method: "unmatched",
    match_reason: "",
    classification: "ambiguous",
    classification_reason_code: "",
    classification_reason: "",
    status: "insufficient_information",
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

describe("positionCategory", () => {
  it("uses catalogue metadata before German text signals", () => {
    const row = position({
      original_description: "Zuluftgitter",
      catalogue_traceability: {
        product_id: "P-SIL-001",
        category: "Silencer",
        subcategory: "Rectangular",
        manufacturer: "Demo",
        model: "RS",
        description: "Rectangular silencer",
        unit: "pc",
        install_code: "SILENCER",
        source_type: "supplier_package",
        supplier_quote_required: true
      }
    });

    expect(positionCategory(row)).toBe("silencers");
  });

  it("classifies German supply and exhaust terms without changing status", () => {
    const row = position({
      original_description: "Zuluft - Tellerventil Grösse Ø 10 cm Stk 5",
      status: "insufficient_information"
    });

    expect(positionCategory(row)).toBe("supply-air-valves");
    expect(row.status).toBe("insufficient_information");
  });

  it("separates exhaust valve signals from supply valve signals", () => {
    const row = position({
      original_description: "Abluft - Tellerventil Grösse Ø 10 cm Stk 5"
    });

    expect(positionCategory(row)).toBe("exhaust-air-valves");
  });

  it("leaves unsupported product families unclassified", () => {
    const row = position({
      original_description: "Regenhut Material V2A B x H 110 x 35 cm Stk 1"
    });

    expect(positionCategory(row)).toBe("other");
  });
});
