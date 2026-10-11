"""Create the fixed, stratified Phase 2B live-LLM evaluation sample."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evaluation/phase2b_coverage/matching_results.jsonl"
OUTPUT = ROOT / "evaluation/phase2b_llm_26/representative_sample.jsonl"

SAMPLE_IDS = (
    # Verified references: six supplier packages and two mandatory review cases.
    "P8H080-003", "P8H106-001", "P8H107-002", "P8H107-005",
    "P8H163-001", "P8H163-002", "P8H169-004", "P8H171-001",
    # Plausible generic catalogue families.
    "P8H082-001", "P8H082-006", "P8H082-007", "P8H162-002",
    # Explicit technical conflicts or unsupported variants.
    "P8H079-002", "P8H085-003", "P8H103-004", "P8H105-004",
    "P8H115-001", "P8H116-001", "P8H142-005", "P8H187-005",
    # Known suspicious candidates caused by cumulative source context.
    "P8H082-003", "P8H103-006", "P8H108-006", "P8H110-003",
    "P8H154-001", "P8H165-006",
)

VERIFIED = {
    "P8H080-003": ("LV0006", "P-SIL-001", "supplier_quote_required"),
    "P8H106-001": ("LV0007", "P-VAV-001", "supplier_quote_required"),
    "P8H107-002": ("LV0009", "P-SIL-002", "uncertain"),
    "P8H107-005": ("LV0010", "P-SIL-003", "supplier_quote_required"),
    "P8H163-001": ("LV0011", "P-SIL-004", "supplier_quote_required"),
    "P8H163-002": ("LV0012", "P-VAV-002", "supplier_quote_required"),
    "P8H169-004": ("LV0018", "P-INS-003", "supplier_quote_required"),
    "P8H171-001": ("LV0021", "P-SUP-001", "uncertain"),
}


def main() -> int:
    rows = [json.loads(line) for line in RESULTS.read_text(encoding="utf-8").splitlines() if line]
    by_id = {row["lv_id"]: row for row in rows}
    missing = sorted(set(SAMPLE_IDS) - set(by_id))
    if missing:
        raise RuntimeError(f"Missing sample rows: {missing}")
    sample = []
    for candidate_id in SAMPLE_IDS:
        row = dict(by_id[candidate_id])
        row["position_id"] = row["lv_id"]
        if candidate_id in VERIFIED:
            reference_id, product_id, priceability = VERIFIED[candidate_id]
            row["label_source"] = "verified_reference_example"
            row["reference_id"] = reference_id
            row["human_labels"] = {
                "confirmed_product_id": product_id,
                "technical_compatibility": (
                    "supplier_package_candidate" if priceability == "supplier_quote_required"
                    else "conflict_requires_review"
                ),
                "priceability": priceability,
                "correction_category": "verified_reference",
                "reviewer_notes": "Ground truth comes from the verified reference files; status safety remains authoritative.",
                "confidence": "high",
            }
        else:
            row["label_source"] = "human_label_required"
            row["human_labels"] = {
                "confirmed_product_id": None,
                "technical_compatibility": None,
                "priceability": None,
                "correction_category": None,
                "reviewer_notes": None,
                "confidence": None,
            }
        sample.append(row)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in sample),
        encoding="utf-8",
    )
    print(f"Wrote {len(sample)} rows to {OUTPUT}")
    print(f"verified labels: {sum(row['label_source'] == 'verified_reference_example' for row in sample)}")
    print(f"human labels required: {sum(row['label_source'] == 'human_label_required' for row in sample)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
