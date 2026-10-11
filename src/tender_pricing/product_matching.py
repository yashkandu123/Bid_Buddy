from __future__ import annotations

import re
from dataclasses import replace
from decimal import Decimal
from typing import Any

from .calculation_engine import by_key, money, resolve_factor_multiplier
from .position_parser import ExtractedPosition
from .semantic_matching import (
    concepts_for_text,
    rank_semantic_candidates,
    repair_extraction_text,
    semantic_conflicts,
)


GERMAN_ENGLISH_SYNONYMS = {
    "tellerventil": "air valve diffuser",
    "zuluft": "supply air",
    "abluft": "exhaust air",
    "brandschutzklappe": "fire damper",
    "drosselklappen": "manual balancing damper",
    "schalldaempfer": "silencer acoustic",
    "schalldoempfer": "silencer acoustic",
    "volumenstromregler": "flow controller vav cav",
    "daemmung": "insulation",
    "daemmungen": "insulation",
    "durchdringungen": "penetration fire seal",
    "anschlusswinkle": "support connection angle",
    "revisisondeckel": "inspection cover",
    "revisionsdeckel": "inspection cover",
}


def match_positions(
    positions: list[ExtractedPosition],
    catalog: list[dict[str, str]],
    productivity: list[dict[str, str]],
    parameters: dict[str, Any],
    ai_provider: Any | None = None,
) -> list[dict[str, Any]]:
    catalog_by_id = by_key(catalog, "product_id")
    productivity_by_code = by_key(productivity, "install_code")
    matched = [
        match_and_price_position(position, catalog_by_id, productivity_by_code, parameters, ai_provider)
        for position in positions
    ]
    annotate_duplicate_candidates(matched)
    return matched


def classify_position(
    position: ExtractedPosition,
    catalog_by_id: dict[str, dict[str, str]],
    productivity_by_code: dict[str, dict[str, str]],
    parameters: dict[str, Any],
    ai_provider: Any | None = None,
) -> dict[str, Any]:
    product_id, confidence, method, reason = select_catalog_product(position, catalog_by_id, ai_provider)
    result: dict[str, Any] = {
        **position.to_dict(),
        "matched_product_id": product_id,
        "match_confidence": confidence,
        "match_method": method,
        "match_reason": reason,
        "classification": "priceable_candidate",
        "classification_reason_code": "matched_or_matchable_position" if product_id else "unclassified_unmatched",
        "classification_reason": "",
        "unmatched_specifications": [] if product_id else _unmatched_specifications(position),
        "conflict_flags": [],
        "review_required": confidence < 0.85,
        "status": "review_required" if product_id else "insufficient_information",
    }
    if not product_id:
        result.update(_insufficient_reason(position))
        return result

    product = catalog_by_id[product_id]
    install_code = product["install_code"]
    supplier_quote_required = product["supplier_quote_required"].strip().lower() == "true"
    result["install_code"] = install_code
    result["price_source"] = product["source_type"]
    result["supplier_quote_required"] = supplier_quote_required
    if supplier_quote_required:
        result["material_cost_basis"] = "supplier_package_catalogue_estimate_pending_quote"
        result["labour_cost_basis"] = "productivity_rule_estimate"
        result["direct_cost_basis"] = "provisional_material_estimate_plus_labour_estimate"
        result["cost_confirmation_status"] = "provisional_supplier_quote_required"
        result["match_confirmation_status"] = "candidate_for_estimator_and_supplier_review"
    else:
        result["material_cost_basis"] = "catalogue_net_cost"
        result["labour_cost_basis"] = "productivity_rule_estimate"
        result["direct_cost_basis"] = "catalogue_material_estimate_plus_labour_estimate"
        result["cost_confirmation_status"] = "confirmed_catalogue_cost_basis"
        result["match_confirmation_status"] = "confirmed_by_deterministic_rule_or_reference"

    if install_code not in productivity_by_code:
        result["status"] = "insufficient_information"
        result["review_required"] = True
        result["insufficient_reason_code"] = "missing_productivity_rule"
        result["insufficient_reason"] = f"No productivity rule for {install_code}"
        result["calculation_note"] = f"No productivity rule for {install_code}"
        return result

    conflict_flags = _catalogue_conflicts(position, product)
    result["conflict_flags"] = conflict_flags
    if supplier_quote_required:
        result["status"] = "supplier_quote_required"
        result["review_required"] = True
    elif conflict_flags:
        result["status"] = "review_required"
        result["review_required"] = True
        result["classification_reason_code"] = "technical_conflict_review_required"
        result["classification_reason"] = "One or more extracted technical attributes conflict with the selected catalogue item."
    elif confidence < 0.85:
        result["status"] = "review_required"
        result["review_required"] = True
    else:
        result["status"] = "calculated"
        result["review_required"] = False
    return result


def match_and_price_position(
    position: ExtractedPosition,
    catalog_by_id: dict[str, dict[str, str]],
    productivity_by_code: dict[str, dict[str, str]],
    parameters: dict[str, Any],
    ai_provider: Any | None = None,
) -> dict[str, Any]:
    result = classify_position(position, catalog_by_id, productivity_by_code, parameters, ai_provider)
    product = catalog_by_id.get(result.get("matched_product_id"))
    if product and product["install_code"] in productivity_by_code:
        result.update(calculate_matched_position(
            position, product, productivity_by_code[product["install_code"]], parameters
        ))
    return result


def matching_context(position: ExtractedPosition) -> str:
    """Keep evidence in the nearest product block; retain raw text on the result."""
    lines = position.description.splitlines()
    if len(lines) == 1:
        # Production parser joins lines; headings remain recognizable in this form.
        text = lines[0]
        pattern = r"(?:Zuluft|Abluft)\s*-\s*Tellerventil|Thermische Aussend[aä]mmung|Kanal-Aussend[aä]mmung|Durchdringungen durch|Revis[io]isondeckel|Revisionsdeckel|Anschlusswink(?:le|el)|Doppelwandige Blechkan[aä]le"
        headings = list(re.finditer(pattern, text, re.IGNORECASE))
        return text[headings[-1].start():] if headings else text
    starts = [i for i, line in enumerate(lines) if re.search(
        r"Tellerventil|Thermische Aussend[aä]mmung|Kanal-Aussend[aä]mmung|Durchdringungen durch|Revisisondeckel|Revisionsdeckel|Anschlusswink(?:le|el)|Doppelwandige Blechkan[aä]le", line, re.IGNORECASE
    )]
    return "\n".join(lines[starts[-1]:] if starts else lines)


def annotate_duplicate_candidates(rows: list[dict[str, Any]]) -> None:
    groups: dict[tuple[object, ...], list[dict[str, Any]]] = {}
    for row in rows:
        signature = (
            row["source_page"],
            row["source_line"],
            row["quantity"],
            row["unit"],
        )
        groups.setdefault(signature, []).append(row)

    for index, (signature, group) in enumerate(groups.items(), start=1):
        if len(group) == 1:
            group[0]["duplicate_group_id"] = None
            group[0]["duplicate_count"] = 1
            group[0]["duplicate_classification"] = "unique"
            group[0]["duplicate_review_required"] = False
            continue
        descriptions = {row["original_description"] for row in group}
        duplicate_classification = (
            "exact_duplicate_extraction" if len(descriptions) == 1 else "repeated_source_line_different_context"
        )
        review_required = duplicate_classification != "repeated_source_line_different_context"
        for row in group:
            row["duplicate_group_id"] = f"DUP-{index:03d}"
            row["duplicate_count"] = len(group)
            row["duplicate_classification"] = duplicate_classification
            row["duplicate_review_required"] = review_required
            if review_required and row["status"] == "calculated":
                row["status"] = "review_required"
                row["review_required"] = True
                row["classification_reason_code"] = "duplicate_extraction_review_required"
                row["classification_reason"] = "Exact duplicate extraction signature requires estimator review."


def calculate_matched_position(
    position: ExtractedPosition,
    product: dict[str, str],
    productivity: dict[str, str],
    parameters: dict[str, Any],
) -> dict[str, Any]:
    quantity = Decimal(str(position.quantity))
    net_unit_cost = Decimal(str(product["net_cost_chf"]))
    waste_multiplier = Decimal("1") + Decimal(str(parameters["allowances"]["material_waste_pct"])) / Decimal("100")
    material_cost = money(quantity * net_unit_cost * waste_multiplier)
    factor_multiplier = resolve_factor_multiplier(productivity["factor_keys"], parameters)
    install_hours = quantity * Decimal(str(productivity["base_hours_per_unit"])) * factor_multiplier
    labour_cost = money(install_hours * Decimal(str(productivity["default_hourly_rate_chf"])))

    return {
        "net_unit_cost_chf": float(net_unit_cost),
        "material_cost_chf": float(material_cost),
        "adjusted_install_hours": float(install_hours.quantize(Decimal("0.01"))),
        "labour_cost_chf": float(labour_cost),
        "direct_position_cost_chf": float(money(material_cost + labour_cost)),
    }


def select_catalog_product(
    position: ExtractedPosition,
    catalog_by_id: dict[str, dict[str, str]],
    ai_provider: Any | None = None,
) -> tuple[str | None, float, str, str]:
    if position.quantity <= 0:
        return None, 0.0, "unmatched", "missing or ambiguous quantity is not eligible for automatic catalogue pricing"
    if position.record_type in {"component_list_row", "labour_service"}:
        return None, 0.0, "unmatched", f"{position.record_type} is extracted for review only and is not eligible for automatic catalogue pricing"
    text = _normalise(matching_context(position))
    source_line = _normalise(position.source_line)
    expanded_text = _expand_german_synonyms(text)
    control = _control_candidate(source_line, text)
    if control is not None:
        if control in catalog_by_id and catalog_by_id[control]["unit"] == position.unit:
            return control, 0.7, "deterministic_cross_language", "German field-device candidate; catalogue omits technical specifications, estimator confirmation required"
        return None, 0.0, "unmatched", "field-device specifications are not covered by the catalogue"
    product_id = _rule_based_product_id(text, source_line, position.unit, position.source_line)
    if product_id and product_id in catalog_by_id and catalog_by_id[product_id]["unit"] == position.unit:
        return (
            product_id,
            _confidence_for_product(catalog_by_id[product_id]),
            "deterministic_cross_language",
            _match_reason(position, catalog_by_id[product_id]),
        )
    if _has_unsupported_specific_product_cue(text, source_line):
        return None, 0.0, "unmatched", "specific technical variant is not covered by the catalogue"

    semantic_source = (
        position.source_line
        if concepts_for_text(position.source_line)
        else matching_context(position)
    )
    semantic = rank_semantic_candidates(
        text=semantic_source,
        unit=position.unit,
        technical_attributes=position.technical_attributes,
        catalog=list(catalog_by_id.values()),
        limit=8,
    )
    if ai_provider is not None and semantic:
        assisted = _validated_ai_selection(position, catalog_by_id, ai_provider)
        if assisted is not None:
            return assisted
    semantic_with_family = [
        candidate for candidate in semantic
        if any(item.startswith("component type:") for item in candidate.evidence)
    ]
    exact_semantic = [
        candidate
        for candidate in semantic_with_family
        if _semantic_exact_match_is_safe(position, candidate, catalog_by_id[candidate.product_id])
    ]
    if len(exact_semantic) == 1:
        candidate = exact_semantic[0]
        return (
            candidate.product_id,
            0.9,
            "multilingual_exact_technical_match",
            "Unique multilingual component-family match with exact technical evidence; "
            + "; ".join(candidate.evidence),
        )
    if semantic_with_family:
        candidate = semantic_with_family[0]
        return (
            candidate.product_id,
            0.7,
            "multilingual_semantic_candidate",
            "Local German/English/French semantic retrieval for estimator review; "
            + "; ".join(candidate.evidence),
        )
    if concepts_for_text(position.source_line):
        return (
            None,
            0.0,
            "unmatched",
            "Local component family is not represented by a compatible catalogue product",
        )

    best_id: str | None = None
    best_score = 0
    for candidate_id, product in catalog_by_id.items():
        if product["unit"] != position.unit:
            continue
        score = _token_score(expanded_text, _normalise(" ".join([
            product["category"],
            product["subcategory"],
            product["description"],
            product["model"],
        ])))
        if score > best_score:
            best_score = score
            best_id = candidate_id

    if best_id and best_score >= 3:
        return best_id, 0.7, "synonym_token_match", f"German-English token match score {best_score}"
    return None, 0.0, "unmatched", "no defensible catalogue match"


def _semantic_exact_match_is_safe(
    position: ExtractedPosition,
    candidate: Any,
    product: dict[str, str],
) -> bool:
    required_prefixes: list[str] = []
    attributes = position.technical_attributes
    if attributes.get("dimensions"):
        required_prefixes.append("dimensions=")
    if attributes.get("diameters"):
        required_prefixes.append("diameter=")
    if attributes.get("fire_ratings"):
        required_prefixes.append("fire_rating=")
    if not required_prefixes and any(
        item.startswith("insulation_thickness=") for item in candidate.evidence
    ):
        required_prefixes.append("insulation_thickness=")
    if not required_prefixes or not all(
        any(item.startswith(prefix) for item in candidate.evidence)
        for prefix in required_prefixes
    ):
        return False
    if attributes.get("ambiguous_dimensions"):
        return False
    if _catalogue_conflicts(position, product):
        return False
    source_text = " ".join((position.original_description, position.source_line))
    return not semantic_conflicts(
        source_text=source_text,
        technical_attributes=position.technical_attributes,
        candidate=product,
    )


def _validated_ai_selection(
    position: ExtractedPosition,
    catalog_by_id: dict[str, dict[str, str]],
    provider: Any,
) -> tuple[str, float, str, str] | None:
    from .ai_matching_experiment import build_position_input, run_ai_matching_case

    record = position.to_dict()
    record.update({"status": "insufficient_information", "matched_product_id": None})
    result = run_ai_matching_case(build_position_input(record), list(catalog_by_id.values()), provider)
    validated = result.get("ai_result") or {}
    product_id = validated.get("recommended_product_id")
    if validated.get("safe_decision") != "accept" or product_id not in catalog_by_id:
        return None
    flags = validated.get("validation_flags", [])
    if flags:
        return None
    return (
        product_id,
        0.7,
        "validated_ai_candidate_review",
        "Provider selected a bounded catalogue candidate; deterministic validation passed; pricing remains review-only.",
    )


def _confidence_for_product(product: dict[str, str]) -> float:
    return 0.72 if product["supplier_quote_required"].strip().lower() == "true" else 0.9


def _normalise(value: str) -> str:
    value = repair_extraction_text(value).lower()
    value = re.sub(r"(?<=\d),(?=\d)", ".", value)
    replacements = {
        "?": "oe",
        "�": "oe",
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
        "`": "'",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    return re.sub(r"[^a-z0-9.]+", " ", value)


def _expand_german_synonyms(text: str) -> str:
    additions = [english for german, english in GERMAN_ENGLISH_SYNONYMS.items() if german in text]
    return " ".join([text, *additions])


def _match_reason(position: ExtractedPosition, product: dict[str, str]) -> str:
    attrs = position.technical_attributes
    evidence = [
        "German source text matched to English catalogue via deterministic technical cues",
        f"product_id={product['product_id']}",
        f"unit={position.unit}",
    ]
    if attrs.get("dimensions"):
        evidence.append(f"dimensions={attrs['dimensions']}")
    if attrs.get("model_code_dimensions"):
        evidence.append(f"model_code_dimensions={attrs['model_code_dimensions']}")
    if attrs.get("ambiguous_dimensions"):
        evidence.append(f"ambiguous_dimensions={attrs['ambiguous_dimensions']}")
    if attrs.get("diameters"):
        evidence.append(f"diameters={attrs['diameters']}")
    if attrs.get("fire_ratings"):
        evidence.append(f"fire_ratings={attrs['fire_ratings']}")
    if attrs.get("model_hints"):
        evidence.append(f"model_hints={attrs['model_hints']}")
    return "; ".join(evidence)


def _unmatched_specifications(position: ExtractedPosition) -> list[str]:
    specs: list[str] = []
    attrs = position.technical_attributes
    for key in (
        "dimensions",
        "model_code_dimensions",
        "ambiguous_dimensions",
        "diameters",
        "fire_ratings",
        "materials",
        "model_hints",
    ):
        value = attrs.get(key)
        if value:
            specs.append(f"{key}={value}")
    return specs


def _catalogue_conflicts(position: ExtractedPosition, product: dict[str, str]) -> list[dict[str, str]]:
    from .position_parser import _technical_attributes
    context = matching_context(position)
    position = replace(position, technical_attributes=_technical_attributes(context))
    conflicts: list[dict[str, str]] = []
    product_text = _normalise(" ".join([product["model"], product["description"]]))
    source_text = " ".join([position.original_description, position.source_line])
    attrs = position.technical_attributes
    normalized_source = _normalise(source_text)
    if "polyurethan" in normalized_source and "polyurethan" not in product_text:
        conflicts.append(
            {
                "code": "material_not_confirmed",
                "message": (
                    "Tender specifies polyurethane construction, which is not confirmed "
                    "by the catalogue candidate."
                ),
            }
        )
    source_angles = _bend_angles(position.source_line, matching_context(position))
    product_angles = _catalogue_bend_angles(product)
    if source_angles and product_angles and source_angles.isdisjoint(product_angles):
        conflicts.append(
            {
                "code": "bend_angle_mismatch",
                "message": (
                    f"Extracted bend angles {sorted(source_angles)} degrees do not match "
                    f"catalogue bend angles {sorted(product_angles)} degrees."
                ),
            }
        )
    if re.search(r"\d+\s+St(?:ue|ü)ck pro Durchf", context, re.IGNORECASE):
        conflicts.append({"code": "quantity_basis_requires_confirmation", "message": "Source counts penetrations and specifies multiple angles per penetration; catalogue set scope must be confirmed."})
    if "KOSD" in context and re.search(r"L[aä]nge\s+[?Ø]", context):
        row_length = re.match(r"\s*(\d+(?:[.,]\d+)?)\s+", position.source_line)
        model_length = re.search(r"KOSD\s+\d+/(\d+)", context)
        if row_length and model_length and "cm cm cm" in context:
            if float(row_length[1].replace(",", ".")) * 10 != float(model_length[1]):
                conflicts.append({"code": "model_length_conflict", "message": "Compact silencer length column (cm) contradicts the model length (mm); estimator confirmation required."})
    ambiguous_dimensions = attrs.get("ambiguous_dimensions", [])
    if ambiguous_dimensions:
        conflicts.append(
            {
                "code": "ambiguous_dimension_unit",
                "message": f"Extracted dimensions without explicit/contextual unit require review: {ambiguous_dimensions}.",
            }
        )

    source_line_diameters = _source_line_diameters_mm(position.source_line)
    position_diameters = source_line_diameters or [
        float(diameter["value_mm"])
        for diameter in attrs.get("diameters", [])
        if isinstance(diameter, dict) and "value_mm" in diameter
    ]
    product_diameters = _catalogue_diameters_mm(product_text)
    if position_diameters and product_diameters and not _any_close_match(position_diameters, product_diameters):
        conflicts.append(
            {
                "code": "diameter_mismatch",
                "message": f"Extracted diameters {position_diameters} mm do not match catalogue diameters {product_diameters} mm.",
            }
        )

    source_line_dimensions = _source_line_dimensions_mm(position.source_line, source_text)
    position_dimensions = source_line_dimensions or [
        tuple(float(value) for value in dimension["values_mm"])
        for dimension in attrs.get("dimensions", [])
        if isinstance(dimension, dict) and "values_mm" in dimension
    ]
    product_dimensions = _catalogue_dimensions_mm(product_text)
    if position_diameters and product_dimensions and not product_diameters:
        conflicts.append(
            {
                "code": "geometry_mismatch",
                "message": (
                    f"Extracted round/diameter evidence {position_diameters} mm conflicts with "
                    f"catalogue rectangular dimensions {product_dimensions}."
                ),
            }
        )
    if position_dimensions and product_dimensions and not _any_dimension_match(position_dimensions, product_dimensions):
        conflicts.append(
            {
                "code": "dimension_mismatch",
                "message": f"Extracted dimensions {position_dimensions} mm do not match catalogue dimensions {product_dimensions} mm.",
            }
        )

    position_fire_ratings = {_normalise_fire_rating(str(value)) for value in attrs.get("fire_ratings", [])}
    product_fire_ratings = set(_fire_ratings(source_text=" ".join([product["model"], product["description"]])))
    if position_fire_ratings and product_fire_ratings and position_fire_ratings.isdisjoint(product_fire_ratings):
        conflicts.append(
            {
                "code": "fire_rating_mismatch",
                "message": f"Extracted fire ratings {sorted(position_fire_ratings)} do not match catalogue fire ratings {sorted(product_fire_ratings)}.",
            }
        )
    existing_codes = {flag["code"] for flag in conflicts}
    for flag in semantic_conflicts(
        source_text=source_text,
        technical_attributes=attrs,
        candidate=product,
    ):
        if flag["code"] not in existing_codes:
            conflicts.append(flag)
            existing_codes.add(flag["code"])
    return conflicts


def _bend_angles(source_line: str, context: str) -> set[float]:
    text = f"{source_line} {context}"
    if not re.search(r"\b(?:bogen|bend|coude)\b", text, re.IGNORECASE):
        return set()
    return {
        float(match.group(1).replace(",", "."))
        for match in re.finditer(r"\b(\d+(?:[.,]\d+)?)\s*(?:°|�)", text)
    }


def _catalogue_bend_angles(product: dict[str, str]) -> set[float]:
    text = " ".join((product.get("model", ""), product.get("description", "")))
    if not re.search(r"\b(?:bend|bogen|coude|B\d+[- ])", text, re.IGNORECASE):
        return set()
    angles = {
        float(match.group(1))
        for match in re.finditer(r"\b(\d+(?:\.\d+)?)\s*°", text)
    }
    angles.update(
        float(match.group(1))
        for match in re.finditer(r"\bB(\d{2,3})[- ]", text, re.IGNORECASE)
    )
    return angles


def _catalogue_diameters_mm(text: str) -> list[float]:
    diameters: set[float] = set()
    for match in re.finditer(r"\bdn\s*(\d+(?:\.\d+)?)\b", text):
        diameters.add(float(match.group(1)))
    for match in re.finditer(r"\b(?:cav|vav|dv [za]|fd ei90|fs c|sp|b\d+|md)[ -](\d{2,4})(?:\b|x)", text):
        value = float(match.group(1))
        if 50 <= value <= 1000:
            diameters.add(value)
    return sorted(diameters)


def _source_line_diameters_mm(text: str) -> list[float]:
    diameters: set[float] = set()
    for match in re.finditer(r"\bdn\s*(\d+(?:[.,]\d+)?)\b", text, re.IGNORECASE):
        diameters.add(float(match.group(1).replace(",", ".")))
    for match in re.finditer(r"[?Ø�]\s*(\d+(?:[.,]\d+)?)\s*(mm|cm)?\b", text, re.IGNORECASE):
        value = float(match.group(1).replace(",", "."))
        unit = (match.group(2) or "cm").lower()
        diameters.add(value * 10 if unit == "cm" else value)
    for match in re.finditer(r"\b(\d+(?:[.,]\d+)?)\s*[?Ø�]\s*(mm|cm)?\b", text, re.IGNORECASE):
        value = float(match.group(1).replace(",", "."))
        unit = (match.group(2) or "cm").lower()
        diameters.add(value * 10 if unit == "cm" else value)
    return sorted(diameters)


def _catalogue_dimensions_mm(text: str) -> list[tuple[float, ...]]:
    dimensions: list[tuple[float, ...]] = []
    for match in re.finditer(r"\b(\d{2,4})x(\d{2,4})(?:x(\d{2,4}))?\b", text):
        values = [float(match.group(1)), float(match.group(2))]
        if match.group(3):
            values.append(float(match.group(3)))
        dimensions.append(tuple(values))
    return dimensions


def _source_line_dimensions_mm(text: str, source_context: str) -> list[tuple[float, ...]]:
    dimensions: list[tuple[float, ...]] = []
    default_unit = "mm" if re.search(r"\bmm\b|\(mm\)", source_context, re.IGNORECASE) else "cm"
    for match in re.finditer(
        r"\b(\d+(?:[.,]\d+)?)\s*x\s*(\d+(?:[.,]\d+)?)(?:\s*x\s*(\d+(?:[.,]\d+)?))?\s*(mm|cm)?\b",
        text,
        re.IGNORECASE,
    ):
        unit = (match.group(4) or default_unit).lower()
        multiplier = 10 if unit == "cm" else 1
        values = [
            float(value.replace(",", ".")) * multiplier
            for value in (match.group(1), match.group(2), match.group(3))
            if value
        ]
        dimensions.append(tuple(values))
    return dimensions


def _fire_ratings(source_text: str) -> list[str]:
    return [match.group(0).upper().replace(" ", "").replace("-", "") for match in re.finditer(r"\bEI\s*-?\s*\d+(?:-S)?\b", source_text, re.IGNORECASE)]


def _normalise_fire_rating(value: str) -> str:
    return value.upper().replace(" ", "").replace("-", "")


def _any_close_match(left: list[float], right: list[float], tolerance_mm: float = 1.0) -> bool:
    return any(abs(left_value - right_value) <= tolerance_mm for left_value in left for right_value in right)


def _any_dimension_match(
    position_dimensions: list[tuple[float, ...]],
    product_dimensions: list[tuple[float, ...]],
    tolerance_mm: float = 2.0,
) -> bool:
    for extracted in position_dimensions:
        for catalogue in product_dimensions:
            if len(extracted) != len(catalogue):
                continue
            if all(abs(left - right) <= tolerance_mm for left, right in zip(extracted, catalogue)):
                return True
            if all(abs(left - right) <= tolerance_mm for left, right in zip(sorted(extracted), sorted(catalogue))):
                return True
    return False


def _rule_based_product_id(text: str, source_line: str, unit: str, raw_source_line: str) -> str | None:
    combined = f"{text} {source_line}"
    diameters = _source_line_diameters_mm(raw_source_line)
    if unit == "pc":
        variant = re.match(r"tvr d (12\.5|16|20)\b", source_line)
        if variant:
            return {"12.5": "P-VAV-003", "16": "P-VAV-004", "20": "P-VAV-005"}[variant[1]]
        if "vfc" in text and re.match(r"\.*\s*250\s", source_line) and "mod. dn" in text and "mm m3" in text:
            return "P-CAV-001"
        if "durchdringungen" in text and "ei30" in text:
            if re.search(r"\b16\s+(?:oe\s+)?cm\b", source_line):
                return "P-FIR-003"
            if re.search(r"\b300 x 200\b", source_line):
                return "P-FIR-002"
    if unit == "m2":
        thicknesses = list(re.finditer(r"thermische aussend(?:ae|oe)mmung (30|60|100)\b", text))
        if thicknesses:
            return {"30": "P-INS-001", "60": "P-INS-002", "100": "P-INS-003"}[thicknesses[-1][1]]
    if unit == "pc":
        if "tellerventil" in combined and "zuluft" in combined:
            if 125 in diameters:
                return "P-AIR-002"
            if 100 in diameters:
                return "P-AIR-001"
        if "tellerventil" in combined and "abluft" in combined and 100 in diameters:
            return "P-AIR-003"
        if "brandschutzklappe" in combined or "fkrs" in combined or "fk2" in combined:
            return "P-FIR-001"
        if "drosselklappe" in combined and 125 in diameters:
            return "P-DAM-001"
        if "schalldoempfer" in combined or "schalld" in combined or "ms f" in combined or "kulissen" in combined:
            if "40 x 30 x 125" in combined or "300x400x1250" in combined:
                return "P-SIL-001"
            if (
                "kosd 100 900" in combined
                or "28.5x20.5" in source_line
                or "28.5 x 20.5" in source_line
            ):
                return "P-SIL-002"
            if "60 x 60 x 175" in combined or "600x600x1750" in combined:
                return "P-SIL-003"
            if "54 x 40 x 125" in combined or "540x400x1250" in combined:
                return "P-SIL-004"
        if "volumenstromregler" in combined or "vvs" in combined or "tvj d" in combined or "tvr d" in combined or "bm0" in source_line:
            if "50x30" in combined or "500x300" in combined or "bm0 50x30" in combined:
                return "P-VAV-001"
            if "30x20" in combined or "300x200" in combined or "tvj d 30x20" in combined:
                return "P-VAV-002"
            if source_line.startswith("tvr d 12.5"):
                return "P-VAV-003"
            if source_line.startswith("tvr d 16"):
                return "P-VAV-004"
            if source_line.startswith("tvr d 20"):
                return "P-VAV-005"
            if "vfc" in combined and 250 in diameters:
                return "P-CAV-001"
        if "300 x 200" in combined and (
            "ei30" in combined or "durchdringungen" in combined or "kanalverstaerkungs" in combined
        ):
            return "P-FIR-002"
        if ("16 oe cm" in combined or "16 cm" in combined) and (
            "ei30" in combined or "durchdringungen" in combined
        ):
            return "P-FIR-003"
        if "anschlusswinkle" in combined or "anschlusswinkel" in combined:
            return "P-SUP-001"
        if "400 x 200" in combined and ("revisisondeckel" in combined or "revisionsdeckel" in combined):
            return "P-FIR-004"
    if unit == "m2":
        if "thermische aussendoemmung 30" in combined or "thermische aussendaemmung 30" in combined:
            return "P-INS-001"
        if "thermische aussendoemmung 60" in combined or "thermische aussendaemmung 60" in combined:
            return "P-INS-002"
        if (
            "wetterfeste ummantelung" in combined
            or "thermische aussendoemmung 100" in combined
            or "thermische aussendaemmung 100" in combined
        ):
            return "P-INS-003"
    return None


def _token_score(left: str, right: str) -> int:
    left_tokens = {token for token in left.split() if len(token) > 2}
    right_tokens = {token for token in right.split() if len(token) > 2}
    return len(left_tokens & right_tokens)


def _insufficient_reason(position: ExtractedPosition) -> dict[str, Any]:
    text = _normalise(" ".join([position.original_description, position.source_line]))
    attrs = position.technical_attributes
    if position.record_type == "component_list_row":
        return {
            "classification": "ambiguous_priceable_candidate",
            "classification_reason_code": "component_list_requires_assumption_or_catalogue_rule",
            "classification_reason": "Bauteilliste Lüftung row was extracted with source evidence, but no deterministic catalogue/pricing rule exists for component-list rows.",
            "insufficient_reason_code": "component_list_requires_assumption_or_catalogue_rule",
            "insufficient_reason": "Component-list row requires estimator review or an explicit assumption/pricing rule before pricing.",
        }
    if position.record_type == "labour_service":
        return {
            "classification": "ambiguous_priceable_candidate",
            "classification_reason_code": "labour_service_requires_productivity_rule",
            "classification_reason": "Labour-service row was extracted, but no deterministic service pricing rule exists for this tender line.",
            "insufficient_reason_code": "labour_service_requires_productivity_rule",
            "insufficient_reason": "Labour-service row requires estimator review or an explicit productivity rule before pricing.",
        }
    if position.quantity <= 0 or not position.unit:
        return {
            "classification": "ambiguous_extraction",
            "classification_reason_code": "missing_or_ambiguous_quantity_unit",
            "classification_reason": "Quantity or unit is missing or invalid after parsing.",
            "insufficient_reason_code": "missing_or_ambiguous_quantity_unit",
            "insufficient_reason": "Quantity or unit is missing or invalid after parsing.",
        }
    if _looks_non_priceable_or_assembly(text):
        return {
            "status": "non_priceable",
            "review_required": False,
            "classification": "confirmed_non_priceable",
            "classification_reason_code": "non_priceable_or_assembly_entry",
            "classification_reason": "Explicit German source markers indicate a heading, surcharge, total, table note or assembly/detail row rather than a standalone priceable item.",
            "insufficient_reason_code": "non_priceable_or_assembly_entry",
            "insufficient_reason": "Row appears to be a heading, surcharge, total, accessory, table note or assembly component rather than a standalone catalogue item.",
        }
    if (
        attrs.get("dimensions")
        or attrs.get("diameters")
        or attrs.get("fire_ratings")
        or attrs.get("model_hints")
        or _has_technical_product_term(text)
    ):
        return {
            "classification": "ambiguous_priceable_candidate",
            "classification_reason_code": "no_plausible_catalogue_match",
            "classification_reason": "Technical information exists, but no supplied catalogue item matched it defensibly.",
            "insufficient_reason_code": "no_plausible_catalogue_match",
            "insufficient_reason": "Technical attributes were extracted but no catalogue product matched them defensibly.",
        }
    return {
        "classification": "ambiguous_extraction",
        "classification_reason_code": "parsing_incomplete_or_low_context",
        "classification_reason": "Parsed quantity/unit exists, but surrounding German context is too weak for reliable product matching.",
        "insufficient_reason_code": "parsing_incomplete_or_low_context",
        "insufficient_reason": "The row has a parsed quantity/unit but insufficient surrounding context for a defensible match.",
    }


def _looks_non_priceable_or_assembly(text: str) -> bool:
    markers = (
        "sonderfarbzuschlag",
        "farbbeschichtung",
        "farbe ncs",
        "total aller",
        "einregulierung",
        "inbetriebsetzen",
        "nachkontrolle",
        "anzahl kulissen",
        "druckverlust",
        "schallleistungspegel",
        "verlaengerung",
        "sockelrohr",
        "standrohr",
        "kulissendicke",
        "spaltbreite",
        "luftmenge",
        "dokumentation",
        "protokoll",
    )
    return any(marker in text for marker in markers)


def _has_unsupported_specific_product_cue(text: str, source_line: str) -> bool:
    if "vfc" in text:
        return True
    if "rohrschalldaempfer" in text or "rohrschalldoempfer" in text:
        return True
    return False


def _control_candidate(source_line: str, context: str) -> str | None:
    # These are review candidates, not specification-complete equivalences.
    if "druckdifferenzfuehler" in source_line:
        return "P-CTL-001"
    if "temperatur" in source_line and "fuehler" in source_line:
        return "" if "feuchte" in source_line else "P-CTL-002"
    if "volumenstromfuehler" in source_line:
        return "P-CTL-004"
    if "drehantrieb" in source_line or "stellantrieb" in source_line:
        voltages = set(re.findall(r"\b(\d+)\s*v\b", context))
        return "P-CTL-003" if voltages == {"24"} else ""
    if "druckwaechter" in source_line or "frostschutzwaechter" in source_line:
        return ""  # A switch is not a pressure/temperature transmitter.
    return None


def _has_technical_product_term(text: str) -> bool:
    terms = (
        "tellerventil",
        "brandschutzklappe",
        "drosselklappe",
        "schalldaempfer",
        "schalldoempfer",
        "rohrschalldaempfer",
        "rohrschalldoempfer",
        "volumenstromregler",
        "daemmung",
        "durchdringung",
        "vfc",
        "vfr",
        "tvr",
        "tvj",
    )
    return any(term in text for term in terms)

