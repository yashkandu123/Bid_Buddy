export type JobStatusName = "queued" | "processing" | "completed" | "failed";

export type ApiErrorPayload = {
  detail?: string | { message?: string; code?: string };
};

export type HealthResponse = {
  status: string;
  service: string;
  schema_version: string;
};

export type JobCreateResponse = {
  job_id: string;
  status: JobStatusName;
  created_at: string;
};

export type JobStatusResponse = {
  job_id: string;
  status: JobStatusName;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  position_counts_by_status: Record<string, number>;
  error: { code: string; message: string } | null;
};

export type ConflictFlag = {
  code: string;
  message: string;
};

export type CatalogueTraceability = {
  product_id: string;
  category: string;
  subcategory: string;
  manufacturer: string;
  model: string;
  description: string;
  unit: string;
  install_code: string;
  source_type: string;
  supplier_quote_required: boolean;
};

export type CatalogItem = {
  product_id: string;
  category: string;
  subcategory: string;
  manufacturer: string;
  model: string;
  description: string;
  unit: string;
  install_code: string;
  source_type: string;
  supplier_quote_required: string;
  list_price_chf: string;
  discount_pct: string;
  net_cost_chf: string;
};

export type ProductivityTraceability = {
  install_code: string;
  work_type: string;
  unit: string;
  base_hours_per_unit: number;
  labour_role: string;
  default_hourly_rate_chf: number;
  factor_keys: string;
};

export type TenderPosition = {
  lv_id: string;
  source_page: number;
  system: string | null;
  source_language: string;
  original_description: string;
  quantity: number;
  unit: string;
  original_unit: string;
  source_line: string;
  evidence: string;
  technical_attributes: Record<string, unknown>;
  matched_product_id: string | null;
  match_confidence: number;
  match_method: string;
  match_reason: string;
  classification: string;
  classification_reason_code: string;
  classification_reason: string;
  insufficient_reason_code?: string;
  insufficient_reason?: string;
  status: string;
  review_required: boolean;
  conflict_flags: ConflictFlag[];
  duplicate_group_id: string | null;
  duplicate_count: number;
  duplicate_classification: string;
  duplicate_review_required: boolean;
  supplier_quote_required: boolean;
  catalogue_traceability: CatalogueTraceability | null;
  productivity_traceability: ProductivityTraceability | null;
  net_unit_cost_chf?: number;
  material_cost_chf?: number;
  labour_cost_chf?: number;
  direct_position_cost_chf?: number;
  cost_confirmation_status?: string;
  pricing_authorized?: boolean;
  accepted_material_cost_chf?: number | null;
  accepted_labour_cost_chf?: number | null;
  accepted_direct_position_cost_chf?: number | null;
  override_cost_preview?: {
    net_unit_cost_chf: number;
    material_cost_chf: number;
    adjusted_install_hours: number;
    labour_cost_chf: number;
    direct_position_cost_chf: number;
  };
  machine_values?: Partial<TenderPosition>;
  review_state?: {
    has_overrides: boolean;
    overridden_fields: string[];
    estimator_notes: string;
    updated_at: string | null;
    pricing_authorized: boolean;
    recalculation_status: string;
    validation_flags: ConflictFlag[];
  };
};

export type ProjectTotalsSegment = {
  label: string;
  summary: {
    material_cost_chf: number;
    labour_cost_chf: number;
    direct_cost_chf: number;
    cost_baseline_chf: number;
  };
  included_position_count: number;
  excluded_position_count: number;
  included_statuses: string[];
  formula_note: string;
};

export type TenderResult = {
  schema_version: string;
  job_id?: string;
  dataset_id?: string;
  scope: string;
  positions: TenderPosition[];
  position_count: number;
  status_counts: Record<string, number>;
  review_summary?: {
    review_required_rows: number;
    conflict_flagged_rows: number;
    duplicate_candidate_rows: number;
    duplicate_groups: number;
  };
  project_totals: {
    summary: ProjectTotalsSegment["summary"];
    confirmed: ProjectTotalsSegment;
    provisional: ProjectTotalsSegment;
    combined_estimate: ProjectTotalsSegment;
    supplier_quotes_outstanding: number;
    supplier_quote_note: string;
  };
  baseline_reconciliation_warning: {
    code: string;
    severity: string;
    documented_in: string;
    current_formula_cost_baseline_chf: number;
    expected_reference_cost_baseline_chf: number;
    difference_chf: number;
    message: string;
  };
  warnings: string[];
};

export type ProductCategory = {
  key: string;
  label: string;
};

export type PositionReviewPatch = {
  quantity?: number;
  net_unit_cost_chf?: number | null;
  unit?: string;
  matched_product_id?: string | null;
  estimator_notes?: string;
};

export type BidScenario = {
  scenario: string;
  margin_pct: number | null;
  cost_baseline_chf: number | null;
  raw_bid_price_chf: number | null;
  bid_price_chf: number | null;
  rounding_increment_chf: number | null;
  estimated_win_probability: number | null;
  probability_available: boolean;
  probability_model: string;
  expected_contribution_chf: number | null;
  expected_contribution_definition: string;
  complete: boolean;
  completion_reasons: string[];
};

export type BidScenariosResponse = {
  schema_version: string;
  job_id: string;
  currency: string;
  cost_basis: {
    basis: string;
    currency: string;
    cost_baseline_chf: number;
    direct_cost_chf: number;
    confirmed_cost_baseline_chf: number;
    provisional_cost_baseline_chf: number;
    confirmed_direct_cost_chf: number;
    provisional_direct_cost_chf: number;
    included_statuses: string[];
    included_position_count: number;
    excluded_position_count: number;
    unresolved_position_counts: Record<string, number>;
    supplier_quotes_outstanding: number;
    non_priceable_position_count: number;
    has_unresolved_positions: boolean;
    has_provisional_supplier_estimates: boolean;
    formula_note: string;
  };
  scenarios: BidScenario[];
  selection: {
    scenario_name: string | null;
    updated_at: string | null;
  };
  warnings: Array<{ code: string; severity: string; message: string }>;
  formula_audit: Record<string, string | string[]>;
};

export type FinalOfferReport = {
  schema_version: string;
  job_id: string;
  status: string;
  created_at: string;
  source_pdf: string;
  page_count: number;
  output_pdf: string;
  download_url: string;
  validation_report: string;
  mapping_report: string;
  pricing_policy: string;
  summary: {
    accepted_position_count: number;
    mapped_position_count: number;
    skipped_mapping_count: number;
    supplier_quotes_outstanding: number;
    unresolved_position_counts: Record<string, number>;
  };
  mapped_positions: Array<{
    lv_id: string;
    source_page: number;
    unit_price_chf: number | null;
    position_total_chf: number | null;
    placement_status: string;
    placement_reason: string;
  }>;
  skipped_positions: Array<{
    lv_id: string;
    source_page: number;
    placement_status: string;
    placement_reason: string;
  }>;
  warnings: Array<{ code: string; severity: string; message: string }>;
};
