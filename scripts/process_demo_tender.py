from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.tender_pricing.data_loading import load_project_data
from src.tender_pricing.pdf_ingestion import extract_pdf_text_pages
from src.tender_pricing.position_parser import parse_lv_positions
from src.tender_pricing.product_matching import match_positions


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract and price tender PDF position candidates.")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--pages", nargs="*", type=int, default=None)
    args = parser.parse_args()

    project_root = args.project_root
    data = load_project_data(project_root)
    pages = extract_pdf_text_pages(project_root / "BKP_244_LV_Lueftung_260804.pdf", args.pages)
    positions = parse_lv_positions(pages)
    priced_positions = match_positions(
        positions,
        data["catalog"],
        data["productivity"],
        data["parameters"],
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    extracted_path = args.output_dir / "extracted_positions.json"
    priced_path = args.output_dir / "priced_positions.json"
    extracted_path.write_text(
        json.dumps([position.to_dict() for position in positions], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    priced_path.write_text(json.dumps(priced_positions, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Extracted {len(positions)} position candidates from {len(pages)} pages")
    print(f"Wrote {extracted_path}")
    print(f"Wrote {priced_path}")
    review_count = sum(1 for row in priced_positions if row.get("review_required"))
    print(f"Review-required/provisional rows: {review_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

