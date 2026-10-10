# Project Rules and Reference Guide

> This file is a durable checklist, not a replacement for `README.md`, source code, tests, or tender data. Verify details in the current project. Do not invent missing facts.

## Objective
Turn a German ventilation tender bill of quantities (LV) into a traceable indicative priced offer through extraction, matching, classification, estimation, review, bid optimization, and final PDF output.

Original tender: `BKP_244_LV_Lueftung_260804.pdf`. When reviewing the full document, start at PDF page 1 unless the user explicitly specifies otherwise.

## Mandatory references
Before work affecting extraction, matching, classification, pricing, or output generation, inspect:
- `README.md`
- `example_lv_positions.csv`
- `expected_output_example.json`
- Relevant tests, source implementation, and current phase artifacts.

Do not assume reference examples are enforced by production code. Check whether tests exercise the production pipeline or only fixtures/helpers. If a mandatory reference is missing, stop and report it rather than substituting another dataset without approval.

## Extraction
- Preserve original German descriptions and source-page traceability.
- Exclude Bauteilliste component-list rows when the active scope explicitly says to exclude them from pricing-position inventory.
- A unit-like token followed by a number is not, by itself, evidence of a distinct position.
- Distinguish real positions, legitimate sub-items, duplicates, technical specifications, headings, and ambiguous candidates.
- Never invent quantities, units, dimensions, or technical attributes.

## Matching
- Match using product function/family and technical attributes, not text similarity alone.
- Explicit candidate-local evidence takes precedence over inherited context.
- Context may supplement missing attributes only when reliably associated with the same position/block.
- Context must not override conflicting dimensions, geometry, model tokens, units, or product function.
- Critical conflicts must remain unresolved/reviewable rather than silently selecting an incompatible product.
- Preserve matched product IDs, rationale, source evidence, and unresolved conflicts.
- Do not discard a reference mapping without evidence; do not assume a mapping is correct without checking compatibility.
- Do not lower thresholds globally just to increase match counts.

## Status vocabulary
These statuses have been used in the project; confirm exact definitions and precedence in the current README and code:
- `calculated`
- `supplier_quote_required`
- `assumption_applied`
- `review_required`
- `insufficient_information`
- `out_of_scope`
- `non_priceable`

Do not invent status names or force every candidate into `calculated`. A mapped product can still require review or a supplier quote.

## Pricing and commercial safety
Previously documented behavior:
- Material cost = quantity × net unit cost × (1 + material waste percentage).
- Installation hours = quantity × base hours per unit × applicable project factors.
- Site efficiency is applied reciprocally; other applicable factors multiply directly.
- Labour cost = installation hours × hourly rate.
- Direct position cost = material cost + labour cost.
- Baseline cost adds configured allowances/overhead.
- Selling price = baseline cost / (1 − target margin).

These are historical rules from project context. Verify current source and `project_parameters.json` before relying on them. Do not change formulas, factors, margins, allowances, rounding, or status precedence without explicit authorization. Supplier-package estimates are not supplier quotations; a numeric estimate is not commercially confirmed just because it has a `calculated` status.

## Traceability and output safety
- Preserve candidate IDs, source PDF page numbers, original descriptions, and evidence.
- Preserve previous phase artifacts unless replacement is explicitly authorized.
- Use new output directories for new audits/experiments.
- Report counts, exclusions, ambiguity, and limitations.
- Do not compare counts across different candidate populations without explaining granularity and inclusion rules.
- Do not claim official unique-position counts without sufficient source evidence.

## External services and secrets
No OpenAI/external AI-provider calls unless explicitly authorized for the current task. Never expose API keys or secrets or commit `.env` files.

## Phase boundaries
Perform only the phase approved by the user. Do not automatically continue into matching, pricing, optimization, or PDF generation. If blocked by missing inputs, report exact missing paths and stop.

## Conflict handling
If this file conflicts with `README.md`, tests, source code, or user instruction, identify the conflict. Do not silently choose the easiest interpretation. Follow the user's latest explicit instruction where applicable and report unresolved documentation conflicts.
