from __future__ import annotations

import re
from dataclasses import dataclass, asdict, replace

from .pdf_ingestion import PdfPageText


UNIT_MAP = {
    "Stk": "pc",
    "Stk.": "pc",
    "pc": "pc",
    "pcs": "pc",
    "piece": "pc",
    "pieces": "pc",
    "pièce": "pc",
    "pièces": "pc",
    "pce": "pc",
    "pces": "pc",
    "Std": "h",
    "Std.": "h",
    "m2": "m2",
    "m²": "m2",
    "m3": "m3",
    "m³": "m3",
    "m": "m",
    "mm": "mm",
    "h": "h",
    "LS": "LS",
    "System": "system",
}

# A bare hour unit is lowercase-only. The surrounding expressions are otherwise
# case-insensitive, so this local flag prevents dimension labels such as "B x H".
HOUR_UNIT_PATTERN = r"(?-i:h)"
UNIT_PATTERN = rf"Stk\.?|Std\.?|pièces|pièce|pieces|piece|pces|pcs|pce|pc|m²|m³|m2|m3|mm|m|{HOUR_UNIT_PATTERN}|LS|System"
COUNT_UNIT_PATTERN = rf"Stk\.?|Std\.?|pièces|pièce|pieces|piece|pces|pcs|pce|pc|m²|m³|m2|m3|{HOUR_UNIT_PATTERN}|LS|System"
QUANTITY_RE = re.compile(
    rf"(?P<prefix>.*?)\b(?P<unit>{UNIT_PATTERN})\s+(?P<quantity>\d+(?:[.,]\d+)?)\b",
    re.IGNORECASE,
)
UNIT_ONLY_RE = re.compile(
    rf"(?P<prefix>.*?)\b(?P<unit>{COUNT_UNIT_PATTERN})\s*$",
    re.IGNORECASE,
)
REVERSE_QUANTITY_RE = re.compile(
    rf"(?P<prefix>.*?)(?<![-\d])(?P<quantity>\d+(?:[.,]\d+)?)\s+(?P<unit>{COUNT_UNIT_PATTERN})(?!/)\b",
    re.IGNORECASE,
)
SYSTEM_RE = re.compile(r"SH Erlenstrasse Oberglatt\s+(?P<system>244\.\d+\s+.*?)\s+Seite")
DIMENSION_RE = re.compile(
    r"(?P<raw>\b\d+(?:[.,]\d+)?\s*x\s*\d+(?:[.,]\d+)?(?:\s*x\s*\d+(?:[.,]\d+)?)?\s*(?P<unit>mm|cm|m)?\b)",
    re.IGNORECASE,
)
MODEL_CODE_DIMENSION_RE = re.compile(r"(?<!\d)(?P<raw>\d{2,4}x\d{2,4}x\d{2,4})(?!\d)", re.IGNORECASE)
DIAMETER_RE = re.compile(
    r"(?P<raw>\bDN\s*(?P<dn>\d+(?:[.,]\d+)?)\b|[?Ø�]\s*(?P<after>\d+(?:[.,]\d+)?)\s*(?P<after_unit>mm|cm)?\b|\b(?P<before>\d+(?:[.,]\d+)?)\s*[?Ø�]\s*(?P<before_unit>mm|cm)?\b)",
    re.IGNORECASE,
)
FIRE_RATING_RE = re.compile(r"\bEI\s*-?\s*\d+(?:-S)?\b", re.IGNORECASE)
MATERIAL_RE = re.compile(r"\b(V2A|verzinkt|sendizimierverzinkt|Mineralwoll\w*|Alu-Folie|Stahl)\b", re.IGNORECASE)
MODEL_RE = re.compile(r"\b(Z-LVS|LVS|MS-F|TVJ-D|TVR-D|VFC|FKRS-EU|FK2-EU|BKN230/24-MOD-BAC)\b", re.IGNORECASE)
COMPONENT_LIST_CODES = {"L", "LT", "BA", "BS", "BO", "HS", "RS", "SR", "UA", "US"}
LENGTH_COMPONENT_CODES = {"L", "LT"}


@dataclass(frozen=True)
class ExtractedPosition:
    lv_id: str
    source_page: int
    system: str | None
    source_language: str
    original_description: str
    description: str
    quantity: float
    unit: str
    original_unit: str
    source_line: str
    evidence: str
    record_type: str
    technical_attributes: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def parse_lv_positions(pages: list[PdfPageText]) -> list[ExtractedPosition]:
    positions: list[ExtractedPosition] = []
    for page in pages:
        positions.extend(parse_page_positions(page))
    return positions


def parse_page_positions(page: PdfPageText) -> list[ExtractedPosition]:
    primary = _parse_page_positions_text(
        PdfPageText(page_number=page.page_number, text=page.text, extraction_backend=page.extraction_backend)
    )
    if not page.structured_text or page.structured_text.strip() == page.text.strip():
        return primary
    supplemental = _parse_page_positions_text(
        PdfPageText(page_number=page.page_number, text=page.structured_text, extraction_backend="docling_structured")
    )
    merged = list(primary)
    for candidate in supplemental:
        if any(_same_source_position(candidate, existing) for existing in merged):
            continue
        merged.append(
            replace(
                candidate,
                lv_id=f"PDF{page.page_number:03d}-{len(merged) + 1:02d}",
                evidence="Docling structured evidence:\n" + candidate.evidence,
            )
        )
    return merged


def _parse_page_positions_text(page: PdfPageText) -> list[ExtractedPosition]:
    lines = [_clean_line(line) for line in page.text.splitlines()]
    lines = [line for line in lines if line]
    system = _extract_system(lines)
    if _looks_like_component_list_page(lines):
        return _parse_component_list_page(page, lines, system)

    context: list[str] = []
    positions: list[ExtractedPosition] = []

    for line_index, line in enumerate(lines):
        if _is_noise_line(line):
            continue
        if re.match(r"(?:Drehantrieb|Stellantrieb|Kanaltemperatur|Druckdifferenz|Druckw[aä]chter|Frostschutzw[aä]chter)", line, re.IGNORECASE):
            context = []
        if _looks_like_heading(line):
            context = [line]
        match = QUANTITY_RE.search(line)
        if match:
            original_unit = match.group("unit")
            unit = UNIT_MAP[_canonical_unit_key(original_unit)]
            quantity = float(match.group("quantity").replace(",", "."))
            description_lines = _description_context(context, line)
            if re.match(r"(?:Drehantrieb|Stellantrieb)\b", line, re.IGNORECASE):
                # Only the adjacent electrical specification belongs to this device.
                following = lines[line_index + 1:line_index + 2]
                if following and re.match(r"(?:AC/DC|AC|DC)\s+\d+\s*V\b", following[0], re.IGNORECASE):
                    description_lines.extend(following)
            description = " ".join(description_lines)
            evidence = "\n".join(description_lines[-8:])
            positions.append(
                _make_position(
                    page_number=page.page_number,
                    sequence=len(positions) + 1,
                    system=system,
                    description=description,
                    quantity=quantity,
                    unit=unit,
                    original_unit=original_unit,
                    source_line=line,
                    evidence=evidence,
                    record_type=_record_type_for_unit(original_unit),
                )
            )
        elif (reverse_match := REVERSE_QUANTITY_RE.search(line)) and _is_reverse_quantity_candidate(line):
            original_unit = reverse_match.group("unit")
            description_lines = _description_context(context, line)
            description = " ".join(description_lines)
            positions.append(
                _make_position(
                    page_number=page.page_number,
                    sequence=len(positions) + 1,
                    system=system,
                    description=description,
                    quantity=float(reverse_match.group("quantity").replace(",", ".")),
                    unit=UNIT_MAP[_canonical_unit_key(original_unit)],
                    original_unit=original_unit,
                    source_line=line,
                    evidence="\n".join(description_lines[-8:]),
                    record_type=_record_type_for_unit(original_unit),
                )
            )
        elif _is_unit_without_quantity_candidate(line):
            unit_match = UNIT_ONLY_RE.search(line)
            if unit_match:
                original_unit = unit_match.group("unit")
                description_lines = _description_context(context, line)
                description = " ".join(description_lines)
                positions.append(
                    _make_position(
                        page_number=page.page_number,
                        sequence=len(positions) + 1,
                        system=system,
                        description=description,
                        quantity=0.0,
                        unit=UNIT_MAP[_canonical_unit_key(original_unit)],
                        original_unit=original_unit,
                        source_line=line,
                        evidence="\n".join(description_lines[-8:]),
                        record_type="tender_position_missing_quantity",
                    )
                )
        context.append(line)
        context = context[-60:]
    return positions


def _same_source_position(left: ExtractedPosition, right: ExtractedPosition) -> bool:
    if left.unit != right.unit or abs(left.quantity - right.quantity) > 0.0001:
        return False
    left_text = re.sub(r"\W+", " ", left.source_line.casefold()).strip()
    right_text = re.sub(r"\W+", " ", right.source_line.casefold()).strip()
    if not left_text or not right_text:
        return False
    if left_text in right_text or right_text in left_text:
        return True
    left_tokens = set(left_text.split())
    right_tokens = set(right_text.split())
    return len(left_tokens & right_tokens) / max(len(left_tokens), len(right_tokens)) >= 0.8


def _make_position(
    *,
    page_number: int,
    sequence: int,
    system: str | None,
    description: str,
    quantity: float,
    unit: str,
    original_unit: str,
    source_line: str,
    evidence: str,
    record_type: str,
    technical_attributes: dict[str, object] | None = None,
) -> ExtractedPosition:
    attrs = _technical_attributes(description)
    if technical_attributes:
        attrs.update(technical_attributes)
    return ExtractedPosition(
        lv_id=f"PDF{page_number:03d}-{sequence:02d}",
        source_page=page_number,
        system=system,
        source_language="de",
        original_description=description,
        description=description,
        quantity=quantity,
        unit=unit,
        original_unit=original_unit,
        source_line=source_line,
        evidence=evidence,
        record_type=record_type,
        technical_attributes=attrs,
    )


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def _canonical_unit_key(unit: str) -> str:
    unit = unit.strip()
    for key in UNIT_MAP:
        if key.lower() == unit.lower():
            return key
    return unit


def _record_type_for_unit(original_unit: str) -> str:
    return "labour_service" if _canonical_unit_key(original_unit) in {"Std", "Std.", "h"} else "tender_position"


def _extract_system(lines: list[str]) -> str | None:
    for line in lines[:5]:
        match = SYSTEM_RE.search(line)
        if match:
            return match.group("system").strip()
    return None


def _is_noise_line(line: str) -> bool:
    return (
        line.startswith("H:\\")
        or line.startswith("Pos. ")
        or line.startswith("Gattg.")
        or line.startswith("SH Erlenstrasse")
        or line.startswith("____")
    )


def _looks_like_heading(line: str) -> bool:
    if QUANTITY_RE.search(line):
        return False
    if len(line) > 70:
        return False
    lower = line.lower()
    if "brandschutzdämmung" in lower or "brandschutzdaemmung" in lower:
        return False
    heading_terms = (
        "tellerventil",
        "schalld",
        "volumenstromregler",
        "drosselklappen",
        "brandschutz",
        "dehnungsmanschette",
        "aussend",
        "durchdringungen",
        "anschlusswinkle",
        "revisisondeckel",
        "revisionsdeckel",
        "kanal",
        "gitter",
        "regenhut",
        "lamellenhut",
    )
    return any(term in lower for term in heading_terms)


def _is_unit_without_quantity_candidate(line: str) -> bool:
    if "..." in line:
        return False
    match = UNIT_ONLY_RE.search(line)
    if not match:
        return False
    prefix = match.group("prefix").strip()
    if len(prefix) < 4 or not re.search(r"[A-Za-zÄÖÜäöüß�]", prefix):
        return False
    lowered = prefix.lower()
    blocked_terms = (
        "pos.",
        "einheits",
        "betrag",
        "mass",
        "preis",
        "fabrikat",
        "typ z.b",
        "druckverlust",
        "luftmenge",
        "filterfläche",
        "alu-folie",
        "gestiftet",
    )
    if lowered.startswith("mit "):
        return False
    return not any(term in lowered for term in blocked_terms)


def _is_reverse_quantity_candidate(line: str) -> bool:
    lowered = line.lower()
    blocked_terms = (
        "luftmenge",
        "volumenstrom",
        "filterfläche",
        "filterfl",
        "druckverlust",
        "schallleistungspegel",
        "abmessung",
        "anzahl kulissen",
        "masse",
    )
    if any(term in lowered for term in blocked_terms):
        return False
    if line.lstrip().startswith("-"):
        return True
    return bool(re.search(r"[A-Za-zÄÖÜäöüß�]{4,}", line))


def _looks_like_component_list_page(lines: list[str]) -> bool:
    text = " ".join(lines).lower()
    return "bauteilliste" in text and ("lüftung" in text or "l�ftung" in text or "luftleitung" in text)


def _parse_component_list_page(
    page: PdfPageText,
    lines: list[str],
    system: str | None,
) -> list[ExtractedPosition]:
    positions: list[ExtractedPosition] = []
    table_context: list[str] = []
    in_component_section = False
    for line in lines:
        lower = line.lower()
        if "auflistung der kanäle" in lower or "auflistung der kanalformstücke" in lower or "auflistung der kanalformst" in lower:
            in_component_section = True
            table_context = [line]
            continue
        if not in_component_section:
            continue
        if _is_component_table_header(line):
            table_context.append(line)
            table_context = table_context[-5:]
            continue
        component = _parse_component_list_line(line)
        if not component:
            continue
        description = line
        evidence = "\n".join((table_context + [line])[-6:])
        positions.append(
            _make_position(
                page_number=page.page_number,
                sequence=len(positions) + 1,
                system=system,
                description=description,
                quantity=component["quantity"],
                unit=component["unit"],
                original_unit=component["original_unit"],
                source_line=line,
                evidence=evidence,
                record_type="component_list_row",
                technical_attributes={
                    "component_list": {
                        "type_code": component["type_code"],
                        "description": component["component_description"],
                        "numeric_values": component["numeric_values"],
                        "quantity_or_length": component["quantity"],
                        "unit": component["unit"],
                        "source_unit": component["original_unit"],
                    }
                },
            )
        )
    return positions


def _is_component_table_header(line: str) -> bool:
    lower = line.lower()
    return (
        "bauteilliste" in lower
        or "kanäle" in lower
        or "kanalform" in lower
        or lower.startswith("l mm")
        or lower.startswith("stk kz")
        or "formteil" in lower
    )


def _parse_component_list_line(line: str) -> dict[str, object] | None:
    tokens = line.split()
    if len(tokens) < 5:
        return None
    if not _looks_number(tokens[0]):
        return None
    type_code = tokens[1].upper()
    if type_code not in COMPONENT_LIST_CODES:
        return None
    first_numeric_after_description = None
    for index, token in enumerate(tokens[2:], start=2):
        if _looks_number(token):
            first_numeric_after_description = index
            break
    if first_numeric_after_description is None or first_numeric_after_description <= 2:
        return None
    component_description = " ".join(tokens[2:first_numeric_after_description])
    numeric_values = [_to_float(token) for token in tokens[first_numeric_after_description:] if _looks_number(token)]
    if len(numeric_values) < 2:
        return None
    quantity = _to_float(tokens[0])
    if type_code in LENGTH_COMPONENT_CODES:
        unit = "mm"
        original_unit = "l mm"
    else:
        unit = "pc"
        original_unit = "Stk"
    return {
        "quantity": quantity,
        "unit": unit,
        "original_unit": original_unit,
        "type_code": type_code,
        "component_description": component_description,
        "numeric_values": numeric_values,
    }


def _looks_number(value: str) -> bool:
    return re.fullmatch(r"\d+(?:[.,]\d+)?", value) is not None


def _description_context(context: list[str], line: str) -> list[str]:
    candidate = context + [line]
    return [part for part in candidate if not _is_noise_line(part)]


def _technical_attributes(description: str) -> dict[str, object]:
    return {
        "dimensions": _dimensions(description),
        "model_code_dimensions": _model_code_dimensions(description),
        "ambiguous_dimensions": _ambiguous_dimensions(description),
        "diameters": _diameters(description),
        "fire_ratings": [rating.upper().replace(" ", "") for rating in FIRE_RATING_RE.findall(description)],
        "materials": sorted({match.group(0) for match in MATERIAL_RE.finditer(description)}),
        "model_hints": sorted({match.group(0) for match in MODEL_RE.finditer(description)}),
    }


def _to_float(value: str) -> float:
    return float(value.replace(",", "."))


def _to_mm(value: float, unit: str | None) -> float:
    if unit and unit.lower() == "m":
        return value * 1000
    if unit and unit.lower() == "cm":
        return value * 10
    return value


def _dimensions(description: str) -> list[dict[str, object]]:
    dimensions: list[dict[str, object]] = []
    model_spans = [match.span("raw") for match in MODEL_CODE_DIMENSION_RE.finditer(description)]
    for match in DIMENSION_RE.finditer(description):
        if _span_inside(match.span("raw"), model_spans):
            continue
        raw = match.group("raw").strip()
        unit = match.group("unit")
        if not unit:
            contextual_unit = _contextual_dimension_unit(description, match.start())
            if not contextual_unit:
                continue
            unit = contextual_unit
        unit = unit.lower()
        values = [_to_float(part) for part in re.findall(r"\d+(?:[.,]\d+)?", raw)]
        dimensions.append(
            {
                "raw": raw,
                "unit": unit,
                "values": values,
                "values_mm": [_to_mm(value, unit) for value in values],
            }
        )
    return dimensions


def _model_code_dimensions(description: str) -> list[dict[str, object]]:
    dimensions: list[dict[str, object]] = []
    for match in MODEL_CODE_DIMENSION_RE.finditer(description):
        raw = match.group("raw")
        values = [_to_float(part) for part in raw.lower().split("x")]
        if len(values) != 3:
            continue
        dimensions.append(
            {
                "raw": raw,
                "unit": "model_code_mm",
                "values": values,
                "values_mm": values,
                "normalization_note": "Compact three-part model-code dimension interpreted as millimetres; kept separate from explicit source dimensions.",
            }
        )
    return dimensions


def _ambiguous_dimensions(description: str) -> list[dict[str, object]]:
    ambiguous: list[dict[str, object]] = []
    model_spans = [match.span("raw") for match in MODEL_CODE_DIMENSION_RE.finditer(description)]
    for match in DIMENSION_RE.finditer(description):
        if match.group("unit") or _span_inside(match.span("raw"), model_spans):
            continue
        if _contextual_dimension_unit(description, match.start()):
            continue
        values = [_to_float(part) for part in re.findall(r"\d+(?:[.,]\d+)?", match.group("raw"))]
        ambiguous.append(
            {
                "raw": match.group("raw").strip(),
                "unit": None,
                "values": values,
                "normalization_note": "No explicit or contextual unit found; not normalized to millimetres.",
            }
        )
    return ambiguous


def _contextual_dimension_unit(description: str, start: int) -> str | None:
    before = description[max(0, start - 80):start].lower()
    if "(mm)" in before or " mm" in before:
        return "mm"
    if "(cm)" in before or " cm" in before:
        return "cm"
    return None


def _span_inside(span: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    return any(start <= span[0] and span[1] <= end for start, end in spans)


def _diameters(description: str) -> list[dict[str, object]]:
    diameters: list[dict[str, object]] = []
    for match in DIAMETER_RE.finditer(description):
        raw = match.group("raw").strip()
        if match.group("dn"):
            value = _to_float(match.group("dn"))
            unit = "mm"
        elif match.group("after"):
            value = _to_float(match.group("after"))
            unit = (match.group("after_unit") or "cm").lower()
        else:
            value = _to_float(match.group("before"))
            unit = (match.group("before_unit") or "cm").lower()
        diameters.append(
            {
                "raw": raw,
                "unit": unit,
                "value": value,
                "value_mm": _to_mm(value, unit),
            }
        )
    return diameters

