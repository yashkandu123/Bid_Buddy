"""Configuration for the two pipeline steps.

Step 2 (``step2_extract``): Docling front-end + LLM schema mapping — LV pages only.
Step 3 (``step3_match``):   LLM translate + retrieve + rerank matching.

Everything is passed in explicitly (no global state) so these steps drop into
another project as plain importable functions.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, replace

# OpenAI-compatible endpoints. Add your own with provider="custom".
KNOWN_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}
KNOWN_MODELS = {
    "openai": "gpt-4o-mini",
    "deepseek": "deepseek-chat",
    "openrouter": "openai/gpt-4o-mini",
}
KNOWN_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


@dataclass
class LLMConfig:
    """Provider settings. All OpenAI-compatible (OpenAI, DeepSeek, OpenRouter, vLLM, Ollama)."""

    provider: str = "openai"
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    temperature: float = 0.0
    max_tokens: int = 8000
    timeout_s: int = 120
    max_retries: int = 3
    retry_backoff_s: float = 2.0
    cache: bool = True
    cache_dir: str | None = None

    def resolved(self) -> "LLMConfig":
        """Fill model / base_url / api_key from the provider's defaults and environment."""
        base = self.base_url or KNOWN_BASE_URLS.get(self.provider)
        model = self.model or KNOWN_MODELS.get(self.provider)
        key = self.api_key or os.environ.get(KNOWN_KEY_ENV.get(self.provider, "OPENAI_API_KEY"), "")
        cache_dir = self.cache_dir or os.path.join(os.path.expanduser("~"), ".cache", "tender_pipeline")
        return replace(self, base_url=base, model=model, api_key=key, cache_dir=cache_dir)

    @property
    def configured(self) -> bool:
        """True when we have enough to make a real call."""
        r = self.resolved()
        return bool(r.api_key and r.base_url and r.model)


@dataclass
class ExtractConfig:
    """Step 2 settings."""

    use_docling: bool = True          # False -> use the regex parser fallback directly
    pages_per_call: int = 4           # LV pages batched into one LLM call
    use_llm: bool = True              # False -> regex parser only (deterministic)
    only_lv_pages: bool = True        # LOCKED scope: LV pages only
    docling_ocr: bool = False         # True for scanned tenders
    docling_table_mode: str = "accurate"


@dataclass
class MatchConfig:
    """Step 3 settings."""

    translate: bool = True            # translate descriptions to English (any language)
    n_candidates: int = 12            # catalogue shortlist size sent to the LLM
    use_llm: bool = True              # False -> rule matcher only
    batch_size: int = 12              # positions per LLM rerank call
    translate_batch: int = 40         # descriptions per translation call
    allow_none: bool = True           # the LLM may answer "no defensible match"
