# Phase 2 AI-Assisted Matching Experiment Design

This document defines a planned offline experiment only. It does not integrate an LLM into the production extraction, matching, pricing, API, upload, or job pipeline.

## Current Implemented Baseline

Implemented Phase 2 behavior remains deterministic:

- PDF text is extracted locally with `pdf_ingestion.py`.
- `position_parser.py` preserves original German descriptions and source pages.
- Technical attributes are parsed into language-independent fields.
- `product_matching.py` uses deterministic German-English cues, units, dimensions, diameters, fire ratings, materials and model hints.
- Prices are calculated only through the existing Python pricing engine.
- `supplier_quote_required` rows keep catalogue-derived material values as provisional estimates until actual supplier quotes are obtained.
- Rows without adequate evidence remain `insufficient_information`, `review_required`, `supplier_quote_required` or `non_priceable`.

No AI accuracy improvement has been measured yet.

## Experiment Goal

Measure whether an AI-assisted candidate ranker can improve catalogue candidate selection for German tender rows that the current deterministic matcher cannot price safely.

The experiment must answer:

1. Does AI ranking find the same product IDs a human estimator would accept?
2. Does it correctly abstain when the supplied catalogue has no matching product?
3. Does it surface technical mismatches instead of glossing over them?
4. Does it reduce review effort without increasing unsafe automatic pricing?

## Failure-Analysis Dataset

Create a human-reviewed sample from the current Phase 2 full output. The first audit sample has been checked in as:

```text
evaluation/phase2_failure_analysis_sample.jsonl
```

Sampling scope:

- Include only rows whose current status is `insufficient_information` or `review_required`.
- Stratify by reason code and product family signals.
- Include enough negative cases where no catalogue product is valid.
- Keep supplier-package rows only if they are being evaluated for match quality; their costs remain provisional.
- Exclude confirmed `non_priceable` records unless evaluating false positives in extraction/classification.

Recommended first sample:

| Group | Current Evidence | Target Count |
|---|---|---:|
| No plausible catalogue match | `no_plausible_catalogue_match` | 20 |
| Low-context extraction | `parsing_incomplete_or_low_context` | 10 |
| Technical conflict review | `technical_conflict_review_required` | 8 |
| Ambiguous dimensions | `ambiguous_dimension_unit` conflict flag | 5 |
| Known catalogue negative controls | clearly absent catalogue families such as grilles/regenhut/sensors when unsupported | 7 |

Minimum row fields:

```json
{
  "sample_id": "FA-0001",
  "lv_id": "PDF080-04",
  "source_page": 80,
  "source_language": "de",
  "original_german_description": "original preserved tender text",
  "source_line": "quantity/source line",
  "quantity": 2.0,
  "unit": "pc",
  "technical_attributes": {
    "dimensions": [],
    "model_code_dimensions": [],
    "ambiguous_dimensions": [],
    "diameters": [],
    "fire_ratings": [],
    "materials": [],
    "model_hints": []
  },
  "current_status": "insufficient_information",
  "current_reason_code": "no_plausible_catalogue_match",
  "current_matched_product_id": null,
  "human_label": {
    "decision": "accept|review|abstain",
    "accepted_product_id": null,
    "acceptable_candidate_product_ids": [],
    "rejected_candidate_product_ids": [],
    "technical_mismatches": [],
    "notes": ""
  }
}
```

The human label is required before using any row for AI scoring. The current checked-in sample records source evidence, current results, failure categories and recommended corrections, but it is not yet a human-labelled accuracy benchmark.

## Candidate Set Restrictions

The AI-assisted ranker may only rank products already present in `catalog.csv`.

It must not:

- invent product IDs;
- invent prices, discounts, install codes or productivity rules;
- modify `catalog.csv`, `productivity.csv`, `project_parameters.json` or golden example files;
- decide final pricing status;
- convert a supplier-package estimate into a confirmed supplier quote.

Candidate generation should stay deterministic before AI is called:

1. Filter by unit where possible.
2. Filter or boost by product family signals such as valve, damper, silencer, insulation, fire protection, ductwork, controls.
3. Include deterministic matcher output, if any, as one candidate.
4. Include only compact candidate records from `catalog.csv`: `product_id`, category, subcategory, model, description, unit, install code, source type and supplier quote flag.
5. Cap candidate count per row, for example top 8-12 deterministic candidates, to control cost and reduce distraction.

## Isolated Evaluation Interface

The experiment should be implemented outside production matching. Proposed files:

```text
src/tender_pricing/ai_matching_evaluation.py
evaluation/phase2_failure_analysis_sample.jsonl
evaluation/ai_matching_results.jsonl
scripts/evaluate_ai_matching.py
tests/test_ai_matching_evaluation.py
```

The production pipeline must continue to call only:

```text
match_positions(...)
match_and_price_position(...)
select_catalog_product(...)
```

The proposed evaluation interface:

```python
def build_ai_matching_prompt_case(
    position: dict,
    catalogue_candidates: list[dict],
) -> dict:
    """Return a structured, minimal case for an external ranker."""


def validate_ai_ranker_output(
    output: dict,
    allowed_product_ids: set[str],
) -> dict:
    """Validate schema and reject invented product IDs or malformed decisions."""


def compare_rule_and_ai_results(
    human_label: dict,
    rule_result: dict,
    ai_result: dict,
) -> dict:
    """Return metrics inputs without changing production pricing."""
```

This module may prepare prompts and validate saved responses, but the first implementation should not make live API calls. Saved responses can be produced manually or by a separately approved experiment runner.

## Structured AI Output

Required structured output per evaluated row:

```json
{
  "lv_id": "PDF080-04",
  "ranked_candidates": [
    {
      "product_id": "P-SIL-001",
      "confidence": 0.64,
      "evidence": [
        "German text contains Schalldämpfer",
        "explicit dimensions overlap catalogue model dimensions"
      ],
      "technical_mismatches": [
        "source has ambiguous 1x230 without unit"
      ],
      "missing_evidence": [
        "catalogue does not state material V2A"
      ]
    }
  ],
  "ambiguity": [
    "same German term could refer to unsupported grille family"
  ],
  "recommendation": "accept|review|abstain",
  "recommended_product_id": null,
  "rationale": "brief estimator-readable rationale"
}
```

Validation rules:

- `recommended_product_id` must be `null` when recommendation is `review` or `abstain`.
- Every candidate `product_id` must exist in `catalog.csv`.
- `confidence` is advisory and must not trigger automatic pricing.
- Technical mismatches must be preserved for estimator review.
- A row with unresolved dimension, fire-rating, material or unit conflicts cannot be auto-accepted.

## Evaluation Metrics

Primary metrics:

- Top-1 accuracy against human-accepted product ID.
- Top-3 recall against human-acceptable product IDs.
- Abstention precision: rows marked `abstain` that human also labels no valid catalogue match.
- Unsafe-accept rate: AI recommends `accept` where human label is `review` or `abstain`.
- Technical-mismatch recall: known mismatches surfaced in the output.

Secondary metrics:

- Review reduction potential: rows where AI gives a useful ranked shortlist but still recommends `review`.
- Candidate-set coverage: percentage of human-accepted product IDs present in the deterministic candidate set before AI ranking.
- API cost per evaluated row and total sample cost.
- Latency per row.
- Schema-validation failure rate.

## API-Cost Tracking

Any future runner must record:

```json
{
  "model": "model-name",
  "provider": "provider-name",
  "input_tokens": 0,
  "output_tokens": 0,
  "estimated_cost_chf": 0.0,
  "request_id": "redacted-or-local-id",
  "created_at": "ISO-8601 timestamp"
}
```

Credentials must not be committed. Raw prompts and outputs should be stored only if they contain the minimal position text and catalogue candidates required for audit.

## Regression Tests Before Any Integration

Required tests for the isolated evaluation module:

- Reject invented `product_id` values.
- Reject malformed recommendations.
- Preserve original German text in prompt cases.
- Ensure catalogue candidates are sourced from `catalog.csv` only.
- Ensure supplier-package candidates keep `supplier_quote_required=true`.
- Ensure AI recommendations do not call pricing functions or change production statuses.
- Compare deterministic and AI results against a small human-labelled fixture.

Existing Phase 1 golden tests and Phase 2 deterministic tests must remain unchanged.

## Stop/Go Criterion

Stop, do not integrate, if any of the following occur:

- Unsafe-accept rate is above 0 on the human-reviewed sample.
- Candidate-set coverage is below 95 percent for rows with a human-accepted product.
- Any AI output invents products or suppresses technical mismatches after validation.
- API cost or latency is unacceptable for expected tender volume.
- Human reviewers judge rationales too vague for audit.

Consider a guarded integration only if:

- Human-labelled sample size is at least 50 rows.
- Top-3 recall is at least 90 percent on rows with a valid catalogue match.
- Abstention precision is at least 90 percent on no-match rows.
- Unsafe-accept rate is 0.
- The integration remains review-only: AI may propose candidates, but Python deterministic pricing remains the only source of costs.

## Integration Boundary

Even after a successful experiment, the first production-facing use should be a review aid:

- AI output may populate candidate suggestions and rationale.
- It must not change `status` to `calculated`.
- It must not write prices.
- It must not mark supplier-package costs as confirmed.
- Estimator acceptance must be explicit and auditable before any production pricing change.
