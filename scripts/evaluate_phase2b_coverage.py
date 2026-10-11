"""Recompute Phase 2B matching coverage without pricing or replacing prior artifacts."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.reconcile_phase_b2 import evaluate_inventory, read_rows, reference_comparison
from src.tender_pricing.data_loading import load_project_data
from src.tender_pricing.pdf_ingestion import extract_pdf_text_pages
from src.tender_pricing.position_parser import parse_lv_positions


SAMPLE_IDS = {
    "P8H082-006",  # temperature sensor: plausible generic catalogue family
    "P8H082-007",  # differential-pressure sensor: plausible family
    "P8H085-003",  # insulation thickness absent from catalogue
    "P8H103-004",  # buried duct bend with incompatible catalogue construction
    "P8H187-001",  # CAV diameter absent from catalogue
    "P8H187-005",  # manual damper diameter absent from catalogue
}


def main() -> int:
    output_dir = ROOT / "evaluation" / "phase2b_coverage"
    output_dir.mkdir(parents=True, exist_ok=True)
    data = load_project_data(ROOT)
    corrected = read_rows(
        ROOT / "outputs/phase8h_extraction_correction/corrected_candidates.jsonl"
    )
    excluded = read_rows(
        ROOT / "outputs/phase8h_extraction_correction/excluded_false_positives.jsonl"
    )
    prior_results = read_rows(
        ROOT / "outputs/phase8h_phase_b2_matching/matching_results.jsonl"
    )
    reviewed_recovery_ids = {
        row["candidate_id"]
        for row in prior_results
        if row.get("recovered_from_exclusion")
    }
    excluded = [
        row for row in excluded
        if row.get("corrected_candidate_id") in reviewed_recovery_ids
    ]
    positions = parse_lv_positions(
        extract_pdf_text_pages(ROOT / "BKP_244_LV_Lueftung_260804.pdf")
    )
    results = evaluate_inventory(corrected, excluded, positions, data)
    references = reference_comparison(data, results)

    correction_summary = json.loads(
        (ROOT / "outputs/phase8h_extraction_correction/correction_summary.json").read_text(
            encoding="utf-8"
        )
    )
    recovered = sum(bool(row.get("recovered_from_exclusion")) for row in results)
    estimated_distinct = correction_summary["counts"]["estimated_distinct_positions"] + recovered
    status_counts = Counter(row["status"] for row in results)
    matched_count = sum(row.get("matched_product_id") is not None for row in results)
    non_priceable = status_counts.get("non_priceable", 0)
    potentially_priceable = estimated_distinct - non_priceable
    summary = {
        "counting_method": (
            "218 correction-pass estimated distinct source occurrences plus the previously "
            "reviewed recovered exclusions; still not an official LV position count"
        ),
        "raw_upload_row_count_is_not_denominator": 576,
        "corrected_candidate_rows": len(corrected),
        "recovered_exclusions": recovered,
        "classification_rows": len(results),
        "estimated_distinct_positions": estimated_distinct,
        "unresolved_duplicate_or_subitem_rows": sum(
            row.get("distinctness_assessment") == "unresolved_duplicate_or_subitem"
            for row in corrected
        ),
        "estimated_potentially_priceable_positions": potentially_priceable,
        "status_counts": dict(status_counts),
        "matched_catalogue_candidate_count": matched_count,
        "calculated_share_of_estimated_potentially_priceable": round(
            status_counts.get("calculated", 0) / potentially_priceable, 4
        ) if potentially_priceable else None,
        "reference_counts": dict(Counter(row["category"] for row in references)),
        "pricing_authorized": False,
    }
    (output_dir / "coverage_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "matching_results.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in results),
        encoding="utf-8",
    )
    sample = [row for row in results if row["lv_id"] in SAMPLE_IDS]
    if {row["lv_id"] for row in sample} != SAMPLE_IDS:
        missing = sorted(SAMPLE_IDS - {row["lv_id"] for row in sample})
        raise RuntimeError(f"Missing live-evaluation sample rows: {missing}")
    (output_dir / "difficult_sample.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in sample),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
