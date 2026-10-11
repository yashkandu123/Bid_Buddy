"""Generate isolated source/overlay renders for PDF alignment validation."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tender_pricing.pdf_overlay import (  # noqa: E402
    eligible_overlay_positions,
    map_price_cells,
    render_pdf_pages,
    write_mapping_json,
    write_overlay_prototype,
)


PAGES = [78, 79, 105, 107, 169]


def main() -> None:
    output_dir = ROOT / "outputs/pdf_overlay_alignment_validation"
    render_dir = output_dir / "renders"
    source_pdf = ROOT / "BKP_244_LV_Lueftung_260804.pdf"
    output_pdf = output_dir / "aligned_overlay_validation.pdf"
    mapping_path = output_dir / "mapping.json"
    rows = json.loads(
        (ROOT / "outputs/phase2_full/priced_positions.json").read_text(encoding="utf-8")
    )
    eligible = eligible_overlay_positions(rows, set(PAGES))
    mappings = map_price_cells(source_pdf, eligible, set(PAGES))
    write_overlay_prototype(
        source_pdf=source_pdf,
        output_pdf=output_pdf,
        mappings=mappings,
        pages=PAGES,
    )
    write_mapping_json(mapping_path, mappings, PAGES)

    if render_dir.exists():
        shutil.rmtree(render_dir)
    render_dir.mkdir(parents=True)
    for page_number in PAGES:
        render_pdf_pages(
            source_pdf,
            render_dir / f"source_page_{page_number:03d}",
            page_number,
            page_number,
        )
    render_pdf_pages(output_pdf, render_dir / "overlay_page", 1, len(PAGES))

    summary = {
        "source_pdf": str(source_pdf.relative_to(ROOT)),
        "output_pdf": str(output_pdf.relative_to(ROOT)),
        "mapping_report": str(mapping_path.relative_to(ROOT)),
        "source_pages": PAGES,
        "eligible_positions": len(eligible),
        "mapped_positions": sum(mapping.placement_status == "mapped" for mapping in mappings),
        "skipped_positions": [
            {
                "lv_id": mapping.lv_id,
                "source_page": mapping.source_page,
                "status": mapping.placement_status,
                "reason": mapping.placement_reason,
            }
            for mapping in mappings
            if mapping.placement_status != "mapped"
        ],
    }
    (output_dir / "validation_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
