from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


DECISIONS = {"accept", "review", "abstain"}
CRITICAL_CONFLICT_CODES = {
    "ambiguous_dimension_unit",
    "diameter_mismatch",
    "dimension_mismatch",
    "fire_rating_mismatch",
    "geometry_mismatch",
}


class AIMatchingError(RuntimeError):
    pass


class AIMatchingValidationError(ValueError):
    pass


@dataclass(frozen=True)
class UsageEstimate:
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_chf: float | None = None
    measurement_note: str = "unsupported_by_provider"


class AIMatchingProvider(Protocol):
    name: str

    def rank_candidates(
        self,
        position: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        ...


def load_project_env(project_root: Path, filename: str = ".env") -> bool:
    env_path = project_root / filename
    if not env_path.exists():
        return False
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or not _VALID_ENV_KEY_RE.match(key):
            continue
        os.environ.setdefault(key, _strip_env_value(value.strip()))
    return True


class FakeAIProvider:
    """Deterministic test/dry-run provider. It never calls a network service."""

    name = "fake"

    def __init__(
        self,
        decision: str = "review",
        recommended_product_id: str | None = None,
        fail: bool = False,
    ) -> None:
        self.decision = decision
        self.recommended_product_id = recommended_product_id
        self.fail = fail

    def rank_candidates(
        self,
        position: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if self.fail:
            raise AIMatchingError("fake provider failure")
        first_candidate_id = candidates[0]["product_id"] if candidates else None
        recommended_product_id = self.recommended_product_id
        if recommended_product_id is None and self.decision == "accept":
            recommended_product_id = first_candidate_id
        ranked_candidates = []
        for index, candidate in enumerate(candidates[:3]):
            ranked_candidates.append(
                {
                    "product_id": candidate["product_id"],
                    "confidence": max(0.1, 0.7 - index * 0.1),
                    "evidence": [
                        "Fake provider ranked only supplied catalogue candidates.",
                    ],
                    "technical_mismatches": [],
                    "missing_evidence": [],
                }
            )
        return {
            "lv_id": position["position_id"],
            "ranked_candidates": ranked_candidates,
            "ambiguity": ["fake provider output is for harness validation only"],
            "recommendation": self.decision,
            "recommended_product_id": recommended_product_id if self.decision == "accept" else None,
            "rationale": "Deterministic fake response; no model call was made.",
            "usage": {
                "input_tokens": None,
                "output_tokens": None,
                "estimated_cost_chf": None,
                "measurement_note": "fake_provider_no_api_usage",
            },
        }


class OpenAIResponsesProvider:
    """Optional real provider. Disabled unless explicitly selected and enabled."""

    name = "openai_responses"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        max_output_tokens: int | None = None,
        enabled: bool | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model or os.getenv("TENDER_AI_MODEL", "gpt-4.1-mini")
        self.base_url = (base_url or os.getenv("TENDER_AI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.timeout_seconds = float(timeout_seconds or os.getenv("TENDER_AI_TIMEOUT_SECONDS", "30"))
        self.max_retries = int(max_retries if max_retries is not None else os.getenv("TENDER_AI_MAX_RETRIES", "1"))
        self.max_output_tokens = int(
            max_output_tokens if max_output_tokens is not None else os.getenv("TENDER_AI_MAX_OUTPUT_TOKENS", "1200")
        )
        env_enabled = os.getenv("TENDER_AI_ENABLE_REAL_PROVIDER", "").strip().lower() == "true"
        self.enabled = env_enabled if enabled is None else enabled

    def rank_candidates(
        self,
        position: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not self.enabled:
            raise AIMatchingError("real provider is disabled; set TENDER_AI_ENABLE_REAL_PROVIDER=true to opt in")
        if not self.api_key:
            raise AIMatchingError("OPENAI_API_KEY is required for the real provider")
        if not candidates:
            return _abstain_without_candidates(position)
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise AIMatchingError("httpx is required for the real provider") from exc

        payload = {
            "model": self.model,
            "input": [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "You rank HVAC catalogue candidates for estimator review. "
                                "Use only supplied product IDs. Do not invent products, prices, "
                                "technical facts, or pricing decisions."
                            ),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": json.dumps(
                                build_ai_matching_prompt_case(position, candidates),
                                ensure_ascii=False,
                                sort_keys=True,
                            ),
                        }
                    ],
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "catalogue_match_ranking",
                    "strict": True,
                    "schema": AI_MATCHING_RESPONSE_SCHEMA,
                }
            },
            "max_output_tokens": self.max_output_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        last_error: str | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = httpx.post(
                    f"{self.base_url}/responses",
                    headers=headers,
                    json=payload,
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                return _parse_openai_response(position["position_id"], response.json())
            except Exception as exc:  # pragma: no cover - tests use fake transport helper
                last_error = str(exc)
                if attempt >= self.max_retries:
                    break
        raise AIMatchingError(f"real provider request failed: {last_error}")


AI_MATCHING_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "ranked_candidates",
        "ambiguity",
        "recommendation",
        "recommended_product_id",
        "rationale",
    ],
    "properties": {
        "ranked_candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "product_id",
                    "confidence",
                    "evidence",
                    "technical_mismatches",
                    "missing_evidence",
                ],
                "properties": {
                    "product_id": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "technical_mismatches": {"type": "array", "items": {"type": "string"}},
                    "missing_evidence": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "ambiguity": {"type": "array", "items": {"type": "string"}},
        "recommendation": {"type": "string", "enum": sorted(DECISIONS)},
        "recommended_product_id": {"type": ["string", "null"]},
        "rationale": {"type": "string"},
    },
}


def create_provider(name: str, fake_decision: str = "review") -> AIMatchingProvider:
    if name == "fake":
        return FakeAIProvider(decision=fake_decision)
    if name == "openai":
        return OpenAIResponsesProvider()
    raise ValueError(f"Unsupported provider: {name}")


def build_position_input(record: dict[str, Any]) -> dict[str, Any]:
    machine = record.get("machine_values", record)
    return {
        "position_id": record.get("position_id") or machine.get("lv_id"),
        "source_page": record.get("source", {}).get("source_page", machine.get("source_page")),
        "source_language": record.get("source", {}).get("source_language", machine.get("source_language")),
        "original_german_description": machine.get("original_description") or record.get("original_german_description"),
        "source_line": machine.get("source_line"),
        "quantity": machine.get("quantity"),
        "unit": machine.get("unit"),
        "technical_attributes": machine.get("technical_attributes", {}),
        "current_status": machine.get("current_status") or machine.get("status"),
        "deterministic_match": {
            "matched_product_id": machine.get("matched_product_id"),
            "match_method": machine.get("match_method"),
            "match_confidence": machine.get("match_confidence"),
            "match_reason": machine.get("match_reason"),
            "conflict_flags": machine.get("conflict_flags", []),
            "insufficient_reason_code": machine.get("insufficient_reason_code"),
            "classification_reason_code": machine.get("classification_reason_code"),
        },
    }


def retrieve_catalogue_candidates(
    position: dict[str, Any],
    catalog: list[dict[str, str]],
    max_candidates: int = 8,
) -> list[dict[str, Any]]:
    if max_candidates <= 0:
        raise ValueError("max_candidates must be positive")

    deterministic_id = position.get("deterministic_match", {}).get("matched_product_id")
    scored: list[tuple[int, str, dict[str, Any]]] = []
    position_text = _normalise(
        " ".join(
            str(part or "")
            for part in (
                position.get("original_german_description"),
                position.get("source_line"),
                _attributes_text(position.get("technical_attributes", {})),
            )
        )
    )
    position_unit = position.get("unit")

    for row in catalog:
        candidate = _catalogue_candidate(row)
        score = 0
        if row["product_id"] == deterministic_id:
            score += 100
        if position_unit and row.get("unit") == position_unit:
            score += 20
        score += _token_score(position_text, _normalise(" ".join(candidate_text_parts(candidate))))
        score += _technical_score(position, candidate)
        if row.get("unit") != position_unit and row["product_id"] != deterministic_id:
            score -= 10
        scored.append((score, row["product_id"], candidate))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [candidate for score, _product_id, candidate in scored[:max_candidates] if score > 0]


def build_ai_matching_prompt_case(
    position: dict[str, Any],
    catalogue_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "task": "Rank only the supplied catalogue candidates for estimator review. Do not invent products or prices.",
        "position": position,
        "catalogue_candidates": catalogue_candidates,
        "required_output_schema": {
            "ranked_candidates": [
                {
                    "product_id": "catalogue product id from supplied candidates only",
                    "confidence": "0.0 to 1.0",
                    "evidence": ["tender and catalogue evidence"],
                    "technical_mismatches": ["technical mismatches"],
                    "missing_evidence": ["missing information"],
                }
            ],
            "ambiguity": ["ambiguity notes"],
            "recommendation": "accept|review|abstain",
            "recommended_product_id": "required only for accept",
            "rationale": "short reason",
        },
    }


def validate_ai_ranker_output(
    output: dict[str, Any],
    allowed_product_ids: set[str],
    position: dict[str, Any] | None = None,
    candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    decision = output.get("recommendation")
    if decision not in DECISIONS:
        raise AIMatchingValidationError(f"Invalid recommendation: {decision!r}")

    ranked_candidates = output.get("ranked_candidates")
    if not isinstance(ranked_candidates, list):
        raise AIMatchingValidationError("ranked_candidates must be a list")

    for candidate in ranked_candidates:
        product_id = candidate.get("product_id")
        if product_id not in allowed_product_ids:
            raise AIMatchingValidationError(f"AI output referenced unknown product_id: {product_id!r}")

    recommended_product_id = output.get("recommended_product_id")
    if decision == "accept":
        if recommended_product_id not in allowed_product_ids:
            raise AIMatchingValidationError(
                f"accepted recommendation must reference a supplied product_id: {recommended_product_id!r}"
            )
    elif recommended_product_id is not None:
        raise AIMatchingValidationError("recommended_product_id must be null unless recommendation is accept")

    validation_flags = _validation_flags(output, position, candidates)
    safe_decision = "review" if _has_critical_flags(validation_flags) and decision == "accept" else decision
    return {
        "lv_id": output.get("lv_id"),
        "ranked_candidates": ranked_candidates,
        "ambiguity": output.get("ambiguity", []),
        "recommendation": decision,
        "recommended_product_id": recommended_product_id,
        "rationale": output.get("rationale", ""),
        "usage": output.get("usage", UsageEstimate().__dict__),
        "validation_flags": validation_flags,
        "safe_decision": safe_decision,
        "pricing_authorized": False,
    }


def run_ai_matching_case(
    position: dict[str, Any],
    catalog: list[dict[str, str]],
    provider: AIMatchingProvider,
    max_candidates: int = 8,
) -> dict[str, Any]:
    candidates = retrieve_catalogue_candidates(position, catalog, max_candidates=max_candidates)
    started = time.perf_counter()
    try:
        raw_output = provider.rank_candidates(position, candidates)
        provider_error = None
    except Exception as exc:
        raw_output = None
        provider_error = str(exc)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)

    result: dict[str, Any] = {
        "position_id": position["position_id"],
        "provider": provider.name,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "latency_ms": elapsed_ms,
        "provider_error": provider_error,
        "validation_error": None,
        "ai_result": None,
        "evaluation_ready": False,
    }
    if provider_error:
        return result

    allowed_ids = {candidate["product_id"] for candidate in candidates}
    try:
        result["ai_result"] = validate_ai_ranker_output(raw_output or {}, allowed_ids, position, candidates)
    except AIMatchingValidationError as exc:
        result["validation_error"] = str(exc)
    return result


def run_experiment(
    sample_records: list[dict[str, Any]],
    catalog: list[dict[str, str]],
    provider: AIMatchingProvider,
    max_candidates: int = 8,
    max_positions: int | None = None,
) -> dict[str, Any]:
    selected_records = sample_records[:max_positions] if max_positions is not None else sample_records
    results = [
        run_ai_matching_case(build_position_input(record), catalog, provider, max_candidates=max_candidates)
        for record in selected_records
    ]
    evaluation = evaluate_against_human_labels(selected_records, results)
    return {
        "experiment": "phase6_ai_matching",
        "provider": provider.name,
        "record_count": len(results),
        "max_positions": max_positions,
        "max_candidates": max_candidates,
        "results": results,
        "evaluation": evaluation,
    }


def evaluate_against_human_labels(
    sample_records: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    labelled: list[tuple[dict[str, Any], dict[str, Any]]] = []
    results_by_id = {result["position_id"]: result for result in results}
    for record in sample_records:
        labels = record.get("human_labels", {})
        if _has_human_label(labels):
            position_id = record.get("position_id") or record.get("machine_values", {}).get("lv_id")
            labelled.append((record, results_by_id[position_id]))

    if not labelled:
        return {
            "status": "blocked_missing_human_labels",
            "message": "No human-labelled rows are available; accuracy metrics were not computed.",
            "labelled_count": 0,
        }

    top1_correct = 0
    unsafe_accepts = 0
    abstain_matches = 0
    abstain_total = 0
    for record, result in labelled:
        labels = record["human_labels"]
        ai_result = result.get("ai_result") or {}
        accepted_id = labels.get("confirmed_product_id")
        if accepted_id and ai_result.get("recommended_product_id") == accepted_id:
            top1_correct += 1
        if ai_result.get("recommendation") == "accept" and labels.get("priceability") != "priceable_with_existing_catalogue":
            unsafe_accepts += 1
        if ai_result.get("recommendation") == "abstain":
            abstain_total += 1
            if labels.get("priceability") in {"priceable_needs_new_catalogue_item", "non_priceable", "uncertain"}:
                abstain_matches += 1

    return {
        "status": "evaluated",
        "labelled_count": len(labelled),
        "top1_accuracy": top1_correct / len(labelled),
        "unsafe_accept_rate": unsafe_accepts / len(labelled),
        "abstention_precision": None if abstain_total == 0 else abstain_matches / abstain_total,
    }


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_openai_response(position_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    text = payload.get("output_text")
    if text is None:
        text = _extract_output_text(payload)
    if not text:
        raise AIMatchingError("real provider response did not contain output_text")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AIMatchingError("real provider returned non-JSON output") from exc

    usage = payload.get("usage") or {}
    parsed.setdefault("lv_id", position_id)
    parsed["usage"] = {
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "estimated_cost_chf": None,
        "measurement_note": "token_usage_reported_cost_not_available" if usage else "usage_not_reported_by_provider",
    }
    return parsed


def _extract_output_text(payload: dict[str, Any]) -> str | None:
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                return content["text"]
    return None


def _abstain_without_candidates(position: dict[str, Any]) -> dict[str, Any]:
    return {
        "lv_id": position["position_id"],
        "ranked_candidates": [],
        "ambiguity": ["No catalogue candidates were supplied."],
        "recommendation": "abstain",
        "recommended_product_id": None,
        "rationale": "No bounded catalogue candidate set was available.",
        "usage": UsageEstimate().__dict__,
    }


def _catalogue_candidate(row: dict[str, str]) -> dict[str, Any]:
    return {
        "product_id": row["product_id"],
        "category": row["category"],
        "subcategory": row["subcategory"],
        "manufacturer": row["manufacturer"],
        "model": row["model"],
        "description": row["description"],
        "unit": row["unit"],
        "install_code": row["install_code"],
        "source_type": row["source_type"],
        "supplier_quote_required": row["supplier_quote_required"].strip().lower() == "true",
    }


def candidate_text_parts(candidate: dict[str, Any]) -> list[str]:
    return [
        str(candidate.get("category", "")),
        str(candidate.get("subcategory", "")),
        str(candidate.get("model", "")),
        str(candidate.get("description", "")),
    ]


def _validation_flags(
    output: dict[str, Any],
    position: dict[str, Any] | None,
    candidates: list[dict[str, Any]] | None,
) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []
    if not position:
        return flags
    machine_flags = position.get("deterministic_match", {}).get("conflict_flags", [])
    for flag in machine_flags:
        code = flag.get("code") if isinstance(flag, dict) else str(flag)
        if code in CRITICAL_CONFLICT_CODES:
            flags.append({"code": code, "message": "Existing deterministic conflict requires review."})
    attrs = position.get("technical_attributes", {})
    if attrs.get("ambiguous_dimensions"):
        flags.append(
            {
                "code": "ambiguous_dimension_unit",
                "message": "Position contains dimensions without supported source units.",
            }
        )

    recommended_id = output.get("recommended_product_id")
    candidate = next((item for item in candidates or [] if item["product_id"] == recommended_id), None)
    if candidate:
        flags.extend(_candidate_technical_flags(position, candidate))
    return _dedupe_flags(flags)


def _candidate_technical_flags(position: dict[str, Any], candidate: dict[str, Any]) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []
    attrs = position.get("technical_attributes", {})
    candidate_text = _normalise(" ".join(candidate_text_parts(candidate)))
    position_diameters = [
        float(item["value_mm"])
        for item in attrs.get("diameters", [])
        if isinstance(item, dict) and "value_mm" in item
    ]
    candidate_diameters = _diameters_mm(candidate_text)
    if position_diameters and candidate_diameters and not _any_close(position_diameters, candidate_diameters):
        flags.append({"code": "diameter_mismatch", "message": "Recommended product diameter conflicts with tender."})

    position_dimensions = [
        tuple(float(value) for value in item["values_mm"])
        for item in attrs.get("dimensions", [])
        if isinstance(item, dict) and "values_mm" in item
    ]
    candidate_dimensions = _dimensions_mm(candidate_text)
    if position_diameters and candidate_dimensions and not candidate_diameters:
        flags.append({"code": "geometry_mismatch", "message": "Round tender evidence conflicts with rectangular candidate."})
    if position_dimensions and candidate_dimensions and not _any_dimension_match(position_dimensions, candidate_dimensions):
        flags.append({"code": "dimension_mismatch", "message": "Recommended product dimensions conflict with tender."})

    position_fire = {_normalise_fire(value) for value in attrs.get("fire_ratings", [])}
    candidate_fire = {_normalise_fire(value) for value in re.findall(r"\bEI\s*-?\s*\d+(?:-S)?\b", candidate_text, re.I)}
    if position_fire and candidate_fire and position_fire.isdisjoint(candidate_fire):
        flags.append({"code": "fire_rating_mismatch", "message": "Recommended product fire rating conflicts with tender."})
    return flags


def _has_critical_flags(flags: list[dict[str, str]]) -> bool:
    return any(flag.get("code") in CRITICAL_CONFLICT_CODES for flag in flags)


def _dedupe_flags(flags: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, str]] = []
    for flag in flags:
        key = (flag["code"], flag["message"])
        if key not in seen:
            seen.add(key)
            result.append(flag)
    return result


def _has_human_label(labels: dict[str, Any]) -> bool:
    return any(
        labels.get(key)
        for key in (
            "confirmed_product_id",
            "technical_compatibility",
            "priceability",
            "correction_category",
            "confidence",
        )
    ) or bool(labels.get("reviewer_notes"))


def _attributes_text(attrs: dict[str, Any]) -> str:
    return json.dumps(attrs, ensure_ascii=False, sort_keys=True)


def _normalise(value: str) -> str:
    value = value.lower()
    replacements = {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
        "ø": "oe",
        "�": "oe",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    return re.sub(r"[^a-z0-9.]+", " ", value)


def _token_score(left: str, right: str) -> int:
    left_tokens = {token for token in left.split() if len(token) > 2}
    right_tokens = {token for token in right.split() if len(token) > 2}
    return len(left_tokens & right_tokens)


def _technical_score(position: dict[str, Any], candidate: dict[str, Any]) -> int:
    score = 0
    attrs = position.get("technical_attributes", {})
    text = _normalise(" ".join(candidate_text_parts(candidate)))
    for diameter in attrs.get("diameters", []):
        value = str(int(float(diameter.get("value_mm", 0)))) if isinstance(diameter, dict) else ""
        if value and value in text:
            score += 10
    for dimension in attrs.get("dimensions", []):
        if not isinstance(dimension, dict):
            continue
        values = [str(int(float(value))) for value in dimension.get("values_mm", [])]
        if values and all(value in text for value in values):
            score += 12
    for rating in attrs.get("fire_ratings", []):
        if _normalise_fire(str(rating)).lower() in text.replace(" ", ""):
            score += 8
    return score


def _diameters_mm(text: str) -> list[float]:
    values: set[float] = set()
    for match in re.finditer(r"\bdn\s*(\d+(?:\.\d+)?)\b", text):
        values.add(float(match.group(1)))
    for match in re.finditer(r"\b(?:dv [za]|fd ei90|fs c|sp|md|vav|cav)[ -](\d{2,4})(?:\b|x)", text):
        values.add(float(match.group(1)))
    return sorted(values)


def _dimensions_mm(text: str) -> list[tuple[float, ...]]:
    result: list[tuple[float, ...]] = []
    for match in re.finditer(r"\b(\d{2,4})x(\d{2,4})(?:x(\d{2,4}))?\b", text):
        values = [float(match.group(1)), float(match.group(2))]
        if match.group(3):
            values.append(float(match.group(3)))
        result.append(tuple(values))
    return result


def _any_close(left: list[float], right: list[float], tolerance: float = 1.0) -> bool:
    return any(abs(left_value - right_value) <= tolerance for left_value in left for right_value in right)


def _any_dimension_match(
    left_dimensions: list[tuple[float, ...]],
    right_dimensions: list[tuple[float, ...]],
    tolerance: float = 2.0,
) -> bool:
    for left in left_dimensions:
        for right in right_dimensions:
            if len(left) != len(right):
                continue
            if all(abs(a - b) <= tolerance for a, b in zip(left, right)):
                return True
            if all(abs(a - b) <= tolerance for a, b in zip(sorted(left), sorted(right))):
                return True
    return False


def _normalise_fire(value: str) -> str:
    return value.upper().replace(" ", "").replace("-", "")


_VALID_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _strip_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
