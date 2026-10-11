from __future__ import annotations

import io
import json
import re
import subprocess
from collections import Counter
from statistics import median
from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from .calculation_engine import money


PROTOTYPE_SCHEMA_VERSION = "phase8e.pdf_overlay_prototype.v1"
EXPORT_SCHEMA_VERSION = "phase8f.pdf_overlay_export.v1"
PRICEABLE_OVERLAY_STATUS = {"calculated"}
PRICE_CELL_INNER_MARGIN = 4.0
TEXT_SIZE = 9.5
MAX_TEXT_SIZE = 10.0
MIN_TEXT_SIZE = 7.0
VERTICAL_TEXT_MARGIN = 0.6
LINE_MATCH_TOLERANCE = 3.0


@dataclass(frozen=True)
class LineBox:
    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    pdf_y0: float
    pdf_y1: float
    baseline_y: float
    font_size: float


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
                if int(getattr(page, "rotation", 0) or 0) % 360:
                    mappings.append(
                        _unmapped(
                            row,
                            "unsupported_page_rotation",
                            "Page rotation requires a separately validated coordinate transform.",
                        )
                    )
                elif not _uses_supported_coordinate_origin(page):
                    mappings.append(
                        _unmapped(
                            row,
                            "unsupported_page_coordinate_system",
                            "Page MediaBox origin is non-zero; overlay coordinates were not guessed.",
                        )
                    )
                elif geometry is None:
                    mappings.append(
                        _unmapped(
                            row,
                            "price_columns_not_found",
                            "Price-column boundaries could not be established from page geometry.",
                        )
                    )
                else:
                    mappings.append(_map_position(row, lines, geometry))
    return _reject_cell_collisions(mappings)


def detect_price_column_geometry(page: Any) -> PriceColumnGeometry | None:
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
    return None


def _cluster_x_positions(values: list[float], tolerance: float = 0.8) -> list[float]:
    clustered: list[list[float]] = []
    for value in sorted(values):
        if clustered and abs(value - (sum(clustered[-1]) / len(clustered[-1]))) <= tolerance:
            clustered[-1].append(value)
        else:
            clustered.append([value])
    return [round(sum(group) / len(group), 2) for group in clustered]


def extract_line_boxes(page: Any) -> list[LineBox]:
    words = page.extract_words(
        x_tolerance=1,
        y_tolerance=3,
        keep_blank_chars=False,
        extra_attrs=["size", "fontname"],
    ) or []
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
        x0 = min(float(word["x0"]) for word in ordered)
        x1 = max(float(word["x1"]) for word in ordered)
        top = min(float(word["top"]) for word in ordered)
        bottom = max(float(word["bottom"]) for word in ordered)
        line_center = (top + bottom) / 2
        chars = [
            char
            for char in getattr(page, "chars", [])
            if float(char.get("x1", 0)) >= x0
            and float(char.get("x0", 0)) <= x1
            and abs(
                ((float(char.get("top", 0)) + float(char.get("bottom", 0))) / 2)
                - line_center
            ) <= LINE_MATCH_TOLERANCE
        ]
        sizes = [float(char.get("size", 0)) for char in chars if float(char.get("size", 0)) > 0]
        if not sizes:
            sizes = [float(word.get("size", 0)) for word in ordered if float(word.get("size", 0)) > 0]
        source_size = float(median(sizes)) if sizes else TEXT_SIZE
        baselines = [
            float(char["matrix"][5])
            for char in chars
            if isinstance(char.get("matrix"), (list, tuple)) and len(char["matrix"]) >= 6
        ]
        pdf_y0_values = [float(char["y0"]) for char in chars if char.get("y0") is not None]
        pdf_y1_values = [float(char["y1"]) for char in chars if char.get("y1") is not None]
        pdf_y0 = min(pdf_y0_values) if pdf_y0_values else float(page.height) - bottom
        pdf_y1 = max(pdf_y1_values) if pdf_y1_values else float(page.height) - top
        baseline_y = float(median(baselines)) if baselines else pdf_y0 + (source_size * 0.21)
        lines.append(
            LineBox(
                text=" ".join(str(word["text"]) for word in ordered),
                x0=x0,
                top=top,
                x1=x1,
                bottom=bottom,
                pdf_y0=pdf_y0,
                pdf_y1=pdf_y1,
                baseline_y=baseline_y,
                font_size=source_size,
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
            if mapping.unit_price_right_x is None or mapping.total_price_right_x is None:
                continue
            overlay.drawRightString(
                mapping.unit_price_right_x,
                mapping.baseline_y,
                _format_price(mapping.unit_price_chf),
            )
            overlay.drawRightString(
                mapping.total_price_right_x,
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
    geometry: PriceColumnGeometry,
) -> PriceCellMapping:
    source_line = str(row.get("source_line", ""))
    scored = [
        (_line_match_score(source_line, line.text, float(row.get("quantity", 0))), line)
        for line in lines
        if line.x0 < geometry.unit_price_left_x
    ]
    best_score = max((score for score, _line in scored), default=0)
    candidates = [line for score, line in scored if score == best_score and score >= 60]
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
    row_y0, row_y1 = line.pdf_y0, line.pdf_y1
    preferred_size = min(TEXT_SIZE, MAX_TEXT_SIZE, max(MIN_TEXT_SIZE, line.font_size * 0.95))
    minimum_size = max(MIN_TEXT_SIZE, min(preferred_size, line.font_size * 0.75))
    font_size = _font_size_for_cells(
        unit_text,
        total_text,
        geometry,
        row_y1 - row_y0,
        preferred_size=preferred_size,
        minimum_size=minimum_size,
    )
    if font_size is None:
        return _unmapped(row, "price_text_does_not_fit", "Price does not fit the validated cell at a readable font size.")
    from reportlab.pdfbase.pdfmetrics import stringWidth
    if any(
        stringWidth(text, "Helvetica", font_size) > right - left - 2 * PRICE_CELL_INNER_MARGIN
        for text, left, right in (
            (unit_text, geometry.unit_price_left_x, geometry.unit_price_right_x),
            (total_text, geometry.total_price_left_x, geometry.total_price_right_x),
        )
    ):
        return _unmapped(row, "price_text_does_not_fit", "Price exceeds the validated cell width at readable font size.")
    unit_right_x = geometry.unit_price_right_x - PRICE_CELL_INNER_MARGIN
    total_right_x = geometry.total_price_right_x - PRICE_CELL_INNER_MARGIN
    baseline_y = line.baseline_y
    if not _text_fits_vertically(baseline_y, font_size, row_y0, row_y1):
        baseline_y = _baseline_y(row_y0, row_y1, font_size)
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
        unit_price_cell_bbox=_cell_bbox(geometry.unit_price_left_x, geometry.unit_price_right_x, row_y0, row_y1),
        total_price_cell_bbox=_cell_bbox(geometry.total_price_left_x, geometry.total_price_right_x, row_y0, row_y1),
        unit_price_text_bbox=_text_bbox(unit_text, unit_right_x, baseline_y, font_size),
        total_price_text_bbox=_text_bbox(total_text, total_right_x, baseline_y, font_size),
        font_size=font_size,
        baseline_y=baseline_y,
        placement_status="mapped",
        placement_reason="Unique language-independent row anchor on the same PDF page; price columns validated from page geometry.",
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
    return _line_match_score(source_line, pdf_line, 0) >= 60


def _line_match_score(source_line: str, pdf_line: str, quantity: float) -> int:
    source = _normalise_line(source_line)
    candidate = _normalise_line(pdf_line)
    if not source or not candidate:
        return 0
    if (source in candidate or candidate in source) and _quantity_present(candidate, quantity):
        return 100

    source_tokens = _row_anchor_tokens(source)
    candidate_tokens = _row_anchor_tokens(candidate)
    if not source_tokens:
        return 0
    shared = source_tokens & candidate_tokens
    coverage = len(shared) / len(source_tokens)
    model_tokens = {token for token in source_tokens if any(char.isdigit() for char in token)}
    model_coverage = 1.0 if not model_tokens else len(model_tokens & candidate_tokens) / len(model_tokens)
    quantity_present = _quantity_present(candidate, quantity)
    if coverage < 0.55 or model_coverage < 0.5 or not quantity_present:
        return 0
    return int(round(45 + coverage * 35 + model_coverage * 15 + 5))


def _row_anchor_tokens(value: str) -> set[str]:
    # Drop short alphabetic unit labels without enumerating German, English or French units.
    return {
        token
        for token in re.findall(r"[a-z0-9]+(?:[./-][a-z0-9]+)*", value)
        if not (token.isalpha() and len(token) <= 3)
    }


def _quantity_present(value: str, quantity: float) -> bool:
    if quantity <= 0:
        return True
    numbers = [float(item.replace(",", ".")) for item in re.findall(r"(?<!\d)\d+(?:[.,]\d+)?(?!\d)", value)]
    return any(abs(item - quantity) <= 0.0001 for item in numbers)


def _reject_cell_collisions(mappings: list[PriceCellMapping]) -> list[PriceCellMapping]:
    cell_counts = Counter(
        (mapping.source_page, round(float(mapping.baseline_y), 2))
        for mapping in mappings
        if mapping.placement_status == "mapped" and mapping.baseline_y is not None
    )
    resolved: list[PriceCellMapping] = []
    for mapping in mappings:
        key = (
            mapping.source_page,
            round(float(mapping.baseline_y), 2) if mapping.baseline_y is not None else None,
        )
        if mapping.placement_status == "mapped" and cell_counts.get(key, 0) > 1:
            resolved.append(
                replace(
                    mapping,
                    unit_price_chf=None,
                    position_total_chf=None,
                    unit_price_right_x=None,
                    total_price_right_x=None,
                    unit_price_cell_bbox=None,
                    total_price_cell_bbox=None,
                    unit_price_text_bbox=None,
                    total_price_text_bbox=None,
                    font_size=None,
                    baseline_y=None,
                    placement_status="ambiguous_cell_collision",
                    placement_reason="Multiple approved positions resolved to the same PDF price row.",
                )
            )
        else:
            resolved.append(mapping)
    return resolved


def _normalise_line(value: str) -> str:
    value = value.replace("�", "")
    value = re.sub(r"\s+", " ", value.lower())
    value = re.sub(r"[^a-z0-9.,/() äöüàéèß-]", "", value)
    return value.strip()


def _font_metrics(font_size: float) -> tuple[float, float]:
    from reportlab.pdfbase.pdfmetrics import getAscentDescent

    ascent, descent = getAscentDescent("Helvetica", font_size)
    return float(ascent), float(descent)


def _baseline_y(row_y0: float, row_y1: float, font_size: float) -> float:
    ascent, descent = _font_metrics(font_size)
    return ((row_y0 + row_y1) / 2) - ((ascent + descent) / 2)


def _format_price(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:,.2f}".replace(",", "'")


def _font_size_for_cells(
    unit_text: str,
    total_text: str,
    geometry: PriceColumnGeometry,
    available_height: float,
    *,
    preferred_size: float = TEXT_SIZE,
    minimum_size: float = MIN_TEXT_SIZE,
) -> float | None:
    try:
        from reportlab.pdfbase.pdfmetrics import stringWidth
    except ImportError:  # pragma: no cover
        return TEXT_SIZE
    font_size = min(preferred_size, MAX_TEXT_SIZE)
    while font_size >= minimum_size:
        unit_width = stringWidth(unit_text, "Helvetica", font_size)
        total_width = stringWidth(total_text, "Helvetica", font_size)
        ascent, descent = _font_metrics(font_size)
        text_height = ascent - descent
        unit_cell_width = geometry.unit_price_right_x - geometry.unit_price_left_x - (2 * PRICE_CELL_INNER_MARGIN)
        total_cell_width = geometry.total_price_right_x - geometry.total_price_left_x - (2 * PRICE_CELL_INNER_MARGIN)
        if (
            unit_width <= unit_cell_width
            and total_width <= total_cell_width
            and text_height <= available_height - (2 * VERTICAL_TEXT_MARGIN)
        ):
            return round(font_size, 2)
        font_size -= 0.2
    return None


def _text_fits_vertically(
    baseline_y: float,
    font_size: float,
    row_y0: float,
    row_y1: float,
) -> bool:
    ascent, descent = _font_metrics(font_size)
    return (
        baseline_y + descent >= row_y0 - 0.1
        and baseline_y + ascent <= row_y1 + 0.1
    )


def _uses_supported_coordinate_origin(page: Any) -> bool:
    mediabox = tuple(float(value) for value in getattr(page, "mediabox", (0, 0, page.width, page.height)))
    return len(mediabox) == 4 and abs(mediabox[0]) <= 0.01 and abs(mediabox[1]) <= 0.01


def _cell_bbox(left_x: float, right_x: float, row_y0: float, row_y1: float) -> dict[str, float]:
    return {
        "x0": left_x,
        "y0": row_y0,
        "x1": right_x,
        "y1": row_y1,
    }


def _text_bbox(text: str, right_x: float, baseline_y: float, font_size: float) -> dict[str, float]:
    try:
        from reportlab.pdfbase.pdfmetrics import stringWidth
        width = stringWidth(text, "Helvetica", font_size)
    except ImportError:  # pragma: no cover
        width = 0.0
    ascent, descent = _font_metrics(font_size)
    return {
        "x0": right_x - width,
        "y0": baseline_y + descent,
        "x1": right_x,
        "y1": baseline_y + ascent,
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
