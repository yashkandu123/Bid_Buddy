# Phase 2 Extraction Slice

This phase adds a first full-PDF extraction and matching pipeline. It does not add an API, n8n workflow, upload handling, or web UI.

## Approach

- `pdf_ingestion.py` extracts text page by page and preserves PDF page numbers.
- `position_parser.py` identifies candidate LV rows from German quantity/unit patterns such as `Stk 5` and `m2 52`.
- Original German text is preserved in `original_description`; `source_language` is set to `de`.
- Technical attributes are normalized into language-independent fields such as dimensions, diameters, fire ratings, materials and model hints.
- `product_matching.py` applies deterministic cross-language catalogue matching from German terms, English catalogue terms, units, dimensions, fire ratings and known model/product cues.
- Existing pricing functions are reused for matched positions.
- Unmatched rows are kept with `insufficient_information`; supplier packages remain `supplier_quote_required`.

Synthetic IDs like `PDF078-01` are generated because the PDF does not expose the `LV0001` IDs directly.

## Runtime

PDF extraction requires `pdfplumber`. The default local Python in this workspace does not have it, but the bundled Codex runtime does:

```powershell
& 'C:\Users\saiya\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' scripts\process_demo_tender.py --project-root . --output-dir outputs\phase2_full
```

For a validation slice:

```powershell
& 'C:\Users\saiya\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' scripts\process_demo_tender.py --project-root . --output-dir outputs\phase2_slice --pages 78 79 80 106 107 163 164 169 170 171
```

## Current Results

Full PDF run:

```text
Extracted 221 position candidates from 202 pages
Review-required/provisional rows: 181
```

Validation against the 22 supplied example positions:

```text
22 / 22 found by source page, quantity, unit and suggested product ID.
```

This is still a conservative first pass. Many rows remain unmatched because the catalogue only covers a subset of tender content or the row needs more context than the current heuristic parser captures.

## German-English Matching Notes

The PDF is German while the CSV reference data is English. The matcher does not translate the tender text away. It preserves German evidence and uses deterministic bilingual cues such as:

```text
Tellerventil -> air valve / diffuser
Zuluft -> supply air
Abluft -> exhaust air
Brandschutzklappe -> fire damper
Schalldämpfer -> silencer
Volumenstromregler -> flow controller
Dämmung -> insulation
Durchdringung -> penetration / fire seal
```

Technical evidence remains primary: quantities, units, dimensions, DN/diameter values, fire ratings like `EI30` or `EI 90-S`, material hints like `V2A`, and model hints such as `Z-LVS`, `MS-F`, `TVJ-D`, `TVR-D` and `VFC`.

No LLM matching is currently used. If deterministic evidence is insufficient, rows stay reviewable instead of receiving invented matches.

## Planned AI-Assisted Matching Experiment

An offline, review-only AI matching experiment is defined in `PHASE2_AI_MATCHING_EXPERIMENT.md`. This is planned functionality, not production behavior.

The experiment is constrained to:

- compare the current rule-based matcher against an AI-assisted candidate ranker on human-labelled `insufficient_information` and `review_required` rows;
- rank only products already present in `catalog.csv`;
- emit structured evidence, technical mismatches, ambiguity and an `accept`, `review` or `abstain` recommendation;
- keep all price calculations deterministic in Python;
- keep supplier-package costs provisional until actual supplier quotes exist;
- require measured metrics, regression tests, API-cost tracking and a stop/go decision before any integration.

No live LLM calls, API credentials, production matcher changes, frontend work or golden-output changes are part of Phase 2 as currently implemented.
