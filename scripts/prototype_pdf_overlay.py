from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.tender_pricing.pdf_overlay import (
    eligible_overlay_positions,
    map_price_cells,
    render_pdf_pages,
    write_mapping_json,
    write_overlay_prototype,
)


DEFAULT_PAGES = [78, 79, 105, 107, 169]


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a limited original-PDF price-overlay prototype.")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--pages", type=int, nargs="*", default=DEFAULT_PAGES)
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    source_pdf = project_root / "BKP_244_LV_Lueftung_260804.pdf"
    priced_positions = project_root / "outputs" / "phase2_full" / "priced_positions.json"
    output_dir = project_root / "outputs" / "phase8e_overlay"
    output_pdf = output_dir / "prototype_price_overlay_pages_78_79_105_107_169.pdf"
    mapping_json = output_dir / "prototype_price_overlay_mapping.json"
    render_dir = output_dir / "renders"

    rows = json.loads(priced_positions.read_text(encoding="utf-8"))
    pages = sorted(set(args.pages))
    eligible = eligible_overlay_positions(rows, set(pages))
    mappings = map_price_cells(source_pdf, eligible, set(pages))
    write_overlay_prototype(source_pdf=source_pdf, output_pdf=output_pdf, mappings=mappings, pages=pages)
    write_mapping_json(mapping_json, mappings, pages)

    if render_dir.exists():
        shutil.rmtree(render_dir)
    render_dir.mkdir(parents=True, exist_ok=True)
    source_renders: list[str] = []
    for page in pages:
        rendered = render_pdf_pages(source_pdf, render_dir / f"source_page_{page:03d}", page, page)
        source_renders.extend(str(path.relative_to(project_root)) for path in rendered)
    prototype_renders = render_pdf_pages(output_pdf, render_dir / "prototype_page", 1, len(pages))

    mapped = [mapping for mapping in mappings if mapping.placement_status == "mapped"]
    print(json.dumps(
        {
            "output_pdf": str(output_pdf.relative_to(project_root)),
            "mapping_json": str(mapping_json.relative_to(project_root)),
            "source_renders": source_renders,
            "prototype_renders": [str(path.relative_to(project_root)) for path in prototype_renders],
            "pages": pages,
            "eligible_positions": len(eligible),
            "mapped_positions": len(mapped),
            "unmapped_positions": len(mappings) - len(mapped),
            "unmapped": [
                {
                    "lv_id": mapping.lv_id,
                    "source_page": mapping.source_page,
                    "status": mapping.placement_status,
                    "reason": mapping.placement_reason,
                }
                for mapping in mappings
                if mapping.placement_status != "mapped"
            ],
        },
        indent=2,
    ))


if __name__ == "__main__":
    main()
