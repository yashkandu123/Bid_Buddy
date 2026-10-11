from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PDF = ROOT / "BKP_244_LV_Lueftung_260804.pdf"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one bounded Docling PDF diagnostic.")
    parser.add_argument("--page", type=int, default=78, help="One-based source PDF page.")
    parser.add_argument(
        "--mode",
        choices=("native", "layout", "tables"),
        default="native",
        help="native is model-free; layout disables OCR/tables; tables enables table recognition.",
    )
    parser.add_argument(
        "--allow-downloads",
        action="store_true",
        help="Allow model downloads. By default cached models are used offline.",
    )
    parser.add_argument("--output", type=Path, help="Optional JSON result path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.allow_downloads:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    started = time.perf_counter()
    try:
        from pypdf import PdfReader, PdfWriter

        sys.path.insert(0, str(ROOT))
        from src.tender_pricing.pdf_ingestion import extract_docling_pages

        if not SOURCE_PDF.exists():
            raise FileNotFoundError(SOURCE_PDF)
        reader = PdfReader(str(SOURCE_PDF))
        if args.page < 1 or args.page > len(reader.pages):
            raise ValueError(f"Page must be between 1 and {len(reader.pages)}.")

        with tempfile.TemporaryDirectory(prefix=".docling-diagnostic-", dir=ROOT) as temp_dir:
            page_pdf = Path(temp_dir) / f"source-page-{args.page}.pdf"
            writer = PdfWriter()
            writer.add_page(reader.pages[args.page - 1])
            with page_pdf.open("wb") as stream:
                writer.write(stream)

            mode = "native" if args.mode == "native" else "standard"
            pages = extract_docling_pages(
                page_pdf,
                [1],
                mode=mode,
                extract_tables=args.mode == "tables",
            )

        result = {
            "status": "success",
            "source_pdf": SOURCE_PDF.name,
            "source_page": args.page,
            "mode": args.mode,
            "offline": not args.allow_downloads,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "page_count": len(pages),
            "text_characters": sum(len(page.text) for page in pages),
            "table_count": sum(len(page.tables) for page in pages),
            "table_row_count": sum(len(table.rows) for page in pages for table in page.tables),
            "text_preview": pages[0].text[:500] if pages else "",
        }
    except Exception as exc:
        result = {
            "status": "failed",
            "source_pdf": SOURCE_PDF.name,
            "source_page": args.page,
            "mode": args.mode,
            "offline": not args.allow_downloads,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }

    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
