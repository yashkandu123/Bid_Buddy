"""Prepare the current full-tender inventory with verified labels where available."""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tender_pricing.data_loading import load_project_data


SOURCE = ROOT / "evaluation/phase2b_coverage/matching_results.jsonl"
OUTPUT = ROOT / "evaluation/phase2b_full_tender/full_inventory_labelled.jsonl"
MANDATORY_REVIEW = {"LV0009", "LV0021"}


def main() -> int:
    rows = [json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines() if line]
    examples = load_project_data(ROOT)["examples"]
    for row in rows:
        row["position_id"] = row["lv_id"]
        row["label_source"] = "human_label_required"
        row["human_labels"] = {
            "confirmed_product_id": None,
            "technical_compatibility": None,
            "priceability": None,
            "correction_category": None,
            "reviewer_notes": None,
            "confidence": None,
        }

    associations = []
    for example in examples:
        candidates = [
            row
            for row in rows
            if row["source_page"] == int(example["source_page"])
            and row["quantity"] == float(example["quantity"])
            and row["unit"] == example["unit"]
            and row.get("matched_product_id") == example["suggested_product_id"]
        ]
        if len(candidates) != 1:
            raise RuntimeError(f"Reference association {example['lv_id']} produced {len(candidates)} rows")
        row = candidates[0]
        uncertain = example["lv_id"] in MANDATORY_REVIEW
        supplier = example["ground_truth_status"] == "supplier_quote_required"
        row["label_source"] = "verified_reference_example"
        row["reference_id"] = example["lv_id"]
        row["human_labels"] = {
            "confirmed_product_id": example["suggested_product_id"],
            "technical_compatibility": (
                "conflict_requires_review"
                if uncertain
                else "supplier_package_candidate" if supplier else "compatible"
            ),
            "priceability": (
                "uncertain"
                if uncertain
                else "supplier_quote_required" if supplier else "priceable_with_existing_catalogue"
            ),
            "correction_category": "verified_reference",
            "reviewer_notes": "Verified reference product; source-local safety status remains authoritative.",
            "confidence": "high",
        }
        associations.append({"reference_id": example["lv_id"], "position_id": row["lv_id"]})

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    print(json.dumps({"rows": len(rows), "verified_labels": len(associations), "associations": associations}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
