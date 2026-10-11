# pipeline — Steps 2 & 3

Drop-in modules for the tender pricing pipeline. No Streamlit, no global state:
pass config in, get plain data out.

```
STEP 1  upload & jobs            (your project)
STEP 2  extract_positions()      THIS PACKAGE   Docling front-end + LLM schema mapping
STEP 3  match_positions()        THIS PACKAGE   translate + retrieve + rerank
STEP 4  calc_positions()         engine/pricing.py   unchanged
```

---

## Install

```bash
pip install docling          # required for the Docling front-end
# no SDK needed: the LLM client is stdlib-only and talks the OpenAI-compatible API
```

If Docling is absent, step 2 automatically falls back to the deterministic regex
parser — the pipeline still runs.

---

## Quick start

```python
import json, pandas as pd
from pipeline import extract_positions, match_positions
from pipeline import LLMConfig, ExtractConfig, MatchConfig

catalog      = pd.read_csv("catalog.csv")
pdf_bytes    = open("tender.pdf", "rb").read()

llm = LLMConfig(provider="openai", model="gpt-4o-mini")     # or deepseek / openrouter

# STEP 2 — LV pages only
positions = extract_positions(pdf_bytes, llm_config=llm, config=ExtractConfig())

# STEP 3 — translate + retrieve + rerank
matched = match_positions(positions, catalog, llm_config=llm, config=MatchConfig())
```

### Choosing a provider

All OpenAI-compatible endpoints work — nothing is hard-wired to one vendor.

```python
LLMConfig(provider="openai")       # gpt-4o-mini,      OPENAI_API_KEY
LLMConfig(provider="deepseek")     # deepseek-chat,    DEEPSEEK_API_KEY
LLMConfig(provider="openrouter")   # any model,        OPENROUTER_API_KEY
LLMConfig(provider="custom", base_url="http://localhost:11434/v1",
          model="llama3.1", api_key="ollama")           # local vLLM / Ollama
```

Precedence: explicit argument → provider default → environment variable.

---

## STEP 2 — `extract_positions`

```python
extract_positions(pdf_bytes, llm=None, config=ExtractConfig(),
                  llm_config=None, progress=None) -> list[dict]
```

**Scope: LV pages only.** Component lists (Bauteilliste) are deliberately ignored.

Flow: Docling converts the PDF → pages are classified → LV pages are batched
(`pages_per_call`) → each batch is sent to the LLM, which returns structured
positions → rows are renumbered `P0001…`.

**Falls back** to `engine/parser.py` (LV rows only) when Docling is missing, the LLM
is off, or a call fails. Each row records which path produced it:

| key | meaning |
|---|---|
| `extractor` | `"docling+llm"` or `"regex"` |

`ExtractConfig` fields:

| field | default | meaning |
|---|---|---|
| `use_docling` | `True` | `False` → regex parser only |
| `use_llm` | `True` | `False` → deterministic extraction only |
| `pages_per_call` | `4` | LV pages batched into one LLM call |
| `only_lv_pages` | `True` | the locked scope |
| `docling_ocr` | `False` | `True` for scanned tenders |
| `docling_table_mode` | `"accurate"` | or `"fast"` |

---

## STEP 3 — `match_positions`

```python
match_positions(positions, catalog, llm=None, config=MatchConfig(),
                llm_config=None, progress=None) -> list[dict]
```

Three stages:

1. **TRANSLATE** — descriptions → English (`description_en`). The original is always
   kept. Batch size `translate_batch`.
2. **RETRIEVE** — a `n_candidates` shortlist per position, scored on keyword overlap
   plus size proximity (DN / W×H / airflow).
3. **RERANK** — the LLM picks the best candidate, or answers "none", and returns
   `product_id`, `install_code`, `status`, `confidence`, `reason`.

Then a **deterministic guard** decides what is actually allowed:

| situation | result |
|---|---|
| valid product + confident | `calculated` |
| valid product + nearest size | `assumption_applied` |
| supplier package | `supplier_quote_required` (never `calculated`) |
| product id not in the catalogue | **rejected** → rule-matcher fallback |
| LLM answers "none" | respected → row stays unpriced |
| no product and no quantity | `insufficient_information` |
| LLM unavailable / unparseable | rule-matcher fallback |

Every row records the deciding path: `matcher` = `"llm"` or `"rules"`.

`MatchConfig` fields:

| field | default | meaning |
|---|---|---|
| `translate` | `True` | translate descriptions to English |
| `use_llm` | `True` | `False` → rule matcher only |
| `n_candidates` | `12` | catalogue shortlist per position |
| `batch_size` | `12` | positions per rerank call |
| `translate_batch` | `40` | descriptions per translation call |
| `allow_none` | `True` | the LLM may answer "no match" |

---

## Integration contract

Step 3 output already carries everything step 4 needs. Add the two review columns
your project owns, then hand it straight to the pricing engine:

```python
import numpy as np, pandas as pd
from engine.pricing import SimSettings, calc_positions, project_summary

df = pd.DataFrame(matched)
df["include"] = True                    # reviewer column (your project)
df["custom_unit_cost_chf"] = np.nan     # reviewer override (your project)

sim = SimSettings.from_params(params)
calc = calc_positions(df, catalog, productivity, sim)
summary = project_summary(calc, params, sim)
```

**Position row keys:** `position_id, system, section, source_page, source_kind,
description, description_en, quantity, unit, dn_mm, w_mm, h_mm, l_mm, airflow_m3h,
raw_line, context, extractor`

**Match keys:** `product_id, install_code, status, match_confidence, match_reason,
category, qty_factor, matcher`

---

## Guardrails (enforced in code)

1. **Numbers never come from an LLM.** It chooses and explains; quantities come from
   the document.
2. **Nothing is force-priced.** No defensible match → `review_required`.
3. **Hallucinated product IDs are rejected** against the catalogue before use.
4. **Supplier packages are never `calculated`.**
5. **Every row records which path decided it** (`extractor`, `matcher`).
6. **Responses are cached on disk** (same prompt → same answer, no repeat spend).

---

## Behaviour without an API key

With no key configured, `build_llm()` returns a `StubLLM` and both steps run their
deterministic paths. Useful for CI and for proving the wiring. Pass
`StubLLM([...])` yourself to test the LLM paths with canned replies.

## Parity

On the bundled tender, step 2 + step 3 (rule path) reproduce the locked baseline
**exactly**: 263 positions, CHF **1,697,469.34** cost baseline, 0 of 263 rows
differing from the reference matcher.

```bash
python -m pytest tests/test_pipeline.py -q     # 13 tests
python count_positions.py                      # both scopes side by side
```
