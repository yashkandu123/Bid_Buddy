# Phase 2B Pipeline Bundle Audit

## Scope and decision

The isolated `experiments/pipeline_bundle/` was audited independently against the current
project data. No bundle component was connected to the production extraction,
matching, pricing, API, or review path. This is intentional: the measured bundle
does not improve the 22-reference product-ID result and its pricing authorization
rules are weaker than the current project rules.

## Architecture

- Step 2: optional Docling conversion followed by LLM position extraction; regex
  parsing in `engine/parser.py` is the fallback.
- Step 3: optional LLM translation, keyword/size candidate retrieval, LLM reranking,
  and a deterministic product-ID/supplier-package guard; `engine/matcher.py` is the
  fallback.
- LLM client: standard-library HTTP against OpenAI-compatible endpoints, optional
  disk cache, and `StubLLM` for offline tests.
- Bundle pricing: a separate copy in `engine/pricing.py`; it was not integrated.
- Dependencies: Docling, pandas, NumPy, pdfplumber and pytest. The bundle contains
  no `data/` directory although its tests and documentation require one.

## LLM configuration and test classes

Providers and variables:

| Provider | Variable | Bundle default model |
|---|---|---|
| OpenAI | `OPENAI_API_KEY` | `gpt-4o-mini` |
| DeepSeek | `DEEPSEEK_API_KEY` | `deepseek-chat` |
| OpenRouter | `OPENROUTER_API_KEY` | `openai/gpt-4o-mini` |

The bundle reads process environment variables; it does not load the project
`.env` itself. The project root `.env` exists, `OPENAI_API_KEY` appears configured,
and the file is ignored and untracked. No secret value was printed or copied.

- Offline tests: JSON parsing, regex extraction, deterministic matching and pricing.
- Mocked LLM tests: translation, reranking, abstention, invalid-ID rejection and
  supplier-package status using `StubLLM`.
- Live LLM tests: none are provided. Running the real client would transmit tender
  descriptions and catalogue candidates externally and was not authorized.

## Independent results

The documented 13 tests were run in a temporary copy of the bundle populated with
the project's actual PDF, catalogue, productivity and parameter files. Provider
variables were blank for the process. Result: **13 passed in 41.59 seconds**.

The deterministic bundle path produced 263 LV rows:

| Status | Count |
|---|---:|
| calculated | 53 |
| supplier_quote_required | 20 |
| assumption_applied | 68 |
| review_required | 84 |
| insufficient_information | 1 |
| non_priceable | 37 |

It selected the expected primary product for all 22 verified examples. The latest
verified production report also selected all 22, so this is no measured product-ID
improvement. The current dirty worktree's production-reference test could not
complete because `P8H078-001` no longer has an exact parser association; that
pre-existing regression was not changed in this audit.
The bundle marked 16 references calculated. Two of those, LV0009 and LV0021, are
kept review-only by production because of source/model-length and quantity-granularity
conflicts. The bundle therefore weakens known safeguards on this benchmark.

The 263-row bundle scope is not directly comparable with the reported 576-row
baseline: the candidate populations and granularity differ. The bundle's claimed
CHF 1,697,469.34 baseline uses its own parser, statuses and copied pricing engine;
it is not evidence that current project pricing remains unchanged.

## Strengths

- Candidate lists are bounded to catalogue IDs.
- Hallucinated product IDs are rejected.
- Supplier packages are prevented from remaining `calculated`.
- Original descriptions are retained beside translated text.
- Stubbed tests exercise LLM wiring without network access.

## Blocking risks

- A valid candidate-list ID can be accepted as `calculated` without a final
  deterministic check of dimensions, geometry, material, fire rating or model.
- `assumption_applied` is a priced status in the bundle, conflicting with current
  accepted-total safety rules.
- Step 2 asks an LLM to emit quantities and dimensions from page text. Prompting is
  not deterministic proof that numbers were preserved.
- LLM extraction sends batches of tender page text externally; matching sends
  descriptions and catalogue candidates.
- Bundle status, row and pricing schemas differ from current API/review contracts.
- The supplied test fixture data is missing, so documented parity is not
  independently reproducible without substituting current project data.

## Integration decision

No production integration is justified. The useful retrieval behavior is already
covered by the project's stricter isolated AI-matching experiment, which validates
critical conflicts and always returns `pricing_authorized=false`. Copying the bundle
provider or matcher would create a parallel implementation without a measured gain.

Recommendation only: human-label difficult review rows, then compare the current
bounded candidate ranker with the bundle ranker on the same labels. Integrate only
if correct top-k retrieval improves without reducing technical-conflict recall.

## Commands and regression state

- Bundle tests in an isolated temporary copy with current project inputs and blank
  provider variables: `python -m pytest tests/test_pipeline.py -q` -> 13 passed.
- Bundle compatibility plus current AI/Phase B2 tests: 25 run, 23 passed, one
  failure and one error. The three new compatibility tests passed.
- Full backend: 127 run, 124 passed, two failures and one error. Remaining issues:
  candidate prompt count 1 versus 3, uppercase dimension `H` parsed as hour, and
  missing exact association for `P8H078-001`.
- Frontend: 16 tests passed across eight files; production build passed.

No live LLM test or other external model call was made. Secret values were never
displayed, logged, copied into source, or written to generated artifacts.
