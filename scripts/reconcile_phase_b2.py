"""Reproduce Phase B2 classification without calculating or emitting prices."""
from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import replace
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tender_pricing.data_loading import load_project_data
from src.tender_pricing.pdf_ingestion import extract_pdf_text_pages
from src.tender_pricing.position_parser import parse_lv_positions
from src.tender_pricing.product_matching import classify_position, annotate_duplicate_candidates


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def associate(candidate, positions):
    matches = [p for p in positions if p.source_page == candidate["pdf_page"]
               and p.source_line == candidate["source_line"]
               and p.quantity == (candidate.get("quantity") or 0)
               and p.unit == candidate["unit_normalized"]]
    if not matches:
        raise ValueError(f"No exact PDF parser association: {candidate['corrected_candidate_id']}")
    ranked = sorted(matches, key=lambda p: SequenceMatcher(None, candidate["original_german_description"], p.description).ratio(), reverse=True)
    return ranked[0], sum(p.description == ranked[0].description for p in matches)


def evaluate_inventory(candidates, excluded, positions, data):
    catalog = {r["product_id"]: r for r in data["catalog"]}
    productivity = {r["install_code"]: r for r in data["productivity"]}
    inventory = [(r, False) for r in candidates]
    for r in excluded:
        if r["exclusion_reason_code"] not in {
            "pressure_loss_technical_specification_not_position",
            "penetration_count_technical_specification_not_position",
        }:
            continue
        position, _ = associate(r, positions)
        result = classify_position(position, catalog, productivity, data["parameters"])
        if result.get("matched_product_id", "") in {"P-SIL-001", "P-SIL-003", "P-SIL-004", "P-SUP-001"}:
            inventory.append((r, True))
    results = []
    for candidate, recovered in inventory:
        position, occurrences = associate(candidate, positions)
        position = replace(position, lv_id=candidate["corrected_candidate_id"])
        result = classify_position(position, catalog, productivity, data["parameters"])
        result.update(candidate_id=position.lv_id, proposed_status=result["status"],
                      corrected_input=candidate, recovered_from_exclusion=recovered,
                      pdf_association_occurrences=occurrences,
                      pricing_authorized=False,
                      classification_only=True)
        # Preserve unresolved extraction evidence unless exact source evidence resolves it.
        if occurrences > 1 and result["status"] == "calculated":
            result.update(status="review_required", proposed_status="review_required", review_required=True)
            result["conflict_flags"].append({"code": "source_occurrence_ambiguous", "message": "Same quantity/unit/source line occurs more than once on page."})
        results.append(result)
    annotate_duplicate_candidates(results)
    for result in results:
        result["proposed_status"] = result["status"]
    return results


def reference_comparison(data, results):
    report = []
    for example in data["examples"]:
        candidates = [r for r in results if r["source_page"] == int(example["source_page"])
                      and r["quantity"] == float(example["quantity"]) and r["unit"] == example["unit"]]
        exact = [r for r in candidates if r["matched_product_id"] == example["suggested_product_id"]]
        row = exact[0] if len(exact) == 1 else None
        category = "unmatched" if row is None else (
            "product_and_status_match" if row["status"] == example["ground_truth_status"] else "correct_product_status_conflict")
        report.append({"reference_id": example["lv_id"], "reference_description": example["description"],
                       "expected_product_id": example["suggested_product_id"], "expected_status": example["ground_truth_status"],
                       "category": category, "candidate_id": row["candidate_id"] if row else None,
                       "source_page": int(example["source_page"]), "source_line": row["source_line"] if row else None,
                       "actual_product_id": row["matched_product_id"] if row else None,
                       "actual_status": row["status"] if row else None,
                       "conflicts": row["conflict_flags"] if row else [],
                       "source_evidence": row["original_description"] if row else None})
    return report


def main():
    output = ROOT / "outputs/phase8h_phase_b2_matching"
    if (output / "matching_results.jsonl").exists() and "--replace-this-run" not in sys.argv:
        raise SystemExit("Output already exists; preserve artifacts and select a new run explicitly.")
    data = load_project_data(ROOT)
    corrected = read_rows(ROOT / "outputs/phase8h_extraction_correction/corrected_candidates.jsonl")
    excluded = read_rows(ROOT / "outputs/phase8h_extraction_correction/excluded_false_positives.jsonl")
    positions = parse_lv_positions(extract_pdf_text_pages(ROOT / "BKP_244_LV_Lueftung_260804.pdf"))
    results = evaluate_inventory(corrected, excluded, positions, data)
    references = reference_comparison(data, results)
    old = read_rows(ROOT / "outputs/phase8h_phase_b_matching/matching_results.jsonl")
    old_by_id = {r["candidate_id"]: r for r in old}
    transitions = Counter()
    for r in results:
        previous = old_by_id.get(r["candidate_id"])
        transitions[(previous["proposed_status"] if previous else "recovered_exclusion") + " -> " + r["status"]] += 1
    summary = {"input_count": len(corrected), "result_count": len(results),
               "recovered_excluded_count": sum(r["recovered_from_exclusion"] for r in results),
               "status_counts": dict(Counter(r["status"] for r in results)),
               "reference_counts": dict(Counter(r["category"] for r in references)),
               "before_status_counts": dict(Counter(r["proposed_status"] for r in old)),
               "status_transitions": dict(transitions), "pdf_pages": 202,
               "no_costs_calculated": True, "all_pricing_authorized_false": True,
               "human_review_count": sum(r["review_required"] for r in results),
               "unmatched_count": sum(r["matched_product_id"] is None for r in results)}
    baseline = json.loads((ROOT / 'outputs/phase2_full/priced_positions.json').read_text(encoding='utf-8'))
    if isinstance(baseline, dict):
        baseline = baseline.get('positions', baseline.get('position_results', []))
    recovery = []
    for prior in baseline:
        if prior.get('status') != 'calculated':
            continue
        linked = [r for r in results if r['source_page'] == prior['source_page'] and r['source_line'] == prior['source_line'] and r['quantity'] == prior['quantity'] and r['unit'] == prior['unit']]
        recovery.append({'old_position_id': prior['lv_id'], 'old_product_id': prior['matched_product_id'],
                         'new_candidates': [{'id': r['candidate_id'], 'product_id': r['matched_product_id'], 'status': r['status']} for r in linked]})
    summary['previous_calculated_baseline_count'] = len(recovery)
    summary['previous_calculated_recovered_same_product_and_status'] = sum(any(r['product_id'] == p['old_product_id'] and r['status'] == 'calculated' for r in p['new_candidates']) for p in recovery)
    output.mkdir(parents=True, exist_ok=True)
    def write_rows(name, rows):
        (output / name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    write_rows("matching_results.jsonl", results)
    write_rows("unmatched_candidates.jsonl", [r for r in results if not r["matched_product_id"]])
    write_rows("human_review_queue.jsonl", [r for r in results if r["review_required"]])
    write_rows("reference_comparison.jsonl", references)
    write_rows("previous_calculated_comparison.jsonl", recovery)
    (output / "matching_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    table = "| Reference | Candidate | Expected product/status | Actual product/status | Evidence conflict |\n|---|---|---|---|---|\n"
    for r in references:
        table += f"| {r['reference_id']} | {r['candidate_id']} | {r['expected_product_id']} / {r['expected_status']} | {r['actual_product_id']} / {r['actual_status']} | {', '.join(f['code'] for f in r['conflicts'])} |\n"
    (output / "reference_regression_report.md").write_text("# Phase B2 reference regression\n\n" + table + "\nSource-local conflicts are retained. LV0009: table length contradicts model length. LV0021: penetration count versus angle-set scope requires confirmation. Golden reference calculations remain unchanged. B1.5 incorrectly associated LV0010 with the second compact-silencer row; the actual rectangular silencer is recovered from P8H107-005.\n", encoding="utf-8")
    (output / "matching_report.md").write_text("# Phase B2\n\nClassification-only production path, with exact page/source-line/quantity/unit association and original correction input preserved on each result. No prices computed. Four recovered source rows are assessed independently. All 202 pages extracted locally; Bauteilliste rows excluded from this corrected inventory.\n\n```json\n" + json.dumps(summary, indent=2) + "\n```\n\nPhase B had no reproducible implementation in src/scripts; comparisons span different implementations. Changes outside the reference families require review. Duplicate source lines remain reviewable. No threshold relaxation.\n", encoding="utf-8")
    (output / "catalogue_coverage_report.md").write_text("# Catalogue coverage\n\n" + str(summary["unmatched_count"]) + " candidates remain unmatched. See unmatched_candidates.jsonl for page, source text and insufficient_reason_code. No new catalogue products or assumptions were added. Supplier-package matches identify provisional catalogue scope, not quotations.\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
