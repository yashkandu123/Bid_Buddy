from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tender_pricing.data_loading import load_project_data
from src.tender_pricing.pdf_ingestion import PdfPageText
from src.tender_pricing.position_parser import parse_page_positions
from src.tender_pricing.product_matching import classify_position


def main() -> None:
    data = load_project_data(ROOT)
    catalog = {row["product_id"]: row for row in data["catalog"]}
    productivity = {row["install_code"]: row for row in data["productivity"]}
    results = []
    for reference in data["examples"]:
        source = f"{reference['description']} {reference['unit']} {reference['quantity']}"
        parsed = parse_page_positions(PdfPageText(int(reference["source_page"]), source))
        result = (
            classify_position(parsed[0], catalog, productivity, data["parameters"])
            if parsed
            else {}
        )
        results.append(
            {
                "reference_id": reference["lv_id"],
                "expected_product_id": reference["suggested_product_id"],
                "actual_product_id": result.get("matched_product_id"),
                "expected_status": reference["ground_truth_status"],
                "actual_status": result.get("status"),
                "match_method": result.get("match_method"),
                "conflicts": result.get("conflict_flags", []),
            }
        )
    payload = {
        "dataset": "22 verified English reference descriptions with original quantities and units",
        "positions": len(results),
        "correct_product_matches": sum(
            row["actual_product_id"] == row["expected_product_id"] for row in results
        ),
        "status_counts": dict(Counter(row["actual_status"] for row in results)),
        "false_product_matches": sum(
            row["actual_product_id"] is not None
            and row["actual_product_id"] != row["expected_product_id"]
            for row in results
        ),
        "unmatched": sum(row["actual_product_id"] is None for row in results),
        "results": results,
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
