# Phase 8F - Final Offer PDF Export

Phase 8F connects the existing Phase 8E price-overlay prototype to uploaded jobs.

## Backend API

- `POST /jobs/{job_id}/final-offer`
  - Generates `final_offer/priced_offer.pdf` for the uploaded job.
  - Applies the current saved review state before export.
  - Overlays only `pricing_authorized` `calculated` rows with accepted direct costs.
  - Leaves `supplier_quote_required`, `review_required`, `insufficient_information`, and `non_priceable` rows blank.
  - Returns a validation report with mapped rows, skipped mappings, warnings, and download URL.

- `GET /jobs/{job_id}/final-offer`
  - Returns the latest validation report if generation has already run.

- `GET /jobs/{job_id}/final-offer/pdf`
  - Downloads the generated PDF.

## UI

The Final Offer page can generate the priced PDF for the active uploaded job, display export warnings, show mapped and skipped rows, and open the generated PDF.

## Storage

Generated files are stored under the uploaded job directory:

- `final_offer/priced_offer.pdf`
- `final_offer/validation_report.json`
- `final_offer/overlay_mapping.json`

The job registry is still in memory, but completed jobs can now be recovered from their local upload directory when `result.json` and the uploaded PDF are present.

## Limitations

- Mapping remains conservative. Ambiguous source-line matches are skipped rather than guessed.
- Supplier-package catalogue estimates remain provisional and are not exported as final accepted prices.
- Full 202-page tender export has not been validated in this phase.
- No database, queue, LLM, or alternate overlay engine was added.
