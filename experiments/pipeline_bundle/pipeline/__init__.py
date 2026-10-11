"""Tender pricing pipeline — steps 2 and 3 as drop-in modules.

    from pipeline import extract_positions, match_positions, ExtractConfig, MatchConfig

    positions = extract_positions(pdf_bytes)                 # STEP 2  (Docling + LLM)
    matched   = match_positions(positions, catalog_df)       # STEP 3  (translate + retrieve + rerank)
    calc      = calc_positions(matched_df, ...)              # STEP 4  (existing pricing engine)

Step 2  LV pages only (locked scope). Regex parser kept as fallback.
Step 3  Translation to English + catalogue retrieval + LLM rerank, with
        deterministic guards and a rule-based fallback.

Nothing here imports Streamlit or holds global state — pass config in, get data out.
"""
from .config import ExtractConfig, LLMConfig, MatchConfig
from .llm import (
    CachedLLM,
    LLMError,
    OpenAICompatibleLLM,
    StubLLM,
    build_llm,
    parse_json_response,
)
from .step2_extract import (
    ExtractorError,
    classify_page,
    docling_pages,
    extract_positions,
    regex_positions,
)
from .step3_match import (
    MATCH_COLUMNS,
    PRICED_STATUSES,
    STATUSES,
    catalog_with_sizes,
    match_positions,
    retrieve_candidates,
    translate_descriptions,
)

__version__ = "1.0.0"

__all__ = [
    # config
    "LLMConfig", "ExtractConfig", "MatchConfig",
    # llm
    "build_llm", "StubLLM", "OpenAICompatibleLLM", "CachedLLM", "LLMError", "parse_json_response",
    # step 2
    "extract_positions", "docling_pages", "regex_positions", "classify_page", "ExtractorError",
    # step 3
    "match_positions", "translate_descriptions", "retrieve_candidates", "catalog_with_sizes",
    "STATUSES", "PRICED_STATUSES", "MATCH_COLUMNS",
]
