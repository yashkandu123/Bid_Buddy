# Phase 6 LLM Experiment Audit

Phase 6 audited the isolated Phase 5 AI matching experiment and prepared an optional real-provider adapter. This remains an evaluation experiment, not production integration.

## Audit Findings

Verified:

- The fake provider is clearly named `fake` and its rationale states that no model call was made.
- Candidate retrieval returns product IDs from `catalog.csv` only.
- AI validation rejects product IDs outside the supplied candidate set.
- Critical technical conflicts are preserved and can downgrade `accept` to review-only.
- `pricing_authorized` remains `false` for every AI result.
- Missing human labels report `blocked_missing_human_labels`.
- Provider failures are captured without fabricating an AI result.
- Production extraction, matching, pricing, API flow and golden outputs are not called by the experiment.

Confirmed defect fixed:

- Malformed provider output was validated by lower-level helpers, but `run_ai_matching_case` could let a validation exception escape. It now records `validation_error` and returns no `ai_result`.

## Real Provider Preparation

Added `OpenAIResponsesProvider`, an optional adapter using the existing `httpx` dependency. No new dependency was added.

The provider:

- uses the existing structured output schema and local validation;
- is disabled unless explicitly selected and enabled;
- reads credentials from environment variables;
- sends only one tender position and bounded catalogue candidates;
- uses timeouts and bounded retries;
- records latency in the harness;
- records token usage when reported by the provider;
- leaves cost as `null` unless reliable provider cost data is returned.

The fake provider remains the default for tests and normal local runs.

## Required Environment Variables For Real Calls

```text
OPENAI_API_KEY
TENDER_AI_ENABLE_REAL_PROVIDER=true
```

Optional:

```text
TENDER_AI_MODEL
TENDER_AI_BASE_URL
TENDER_AI_TIMEOUT_SECONDS
TENDER_AI_MAX_RETRIES
TENDER_AI_MAX_OUTPUT_TOKENS
```

## Commands

Fake experiment:

```powershell
& 'C:\Users\saiya\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' scripts\evaluate_ai_matching.py --project-root . --sample outputs\phase2_review_sample.jsonl --output evaluation\ai_matching_results.json
```

Small real-provider experiment:

```powershell
& 'C:\Users\saiya\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' scripts\evaluate_ai_matching.py --project-root . --provider openai --max-positions 3 --max-candidates 6 --sample outputs\phase2_review_sample.jsonl --output evaluation\ai_matching_results_real.json
```

## Current Limitation

The review sample still has blank human labels. Accuracy evaluation remains blocked until an estimator fills `human_labels` in `outputs/phase2_review_sample.jsonl`.

No real LLM call was executed during this implementation.
