"""Revalidate saved live responses after deterministic safety-rule changes."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tender_pricing.ai_matching_experiment import (
    build_position_input,
    evaluate_against_human_labels,
    validate_ai_ranker_output,
)


def main() -> int:
    directory = ROOT / "evaluation/phase2b_llm_26"
    sample = [
        json.loads(line)
        for line in (directory / "representative_sample.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    payload = json.loads((directory / "ai_results_real.json").read_text(encoding="utf-8"))
    sample_by_id = {row["position_id"]: row for row in sample}
    results = []
    for result in payload["results"]:
        position = build_position_input(sample_by_id[result["position_id"]])
        candidates = result["candidates"]
        validated = validate_ai_ranker_output(
            result["ai_result"],
            {row["product_id"] for row in candidates},
            position,
            candidates,
        )
        results.append({**result, "ai_result": validated})

    evaluation = evaluate_against_human_labels(sample, results)
    summary = {
        "record_count": len(results),
        "raw_recommendations": dict(Counter(
            result["ai_result"]["recommendation"] for result in results
        )),
        "safe_decisions": dict(Counter(
            result["ai_result"]["safe_decision"] for result in results
        )),
        "pricing_authorized_count": sum(
            bool(result["ai_result"]["pricing_authorized"]) for result in results
        ),
        "provider_error_count": sum(bool(result.get("provider_error")) for result in results),
        "validation_error_count": sum(bool(result.get("validation_error")) for result in results),
        "evaluation": evaluation,
        "safe_accept_ids": [
            result["position_id"] for result in results
            if result["ai_result"]["safe_decision"] == "accept"
        ],
        "human_label_required_count": sum(
            row.get("label_source") == "human_label_required" for row in sample
        ),
        "additional_api_calls": 0,
    }
    (directory / "revalidated_results.json").write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
