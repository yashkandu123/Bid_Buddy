from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from .calculation_engine import (
    calculate_example_summary,
    calculate_positions,
    calculate_project_cost_breakdown,
    validate_against_reference,
)
from .data_loading import load_project_data


def main() -> int:
    parser = argparse.ArgumentParser(description="Price the verified tender example subset.")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    args = parser.parse_args()

    data = load_project_data(args.project_root)
    positions = calculate_positions(data)
    summary = calculate_example_summary(positions, data["parameters"])
    breakdown = calculate_project_cost_breakdown(positions, data["parameters"])
    validation = validate_against_reference(positions, summary, data["expected"])

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = {
        "schema_version": "1.0",
        "scope": "Verified example subset only; not the full tender.",
        "positions": positions,
        "summary": summary,
        "project_cost_breakdown": breakdown,
        "validation": validation,
    }
    output_path = args.output_dir / "example_pricing_results.json"
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    csv_path = args.output_dir / "example_priced_positions.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(positions[0]))
        writer.writeheader()
        writer.writerows(positions)

    print(f"Wrote {output_path}")
    print(f"Wrote {csv_path}")
    print(json.dumps({"summary": summary, "validation": validation}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

