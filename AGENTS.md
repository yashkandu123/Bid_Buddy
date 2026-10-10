# Repository Instructions for Codex

These instructions apply to every task performed in this repository.

## Required context before acting
Before making changes or running a project workflow, read:
1. `README.md`
2. `PROJECT_RULES.md`
3. `PHASE_STATUS.md`

Then inspect source files, tests, reference data, and prior outputs relevant to the requested task. If a required file is missing, report it; do not silently skip it or invent its contents.

## Mandatory reference examples
For any task involving tender extraction, matching, classification, pricing, or offer output, inspect:
- `example_lv_positions.csv`
- `expected_output_example.json`

These are mandatory references, not optional examples. Determine whether tests exercise the production pipeline or only isolated fixtures. Reconcile known examples individually when relevant, and explain any missing, changed, downgraded, or unmatched example.

## Correctness over counts
- Do not optimize for the number of calculated positions alone.
- Do not lower confidence thresholds globally just to increase coverage.
- Never silently accept conflicting dimensions, geometry, model identifiers, units, product families, or technical attributes.
- Prefer explicit evidence from the candidate's own tender line over inherited context. Context may supplement missing fields only when its association is clear and must never override conflicting local evidence.
- Distinguish extraction, matching, classification, estimation, commercial approval, and PDF export.
- A `calculated` status does not mean a price is commercially confirmed.

## Change and artifact safety
- Keep changes within the user's explicitly requested scope; do not automatically advance phases.
- Do not change pricing formulas, margins, allowances, status precedence, confidence thresholds, or export behavior without explicit authorization.
- Do not call OpenAI or other external AI providers unless explicitly authorized for the current task.
- Never expose or commit API keys, credentials, or secrets.
- Preserve prior phase outputs. Use new output directories for new experiments unless overwriting is explicitly authorized.
- Do not revert, reset, stash, commit, or overwrite existing user changes without explicit authorization.
- Do not initialize Git solely to perform a task unless asked.
- Do not invent missing files, products, prices, productivity rates, source evidence, or test results.

## Testing and reporting
Before changing behavior, inspect implementation and relevant tests. Determine whether tests exercise production behavior or isolated helpers/fixtures.
After changes:
- Run relevant tests and report exact commands and actual outcomes.
- Report files changed, artifacts created, and limitations.
- Separate verified facts from assumptions and unresolved questions.
- Explain candidate-level status changes and conflicts when relevant.
- If required inputs are missing or instructions conflict, stop and explain the blocker.

## End-of-task update
At the end of each task, update `PHASE_STATUS.md` with verified state, completed work, tests actually run, artifact paths, limitations, unresolved issues, and the next recommended action. Label recommendations as recommendations, not authorization. Do not start the next action unless the user explicitly asks.
