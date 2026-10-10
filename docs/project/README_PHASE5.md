# Phase 5 AI Matching Experiment

Phase 5 is an isolated experiment. It does not change production PDF extraction, deterministic matching, pricing, API behavior, upload jobs, frontend behavior or golden outputs.

## What It Adds

- `src/tender_pricing/ai_matching_experiment.py`
  - input schema builder for tender positions;
  - catalogue candidate retrieval from `catalog.csv` only;
  - structured AI-result validation;
  - critical technical mismatch flags;
  - fake AI provider for offline tests;
  - optional OpenAI Responses provider, disabled unless explicitly enabled;
  - evaluation harness for human-labelled samples.
- `scripts/evaluate_ai_matching.py`
  - reproducible CLI runner for the mock experiment.
- `tests/test_ai_matching_experiment.py`
  - network-free tests for schema, catalogue restrictions, invalid product IDs, mismatch handling, abstention, provider errors and evaluation blocking.

## Safety Boundaries

- The AI experiment never authorizes pricing.
- `pricing_authorized` is always `false`.
- Candidate product IDs must come from the supplied catalogue candidates.
- Supplier-package catalogue entries keep their `supplier_quote_required` flag.
- Critical conflicts such as diameter, dimension, geometry, fire-rating or ambiguous-unit issues force review even if a provider recommends `accept`.
- The fake provider is the only implemented provider. It makes no network calls and has no API cost.
- The fake provider remains the default. The real provider requires `--provider openai` plus `TENDER_AI_ENABLE_REAL_PROVIDER=true`.
- Real-provider output is still validated locally and never authorizes pricing.

## Input Sample

Default sample:

```text
outputs/phase2_review_sample.jsonl
```

Each record should preserve machine values separately from estimator labels. Estimators should fill only:

```text
human_labels.confirmed_product_id
human_labels.technical_compatibility
human_labels.priceability
human_labels.correction_category
human_labels.reviewer_notes
human_labels.confidence
```

Until at least one human label exists, evaluation reports:

```text
blocked_missing_human_labels
```

## Run The Mock Experiment

Use the bundled Codex Python runtime:

```powershell
& 'C:\Users\saiya\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' scripts\evaluate_ai_matching.py --project-root . --sample outputs\phase2_review_sample.jsonl --output evaluation\ai_matching_results.json
```

Expected behavior with the current blank-label sample:

```text
records: 16
evaluation: blocked_missing_human_labels
```

## Output

Default output:

```text
evaluation/ai_matching_results.json
```

The output contains:

- the bounded catalogue candidate list per sampled position;
- fake provider result;
- validation flags;
- latency in milliseconds;
- unsupported or fake API usage/cost metadata;
- evaluation status.

## Adding Human Labels

Fill `human_labels` in `outputs/phase2_review_sample.jsonl`, then rerun the script. Do not edit `machine_values`; those are the audit trail from Phase 2.

Valid label values are documented in each sample row under `human_label_guidance`.

## Tests

```powershell
& 'C:\Users\saiya\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests
```

The tests do not require network access, API credentials or paid API calls.

## Optional Real-Provider Experiment

The real-provider path is for a small evaluation run only. It is not production integration.

Required environment variables:

```text
OPENAI_API_KEY
TENDER_AI_ENABLE_REAL_PROVIDER=true
```

The CLI loads these from a project-root `.env` file if present, without printing values and without overriding variables already set in the shell. `.env` and `.env.*` are ignored by `.gitignore`; keep shareable placeholders in `.env.example`.

Optional environment variables:

```text
TENDER_AI_MODEL=gpt-4.1-mini
TENDER_AI_BASE_URL=https://api.openai.com/v1
TENDER_AI_TIMEOUT_SECONDS=30
TENDER_AI_MAX_RETRIES=1
TENDER_AI_MAX_OUTPUT_TOKENS=1200
```

Run a small bounded experiment:

```powershell
& 'C:\Users\saiya\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' scripts\evaluate_ai_matching.py --project-root . --provider openai --max-positions 3 --max-candidates 6 --sample outputs\phase2_review_sample.jsonl --output evaluation\ai_matching_results_real.json
```

Safety controls:

- only selected position fields and bounded catalogue candidates are sent;
- the whole PDF is never sent;
- candidates are still restricted to `catalog.csv`;
- invalid or invented IDs are rejected;
- critical technical mismatches force review;
- token usage is recorded when the provider reports it;
- cost remains `null` unless a provider returns reliable cost data.

The OpenAI Responses API supports structured JSON schema output, which this adapter uses for the model-facing schema.
