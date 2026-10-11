from __future__ import annotations

from copy import deepcopy
import math
from typing import Any

from .api_service import (
    _catalogue_traceability,
    _has_pricing_fields,
    _normalise_position_payload,
    _productivity_traceability,
    build_baseline_warning,
    build_segmented_project_totals,
)
from .calculation_engine import by_key
from .position_parser import ExtractedPosition, _record_type_for_unit
from .product_matching import _catalogue_conflicts, calculate_matched_position


REVIEW_STATE_SCHEMA_VERSION = "phase8c.review_state.v1"
EDITABLE_UNITS = {"pc", "m", "m2", "h", "LS", "system"}
AUTHORIZED_STATUS = {"calculated", "supplier_quote_required"}
EXCLUDED_SOURCE_STATUS = {"review_required", "insufficient_information", "non_priceable"}
CRITICAL_CONFLICT_CODES = {
    "diameter_mismatch",
    "dimension_mismatch",
    "fire_rating_mismatch",
    "geometry_mismatch",
}
PRICING_FIELDS = (
    "net_unit_cost_chf",
    "material_cost_chf",
    "adjusted_install_hours",
    "labour_cost_chf",
    "direct_position_cost_chf",
)


class ReviewValidationError(ValueError):
    pass


def empty_review_state() -> dict[str, Any]:
    return {
        "schema_version": REVIEW_STATE_SCHEMA_VERSION,
        "positions": {},
    }


def validate_review_patch(
    base_position: dict[str, Any],
    patch: dict[str, Any],
    data: dict[str, Any],
) -> dict[str, Any]:
    allowed = {"quantity", "unit", "matched_product_id", "estimator_notes", "net_unit_cost_chf"}
    unknown = sorted(set(patch) - allowed)
    if unknown:
        raise ReviewValidationError(f"Unsupported review fields: {', '.join(unknown)}")

    normalized: dict[str, Any] = {}
    if "quantity" in patch:
        try:
            quantity = float(patch["quantity"])
        except (TypeError, ValueError) as exc:
            raise ReviewValidationError("Quantity must be a positive number.") from exc
        if not math.isfinite(quantity) or quantity <= 0:
            raise ReviewValidationError("Quantity must be greater than zero.")
        normalized["quantity"] = quantity

    if "net_unit_cost_chf" in patch:
        cost = patch["net_unit_cost_chf"]
        if cost is not None:
            try:
                cost = float(cost)
            except (TypeError, ValueError) as exc:
                raise ReviewValidationError("Unit cost must be a finite non-negative number.") from exc
            if not math.isfinite(cost) or cost < 0:
                raise ReviewValidationError("Unit cost must be a finite non-negative number.")
        normalized["net_unit_cost_chf"] = cost

    if "unit" in patch:
        unit = str(patch["unit"])
        if unit not in EDITABLE_UNITS:
            raise ReviewValidationError(f"Unsupported unit: {unit}")
        normalized["unit"] = unit

    if "matched_product_id" in patch:
        product_id = patch["matched_product_id"]
        if product_id is not None:
            catalog_by_id = by_key(data["catalog"], "product_id")
            if product_id not in catalog_by_id:
                raise ReviewValidationError(f"Unknown catalogue product_id: {product_id}")
            effective_unit = normalized.get("unit", base_position.get("unit"))
            if catalog_by_id[product_id]["unit"] != effective_unit:
                raise ReviewValidationError(
                    f"Product {product_id} uses unit {catalog_by_id[product_id]['unit']}, "
                    f"but the position unit is {effective_unit}."
                )
        normalized["matched_product_id"] = product_id

    if "estimator_notes" in patch:
        notes = "" if patch["estimator_notes"] is None else str(patch["estimator_notes"]).strip()
        if len(notes) > 1000:
            raise ReviewValidationError("Estimator notes must be 1000 characters or fewer.")
        normalized["estimator_notes"] = notes

    if not normalized:
        raise ReviewValidationError("At least one supported review field is required.")
    return normalized


def apply_review_state(
    result: dict[str, Any],
    data: dict[str, Any],
    review_state: dict[str, Any],
) -> dict[str, Any]:
    updated = deepcopy(result)
    positions = [
        apply_position_review(row, review_state.get("positions", {}).get(row["lv_id"], {}), data)
        for row in updated["positions"]
    ]
    updated["positions"] = positions
    updated["position_count"] = len(positions)
    updated["status_counts"] = _status_counts(positions)
    duplicate_rows = [row for row in positions if row.get("duplicate_group_id")]
    conflict_rows = [row for row in positions if row.get("conflict_flags")]
    updated["review_summary"] = {
        "review_required_rows": sum(1 for row in positions if row.get("review_required")),
        "conflict_flagged_rows": len(conflict_rows),
        "duplicate_candidate_rows": len(duplicate_rows),
        "duplicate_groups": len({row["duplicate_group_id"] for row in duplicate_rows}),
    }
    updated["project_totals"] = build_segmented_project_totals(positions, data["parameters"])
    updated["baseline_reconciliation_warning"] = build_baseline_warning(data)
    warnings = list(updated.get("warnings", []))
    limitation = "Estimator review overrides are stored locally with the in-memory job and are lost if job state is reset."
    if limitation not in warnings:
        warnings.append(limitation)
    updated["warnings"] = warnings
    return updated


def apply_position_review(
    base_row: dict[str, Any],
    review_entry: dict[str, Any],
    data: dict[str, Any],
) -> dict[str, Any]:
    row = deepcopy(base_row)
    _set_accepted_cost_fields(row)
    row["machine_values"] = _machine_values(base_row)
    row["review_state"] = {
        "has_overrides": bool(review_entry),
        "overridden_fields": sorted(key for key in review_entry if key != "net_unit_cost_chf" or review_entry[key] is not None),
        "estimator_notes": review_entry.get("estimator_notes", ""),
        "updated_at": review_entry.get("updated_at"),
        "pricing_authorized": row.get("pricing_authorized", False),
        "recalculation_status": "machine_result",
        "validation_flags": [],
    }
    if not review_entry:
        return row

    for key in ("quantity", "unit", "matched_product_id"):
        if key in review_entry:
            row[key] = review_entry[key]
    row["review_state"]["estimator_notes"] = review_entry.get("estimator_notes", "")
    row["review_state"]["updated_at"] = review_entry.get("updated_at")

    if row.get("matched_product_id") is None:
        _remove_cost_fields(row)
        row["catalogue_traceability"] = None
        row["productivity_traceability"] = None
        row["status"] = "review_required"
        row["review_required"] = True
        row["review_state"]["pricing_authorized"] = False
        row["review_state"]["recalculation_status"] = "product_match_cleared"
        _set_accepted_cost_fields(row)
        return row

    catalog_by_id = by_key(data["catalog"], "product_id")
    productivity_by_code = by_key(data["productivity"], "install_code")
    product = catalog_by_id[row["matched_product_id"]]
    install_code = product["install_code"]
    row["install_code"] = install_code
    row["price_source"] = product["source_type"]
    row["supplier_quote_required"] = product["supplier_quote_required"].strip().lower() == "true"
    row["catalogue_traceability"] = _catalogue_traceability(product)
    productivity = productivity_by_code.get(install_code)
    row["productivity_traceability"] = _productivity_traceability(productivity)
    if not productivity:
        _remove_cost_fields(row)
        row["status"] = "review_required"
        row["review_required"] = True
        row["review_state"]["pricing_authorized"] = False
        row["review_state"]["recalculation_status"] = "missing_productivity_rule"
        _set_accepted_cost_fields(row)
        return row

    position = _position_from_row(row)
    pricing_product = dict(product)
    if review_entry.get("net_unit_cost_chf") is not None:
        row["price_source"] = "estimator_override"
        pricing_product["net_cost_chf"] = str(review_entry["net_unit_cost_chf"])
    priced = calculate_matched_position(position, pricing_product, productivity, data["parameters"])
    conflicts = _merge_conflicts(base_row.get("conflict_flags", []), _catalogue_conflicts(position, product))
    row["conflict_flags"] = conflicts
    critical_conflicts = [flag for flag in conflicts if flag.get("code") in CRITICAL_CONFLICT_CODES]
    source_status = base_row.get("status")
    if row["supplier_quote_required"]:
        row.update(_supplier_basis_fields())
    else:
        row.update(_catalog_basis_fields())

    pricing_authorized = source_status not in EXCLUDED_SOURCE_STATUS and not critical_conflicts
    if row["supplier_quote_required"] and pricing_authorized:
        row.update(priced)
        row["status"] = "supplier_quote_required"
        row["review_required"] = True
        row["review_state"]["recalculation_status"] = "recalculated_provisional_supplier_estimate"
    elif pricing_authorized:
        row.update(priced)
        row["status"] = "calculated"
        row["review_required"] = False
        row["review_state"]["recalculation_status"] = "recalculated_confirmed_catalogue_estimate"
    else:
        _remove_cost_fields(row)
        row["override_cost_preview"] = priced
        row["status"] = source_status if source_status in {"insufficient_information", "non_priceable"} else "review_required"
        row["review_required"] = row["status"] != "non_priceable"
        row["review_state"]["validation_flags"] = conflicts
        if source_status in EXCLUDED_SOURCE_STATUS:
            row["review_state"]["recalculation_status"] = "preview_only_source_status_excluded_from_totals"
        else:
            row["review_state"]["recalculation_status"] = "preview_only_conflict_review_required"

    row["review_state"]["pricing_authorized"] = pricing_authorized
    if review_entry.get("net_unit_cost_chf") is not None:
        row["material_cost_basis"] = "estimator_net_unit_cost_override"
        row["direct_cost_basis"] = "estimator_material_estimate_plus_labour_estimate"
        if not row["supplier_quote_required"]:
            row["cost_confirmation_status"] = "estimator_cost_basis"
    _set_accepted_cost_fields(row)
    return _normalise_position_payload(row, data)


def _position_from_row(row: dict[str, Any]) -> ExtractedPosition:
    return ExtractedPosition(
        lv_id=row["lv_id"],
        source_page=int(row["source_page"]),
        system=row.get("system"),
        source_language=row.get("source_language", "de"),
        original_description=row.get("original_description", ""),
        description=row.get("description", row.get("original_description", "")),
        quantity=float(row["quantity"]),
        unit=row["unit"],
        original_unit=row.get("original_unit", row["unit"]),
        source_line=row.get("source_line", ""),
        evidence=row.get("evidence", ""),
        # Legacy results predate component/missing-quantity records; retain the parser's unit semantics.
        record_type=row.get("record_type", _record_type_for_unit(row.get("original_unit") or row["unit"])),
        technical_attributes=row.get("technical_attributes", {}),
    )


def _machine_values(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(row.get(key))
        for key in (
            "quantity",
            "unit",
            "matched_product_id",
            "install_code",
            "status",
            "net_unit_cost_chf",
            "material_cost_chf",
            "labour_cost_chf",
            "direct_position_cost_chf",
            "conflict_flags",
        )
    }


def _remove_cost_fields(row: dict[str, Any]) -> None:
    for key in PRICING_FIELDS:
        row.pop(key, None)


def _set_accepted_cost_fields(row: dict[str, Any]) -> None:
    authorized = row.get("status") in AUTHORIZED_STATUS and _has_pricing_fields(row)
    row["pricing_authorized"] = authorized
    for key in ("material_cost_chf", "labour_cost_chf", "direct_position_cost_chf"):
        accepted_key = "accepted_" + key
        row[accepted_key] = row.get(key) if authorized else None


def _merge_conflicts(
    existing: list[dict[str, str]],
    new: list[dict[str, str]],
) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for flag in [*existing, *new]:
        key = (flag.get("code", ""), flag.get("message", ""))
        if key not in seen:
            seen.add(key)
            merged.append(flag)
    return merged


def _catalog_basis_fields() -> dict[str, str]:
    return {
        "material_cost_basis": "catalogue_net_cost",
        "labour_cost_basis": "productivity_rule_estimate",
        "direct_cost_basis": "catalogue_material_estimate_plus_labour_estimate",
        "cost_confirmation_status": "confirmed_catalogue_cost_basis",
        "match_confirmation_status": "estimator_override_pending_audit",
    }


def _supplier_basis_fields() -> dict[str, str]:
    return {
        "material_cost_basis": "supplier_package_catalogue_estimate_pending_quote",
        "labour_cost_basis": "productivity_rule_estimate",
        "direct_cost_basis": "provisional_material_estimate_plus_labour_estimate",
        "cost_confirmation_status": "provisional_supplier_quote_required",
        "match_confirmation_status": "estimator_override_pending_supplier_review",
    }


def _status_counts(positions: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in positions:
        status = str(row.get("status"))
        counts[status] = counts.get(status, 0) + 1
    return counts

