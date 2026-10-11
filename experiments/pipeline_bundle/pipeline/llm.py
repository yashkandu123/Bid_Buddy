"""Pluggable LLM layer — OpenAI-compatible, dependency-free.

Works with any OpenAI-compatible endpoint (OpenAI, DeepSeek, OpenRouter, Azure,
vLLM, Ollama's OpenAI shim) using only the standard library, so the module drops
into another project without dragging in a vendor SDK.

Three clients:
    OpenAICompatibleLLM  real HTTP calls
    StubLLM              canned responses (tests / dry runs)
    CachedLLM            wraps any client with an on-disk cache

All clients expose one method:
    complete_json(system, user, tag="") -> parsed JSON (dict or list)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request

from .config import LLMConfig


class LLMError(RuntimeError):
    pass


def parse_json_response(text: str):
    """Pull the first JSON object/array out of a model reply.

    Tolerates ```json fences and prose around the payload.
    """
    if not text:
        raise LLMError("empty response")
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    # first balanced {...} or [...]
    for opener, closer in (("{", "}"), ("[", "]")):
        start = t.find(opener)
        if start == -1:
            continue
        depth, in_str, esc = 0, False, False
        for i in range(start, len(t)):
            ch = t[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(t[start:i + 1])
                    except json.JSONDecodeError:
                        break
    raise LLMError(f"no JSON found in response: {text[:300]!r}")


class StubLLM:
    """Deterministic canned client.

    ``responses`` is a list returned in order; when exhausted the last one repeats.
    Lets the whole pipeline be exercised end-to-end with no API key.
    """

    def __init__(self, responses=None, name="stub"):
        self.responses = list(responses or [])
        self.name = name
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str, tag: str = ""):
        self.calls.append((tag, user))
        if not self.responses:
            return {}
        return self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]


class OpenAICompatibleLLM:
    """Minimal OpenAI-compatible chat client over stdlib HTTP."""

    def __init__(self, config: LLMConfig | None = None, name: str | None = None):
        self.config = (config or LLMConfig()).resolved()
        self.name = name or f"{self.config.provider}:{self.config.model}"
        if not self.config.api_key:
            raise LLMError(
                f"no API key for provider '{self.config.provider}'. "
                f"Set {self.config.provider.upper()}_API_KEY or pass api_key=."
            )
        if not self.config.base_url:
            raise LLMError(f"no base_url for provider '{self.config.provider}'")

    def complete_json(self, system: str, user: str, tag: str = ""):
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.config.model,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
        }
        last_err: Exception | None = None
        for attempt in range(self.config.max_retries):
            try:
                req = urllib.request.Request(
                    url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
                )
                with urllib.request.urlopen(req, timeout=self.config.timeout_s) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                text = body["choices"][0]["message"]["content"]
                return parse_json_response(text)
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:300]
                last_err = LLMError(f"HTTP {e.code}: {detail}")
                if e.code in (400, 401, 403, 404):   # not retryable
                    break
            except Exception as e:                    # noqa: BLE001 - network/parse
                last_err = e
            if attempt < self.config.max_retries - 1:
                time.sleep(self.config.retry_backoff_s * (2 ** attempt))
        raise LLMError(f"LLM call failed ({tag}): {last_err}")


class CachedLLM:
    """On-disk cache wrapper. Same prompt -> same answer, no repeat spend."""

    def __init__(self, inner, cache_dir: str):
        self.inner = inner
        self.cache_dir = cache_dir
        self.name = getattr(inner, "name", "cached")
        os.makedirs(cache_dir, exist_ok=True)

    def _path(self, system: str, user: str) -> str:
        h = hashlib.sha256((system + "\x00" + user).encode("utf-8")).hexdigest()[:32]
        return os.path.join(self.cache_dir, h + ".json")

    def complete_json(self, system: str, user: str, tag: str = ""):
        p = self._path(system, user)
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        out = self.inner.complete_json(system, user, tag=tag)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False)
        os.replace(tmp, p)
        return out


def build_llm(config: LLMConfig | None = None, stub_responses=None):
    """Return a ready client: StubLLM when responses are given, else the real HTTP client
    (wrapped in the cache when enabled). Falls back to StubLLM when no key is configured.
    """
    cfg = (config or LLMConfig()).resolved()
    if stub_responses is not None:
        return StubLLM(stub_responses)
    if not cfg.api_key:
        return StubLLM([], name="stub-no-key")
    client = OpenAICompatibleLLM(cfg)
    return CachedLLM(client, cfg.cache_dir) if cfg.cache else client
