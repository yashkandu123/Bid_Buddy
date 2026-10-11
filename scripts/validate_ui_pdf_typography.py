"""Create a limited typography test PDF, never a commercial tender offer."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tender_pricing.pdf_overlay import (
    eligible_overlay_positions, map_price_cells, write_mapping_json, write_overlay_prototype,
)


def main():
    import pdfplumber

    destination = ROOT / "outputs" / "ui_improvements_pdf_validation"
    destination.mkdir(parents=True, exist_ok=True)
    source = ROOT / "BKP_244_LV_Lueftung_260804.pdf"
    rows = json.loads((ROOT / "outputs" / "phase2_full" / "priced_positions.json").read_text(encoding="utf-8"))
    pages = [78, 79, 105]
    eligible = eligible_overlay_positions(rows, set(pages))
    mappings = map_price_cells(source, eligible, set(pages))
    output = destination / "typography_test_only.pdf"
    write_overlay_prototype(source_pdf=source, output_pdf=output, mappings=mappings, pages=pages)
    write_mapping_json(destination / "mapping.json", mappings, pages)
    with pdfplumber.open(source) as original, pdfplumber.open(output) as rendered:
        for index, page in enumerate(pages):
            original.pages[page - 1].to_image(resolution=108).save(destination / f"source_{page}.png")
            rendered.pages[index].to_image(resolution=108).save(destination / f"priced_{page}.png")
    print(json.dumps({"pdf": str(output), "pages": pages, "mapped": sum(m.placement_status == "mapped" for m in mappings), "skipped": [m.to_dict() for m in mappings if m.placement_status != "mapped"]}, indent=2))


if __name__ == "__main__":
    main()
