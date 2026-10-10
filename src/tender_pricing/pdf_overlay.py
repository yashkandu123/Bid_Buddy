from __future__ import annotations

import io
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .calculation_engine import money


PROTOTYPE_SCHEMA_VERSION = "phase8e.pdf_overlay_prototype.v1"
EXPORT_SCHEMA_VERSION = "phase8f.pdf_overlay_export.v1"
PRICEABLE_OVERLAY_STATUS = {"calculated"}
DEFAULT_UNIT_PRICE_LEFT_X = 440.2
DEFAULT_UNIT_PRICE_RIGHT_X = 488.3
DEFAULT_TOTAL_PRICE_LEFT_X = 488.3
DEFAULT_TOTAL_PRICE_RIGHT_X = 562.0
PRICE_CELL_INNER_MARGIN = 5.0
TEXT_SIZE = 7.2
MIN_TEXT_SIZE = 6.4
LINE_MATCH_TOLERANCE = 3.0


@dataclass(frozen=True)
class LineBox:
    text: str
    x0: float
    top: float
    x1: float
    bottom: float


@dataclass(frozen=True)
class PriceColumnGeometry:
    unit_price_left_x: float
    unit_price_right_x: float
    total_price_left_x: float
    total_price_right_x: float


@dataclass(frozen=True)
class PriceCellMapping:
    lv_id: str
    source_page: int
    source_line: str
    status: str
    quantity: float
    unit: str
    unit_price_chf: float | None
    position_total_chf: float | None
    line_bbox: dict[str, float] | None
    unit_price_right_x: float | None
    total_price_right_x: float | None
    unit_price_cell_bbox: dict[str, float] | None
    total_price_cell_bbox: dict[str, float] | None
    unit_price_text_bbox: dict[str, float] | None
    total_price_text_bbox: dict[str, float] | None
    font_size: float | None
    baseline_y: float | None
    placement_status: str
    placement_reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def eligible_overlay_positions(positions: list[dict[str, Any]], pages: set[int]) -> list[dict[str, Any]]:
    eligible = []
    for row in positions:
        if int(row.get("source_page", -1)) not in pages:
            continue
        if row.get("status") not in PRICEABLE_OVERLAY_STATUS:
            continue
        if row.get("supplier_quote_required"):
            continue
        if row.get("pricing_authorized") is False:
            continue
        if not _has_accepted_price(row):
            continue
        eligible.append(row)
    return eligible


def map_price_cells(
    pdf_path: Path,
    positions: list[dict[str, Any]],
    pages: set[int],
) -> list[PriceCellMapping]:
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PDF overlay mapping requires pdfplumber.") from exc

    mappings: list[PriceCellMapping] = []
    positions_by_page: dict[int, list[dict[str, Any]]] = {}
    for row in positions:
        positions_by_page.setdefault(int(row["source_page"]), []).append(row)

    with pdfplumber.open(pdf_path) as document:
        for page_number in sorted(pages):
            page = document.pages[page_number - 1]
            lines = extract_line_boxes(page)
            geometry = detect_price_column_geometry(page)
            for row in positions_by_page.get(page_number, []):
                mappings.append(_map_position(row, lines, float(page.height), geometry))
    return mappings


def detect_price_column_geometry(page: Any) -> PriceColumnGeometry:
    verticals = []
    for edge in getattr(page, "edges", []):
        if edge.get("orientation") != "v":
            continue
        if float(edge.get("height", 0)) < float(page.height) * 0.6:
            continue
        x = round(float(edge["x0"]), 1)
        if x >= 400:
            verticals.append(x)
    unique = _cluster_x_positions(verticals)
    if len(unique) >= 3:
        # Standard tender table: mass amount, unit-price, amount columns.
        return PriceColumnGeometry(
            unit_price_left_x=unique[-3],
            unit_price_right_x=unique[-2],
            total_price_left_x=unique[-2],
            total_price_right_x=unique[-1],
        )
    return PriceColumnGeometry(
        unit_price_left_x=DEFAULT_UNIT_PRICE_LEFT_X,
        unit_price_right_x=DEFAULT_UNIT_PRICE_RIGHT_X,
        total_price_left_x=DEFAULT_TOTAL_PRICE_LEFT_X,
        total_price_right_x=DEFAULT_TOTAL_PRICE_RIGHT_X,
    )


def _cluster_x_positions(values: list[float], tolerance: float = 0.8) -> list[float]:
    clustered: list[list[float]] = []
    for value in sorted(values):
        if clustered and abs(value - (sum(clustered[-1]) / len(clustered[-1]))) <= tolerance:
            clustered[-1].append(value)
        else:
            clustered.append([value])
    return [round(sum(group) / len(group), 2) for group in clustered]


def extract_line_boxes(page: Any) -> list[LineBox]:
    words = page.extract_words(x_tolerance=1, y_tolerance=3, keep_blank_chars=False) or []
    sorted_words = sorted(words, key=lambda word: (float(word["top"]), float(word["x0"])))
    groups: list[list[dict[str, Any]]] = []
    for word in sorted_words:
        center = (float(word["top"]) + float(word["bottom"])) / 2
        for group in reversed(groups[-4:]):
            group_center = sum((float(item["top"]) + float(item["bottom"])) / 2 for item in group) / len(group)
            if abs(center - group_center) <= LINE_MATCH_TOLERANCE:
                group.append(word)
                break
        else:
            groups.append([word])

    lines: list[LineBox] = []
    for group in groups:
        ordered = sorted(group, key=lambda word: float(word["x0"]))
        lines.append(
            LineBox(
                text=" ".join(str(word["text"]) for word in ordered),
                x0=min(float(word["x0"]) for word in ordered),
                top=min(float(word["top"]) for word in ordered),
                x1=max(float(word["x1"]) for word in ordered),
                bottom=max(float(word["bottom"]) for word in ordered),
            )
        )
    return lines


def write_overlay_prototype(
    *,
    source_pdf: Path,
    output_pdf: Path,
    mappings: list[PriceCellMapping],
    pages: list[int],
) -> None:
    try:
        from pypdf import PdfReader, PdfWriter
        from reportlab.pdfgen import canvas
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PDF overlay writing requires pypdf and reportlab.") from exc

    reader = PdfReader(str(source_pdf))
    writer = PdfWriter()
    mappings_by_page: dict[int, list[PriceCellMapping]] = {}
    for mapping in mappings:
        if mapping.placement_status == "mapped":
            mappings_by_page.setdefault(mapping.source_page, []).append(mapping)

    for page_number in pages:
        page = reader.pages[page_number - 1]
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        overlay_buffer = io.BytesIO()
        overlay = canvas.Canvas(overlay_buffer, pagesize=(width, height))
        for mapping in mappings_by_page.get(page_number, []):
            if mapping.baseline_y is None:
                continue
            overlay.setFont("Helvetica", mapping.font_size or TEXT_SIZE)
            overlay.drawRightString(
                mapping.unit_price_right_x or (DEFAULT_UNIT_PRICE_RIGHT_X - PRICE_CELL_INNER_MARGIN),
                mapping.baseline_y,
                _format_price(mapping.unit_price_chf),
            )
            overlay.drawRightString(
                mapping.total_price_right_x or (DEFAULT_TOTAL_PRICE_RIGHT_X - PRICE_CELL_INNER_MARGIN),
                mapping.baseline_y,
                _format_price(mapping.position_total_chf),
            )
        overlay.showPage()
        overlay.save()
        overlay_buffer.seek(0)
        overlay_page = PdfReader(overlay_buffer).pages[0]
        writer.add_page(page)
        writer.pages[-1].merge_page(overlay_page)

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    with output_pdf.open("wb") as handle:
        writer.write(handle)


def write_mapping_json(path: Path, mappings: list[PriceCellMapping], pages: list[int]) -> None:
    payload = {
        "schema_version": PROTOTYPE_SCHEMA_VERSION,
        "pages": pages,
        "pricing_policy": (
            "Prototype overlays only calculated, non-supplier-package direct costs. "
            "Supplier_quote_required, review_required, insufficient_information and non_priceable rows are left blank."
        ),
        "unit_price_definition": "direct_position_cost_chf / quantity for accepted calculated prototype rows",
        "mappings": [mapping.to_dict() for mapping in mappings],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def render_pdf_pages(pdf_path: Path, output_prefix: Path, first_page: int, last_page: int) -> list[Path]:
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "pdftoppm",
        "-f",
        str(first_page),
        "-l",
        str(last_page),
        "-png",
        "-r",
        "144",
        str(pdf_path),
        str(output_prefix),
    ]
    subprocess.run(command, check=True)
    return sorted(output_prefix.parent.glob(output_prefix.name + "-*.png"))


def _map_position(
    row: dict[str, Any],
    lines: list[LineBox],
    page_height: float,
    geometry: PriceColumnGeometry,
) -> PriceCellMapping:
    source_line = str(row.get("source_line", ""))
    candidates = [line for line in lines if _line_matches(source_line, line.text)]
    if len(candidates) != 1:
        return _unmapped(
            row,
            "ambiguous_line_match" if candidates else "line_not_found",
            f"Matched {len(candidates)} candidate PDF lines for source_line.",
        )

    line = candidates[0]
    quantity = float(row["quantity"])
    total = float(row.get("accepted_direct_position_cost_chf") or row["direct_position_cost_chf"])
    unit_price = float(money(Decimal(str(total)) / Decimal(str(quantity))))
    unit_text = _format_price(unit_price)
    total_text = _format_price(total)
    font_size = _font_size_for_cells(unit_text, total_text, geometry)
    unit_right_x = geometry.unit_price_right_x - PRICE_CELL_INNER_MARGIN
    total_right_x = geometry.total_price_right_x - PRICE_CELL_INNER_MARGIN
    baseline_y = _baseline_y(line, page_height)
    bbox = {"x0": line.x0, "top": line.top, "x1": line.x1, "bottom": line.bottom}
    return PriceCellMapping(
        lv_id=row["lv_id"],
        source_page=int(row["source_page"]),
        source_line=source_line,
        status=str(row["status"]),
        quantity=quantity,
        unit=str(row["unit"]),
        unit_price_chf=unit_price,
        position_total_chf=total,
        line_bbox=bbox,
        unit_price_right_x=unit_right_x,
        total_price_right_x=total_right_x,
        unit_price_cell_bbox=_cell_bbox(geometry.unit_price_left_x, geometry.unit_price_right_x, line, page_height),
        total_price_cell_bbox=_cell_bbox(geometry.total_price_left_x, geometry.total_price_right_x, line, page_height),
        unit_price_text_bbox=_text_bbox(unit_text, unit_right_x, baseline_y, font_size),
        total_price_text_bbox=_text_bbox(total_text, total_right_x, baseline_y, font_size),
        font_size=font_size,
        baseline_y=baseline_y,
        placement_status="mapped",
        placement_reason="Unique source_line match on the same PDF page.",
    )


def _unmapped(row: dict[str, Any], status: str, reason: str) -> PriceCellMapping:
    return PriceCellMapping(
        lv_id=row["lv_id"],
        source_page=int(row["source_page"]),
        source_line=str(row.get("source_line", "")),
        status=str(row.get("status", "")),
        quantity=float(row.get("quantity", 0)),
        unit=str(row.get("unit", "")),
        unit_price_chf=None,
        position_total_chf=None,
        line_bbox=None,
        unit_price_right_x=None,
        total_price_right_x=None,
        unit_price_cell_bbox=None,
        total_price_cell_bbox=None,
        unit_price_text_bbox=None,
        total_price_text_bbox=None,
        font_size=None,
        baseline_y=None,
        placement_status=status,
        placement_reason=reason,
    )


def _line_matches(source_line: str, pdf_line: str) -> bool:
    source = _normalise_line(source_line)
    candidate = _normalise_line(pdf_line)
    if not source or not candidate:
        return False
    return source in candidate


def _normalise_line(value: str) -> str:
    value = value.replace("�", "")
    value = re.sub(r"\s+", " ", value.lower())
    value = re.sub(r"[^a-z0-9.,/() äöüàéèß-]", "", value)
    return value.strip()


def _baseline_y(line: LineBox, page_height: float) -> float:
    return page_height - line.bottom + 1.2


def _format_price(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:,.2f}".replace(",", "'")


def _font_size_for_cells(unit_text: str, total_text: str, geometry: PriceColumnGeometry) -> float:
    try:
        from reportlab.pdfbase.pdfmetrics import stringWidth
    except ImportError:  # pragma: no cover
        return TEXT_SIZE
    font_size = TEXT_SIZE
    while font_size > MIN_TEXT_SIZE:
        unit_width = stringWidth(unit_text, "Helvetica", font_size)
        total_width = stringWidth(total_text, "Helvetica", font_size)
        unit_cell_width = geometry.unit_price_right_x - geometry.unit_price_left_x - (2 * PRICE_CELL_INNER_MARGIN)
        total_cell_width = geometry.total_price_right_x - geometry.total_price_left_x - (2 * PRICE_CELL_INNER_MARGIN)
        if unit_width <= unit_cell_width and total_width <= total_cell_width:
            return round(font_size, 2)
        font_size -= 0.2
    return MIN_TEXT_SIZE


def _cell_bbox(left_x: float, right_x: float, line: LineBox, page_height: float) -> dict[str, float]:
    return {
        "x0": left_x,
        "y0": page_height - line.bottom,
        "x1": right_x,
        "y1": page_height - line.top,
    }


def _text_bbox(text: str, right_x: float, baseline_y: float, font_size: float) -> dict[str, float]:
    try:
        from reportlab.pdfbase.pdfmetrics import stringWidth
        width = stringWidth(text, "Helvetica", font_size)
    except ImportError:  # pragma: no cover
        width = 0.0
    return {
        "x0": right_x - width,
        "y0": baseline_y,
        "x1": right_x,
        "y1": baseline_y + font_size,
    }


def _has_accepted_price(row: dict[str, Any]) -> bool:
    direct_cost = row.get("accepted_direct_position_cost_chf")
    if direct_cost is None:
        direct_cost = row.get("direct_position_cost_chf")
    return (
        direct_cost is not None
        and row.get("quantity") not in (None, 0)
        and row.get("net_unit_cost_chf") is not None
    )
