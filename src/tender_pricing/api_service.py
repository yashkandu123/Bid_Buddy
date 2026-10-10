from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .calculation_engine import (
    calculate_example_summary,
    calculate_positions,
    calculate_project_cost_breakdown,
    validate_against_reference,
)
from .data_loading import load_project_data


API_SCHEMA_VERSION = "phase4.v1"
EXAMPLE_DATASET_ID = "verified_examples"
FULL_TENDER_OUTPUT_ID = "phase2_full"
FULL_TENDER_OUTPUT_PATH = Path("outputs") / "phase2_full" / "priced_positions.json"
CONFIRMED_TOTAL_STATUSES = {"calculated"}
PROVISIONAL_TOTAL_STATUSES = {"supplier_quote_required"}
TOTAL_INCLUDED_STATUSES = CONFIRMED_TOTAL_STATUSES | PROVISIONAL_TOTAL_STATUSES


def build_health_response() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "tender-pricing-api",
        "schema_version": API_SCHEMA_VERSION,
    }


def build_verified_examples_response(project_root: Path) -> dict[str, Any]:
    data = load_project_data(project_root)
    calculated_positions = calculate_positions(data)
    summary = calculate_example_summary(calculated_positions, data["parameters"])
    breakdown = calculate_project_cost_breakdown(calculated_positions, data["parameters"])
    validation = validate_against_reference(calculated_positions, summary, data["expected"])
    full_rows = _load_optional_full_output(project_root)
    full_rows_by_example = _link_full_rows_to_examples(full_rows, data["examples"])

    examples_by_id = {row["lv_id"]: row for row in data["examples"]}
    enriched_positions = [
        _normalise_position_payload(
            {
                **position,
                "system": examples_by_id[position["lv_id"]]["system"],
                "reference_description_en": examples_by_id[position["lv_id"]]["description"],
                "original_description": _linked_value(
                    full_rows_by_example.get(position["lv_id"]),
                    "original_description",
                    examples_by_id[position["lv_id"]]["description"],
                ),
                "description": _linked_value(
                    full_rows_by_example.get(position["lv_id"]),
                    "description",
                    examples_by_id[position["lv_id"]]["description"],
                ),
                "source_language": "de" if full_rows_by_example.get(position["lv_id"]) else "en_reference",
                "original_unit": _linked_value(
                    full_rows_by_example.get(position["lv_id"]),
                    "original_unit",
                    position["unit"],
                ),
                "source_line": _linked_value(full_rows_by_example.get(position["lv_id"]), "source_line", ""),
                "evidence": _linked_value(full_rows_by_example.get(position["lv_id"]), "evidence", ""),
                "technical_attributes": _linked_value(
                    full_rows_by_example.get(position["lv_id"]),
                    "technical_attributes",
                    {},
                ),
                "match_method": _linked_value(
                    full_rows_by_example.get(position["lv_id"]),
                    "match_method",
                    "verified_reference",
                ),
                "match_reason": _linked_value(
                    full_rows_by_example.get(position["lv_id"]),
                    "match_reason",
                    "Verified example row matched through supplied reference data.",
                ),
                "classification": _linked_value(
                    full_rows_by_example.get(position["lv_id"]),
                    "classification",
                    "priceable_candidate",
                ),
                "classification_reason_code": _linked_value(
                    full_rows_by_example.get(position["lv_id"]),
                    "classification_reason_code",
                    "verified_example_reference",
                ),
                "classification_reason": _linked_value(
                    full_rows_by_example.get(position["lv_id"]),
                    "classification_reason",
                    "Verified example row from supplied reference dataset.",
                ),
                "unmatched_specifications": _linked_value(
                    full_rows_by_example.get(position["lv_id"]),
                    "unmatched_specifications",
                    [],
                ),
                "conflict_flags": _linked_value(full_rows_by_example.get(position["lv_id"]), "conflict_flags", []),
                "duplicate_group_id": _linked_value(
                    full_rows_by_example.get(position["lv_id"]),
                    "duplicate_group_id",
                    None,
                ),
                "duplicate_count": _linked_value(full_rows_by_example.get(position["lv_id"]), "duplicate_count", 1),
                "duplicate_classification": _linked_value(
                    full_rows_by_example.get(position["lv_id"]),
                    "duplicate_classification",
                    "unique",
                ),
                "duplicate_review_required": _linked_value(
                    full_rows_by_example.get(position["lv_id"]),
                    "duplicate_review_required",
                    False,
                ),
            },
            data,
        )
        for position in calculated_positions
    ]

    return {
        "schema_version": API_SCHEMA_VERSION,
        "dataset_id": EXAMPLE_DATASET_ID,
        "scope": "Verified 22-position example subset; not the full tender.",
        "positions": enriched_positions,
        "position_count": len(enriched_positions),
        "status_counts": dict(Counter(row["status"] for row in enriched_positions)),
        "project_totals": build_segmented_project_totals(enriched_positions, data["parameters"]),
        "validation": validation,
        "baseline_reconciliation_warning": build_baseline_warning(data),
        "warnings": _example_traceability_warnings(full_rows_by_example, data["examples"]),
    }


def build_full_tender_output_response(project_root: Path) -> dict[str, Any]:
    data = load_project_data(project_root)
    output_path = project_root / FULL_TENDER_OUTPUT_PATH
    if not output_path.exists():
        raise FileNotFoundError(f"Required Phase 2 output is missing: {FULL_TENDER_OUTPUT_PATH}")

    rows = json.loads(output_path.read_text(encoding="utf-8"))
    positions = [_normalise_position_payload(row, data) for row in rows]
    status_counts = Counter(row["status"] for row in positions)
    duplicate_rows = [row for row in positions if row.get("duplicate_group_id")]
    conflict_rows = [row for row in positions if row.get("conflict_flags")]

    return {
        "schema_version": API_SCHEMA_VERSION,
        "dataset_id": FULL_TENDER_OUTPUT_ID,
        "scope": "Existing Phase 2 full-tender extraction output; no new PDF extraction performed.",
        "source_output": str(FULL_TENDER_OUTPUT_PATH).replace("\\", "/"),
        "positions": positions,
        "position_count": len(positions),
        "status_counts": dict(status_counts),
        "review_summary": {
            "review_required_rows": sum(1 for row in positions if row.get("review_required")),
            "conflict_flagged_rows": len(conflict_rows),
            "duplicate_candidate_rows": len(duplicate_rows),
            "duplicate_groups": len({row["duplicate_group_id"] for row in duplicate_rows}),
        },
        "project_totals": build_segmented_project_totals(positions, data["parameters"]),
        "baseline_reconciliation_warning": build_baseline_warning(data),
        "warnings": [
            "Combined estimate totals include confirmed calculated rows plus provisional supplier_quote_required rows.",
            "Confirmed totals exclude supplier_quote_required rows because supplier quotes remain outstanding.",
            "Rows marked review_required, insufficient_information or non_priceable are excluded from both confirmed and provisional totals.",
        ],
    }


def build_segmented_project_totals(
    positions: list[dict[str, Any]],
    parameters: dict[str, Any],
) -> dict[str, Any]:
    confirmed_rows = [
        row
        for row in positions
        if row.get("status") in CONFIRMED_TOTAL_STATUSES and _has_pricing_fields(row)
    ]
    provisional_rows = [
        row
        for row in positions
        if row.get("status") in PROVISIONAL_TOTAL_STATUSES and _has_pricing_fields(row)
    ]
    combined_rows = confirmed_rows + provisional_rows
    excluded_count = len(positions) - len(combined_rows)
    confirmed = _project_totals_payload(
        rows=confirmed_rows,
        parameters=parameters,
        included_statuses=sorted(CONFIRMED_TOTAL_STATUSES),
        excluded_position_count=len(positions) - len(confirmed_rows),
        label="confirmed_costs_only",
    )
    provisional = _project_totals_payload(
        rows=provisional_rows,
        parameters=parameters,
        included_statuses=sorted(PROVISIONAL_TOTAL_STATUSES),
        excluded_position_count=len(positions) - len(provisional_rows),
        label="provisional_supplier_package_estimates",
    )
    combined = _project_totals_payload(
        rows=combined_rows,
        parameters=parameters,
        included_statuses=sorted(TOTAL_INCLUDED_STATUSES),
        excluded_position_count=excluded_count,
        label="combined_confirmed_and_provisional_estimate",
    )
    return {
        "summary": combined["summary"],
        "breakdown": combined["breakdown"],
        "included_position_count": combined["included_position_count"],
        "excluded_position_count": combined["excluded_position_count"],
        "included_statuses": combined["included_statuses"],
        "formula_note": combined["formula_note"],
        "confirmed": confirmed,
        "provisional": provisional,
        "combined_estimate": combined,
        "supplier_quotes_outstanding": len(provisional_rows),
        "supplier_quote_note": (
            "Supplier-package net costs come from catalog.csv as provisional estimates. "
            "They are not confirmed supplier quotes; labour remains estimated from productivity rules."
        ),
    }


def build_baseline_warning(data: dict[str, Any]) -> dict[str, Any]:
    positions = calculate_positions(data)
    summary = calculate_example_summary(positions, data["parameters"])
    expected = data["expected"]["example_subset_summary"]["cost_baseline_chf"]
    actual = summary["cost_baseline_chf"]
    difference = round(float(expected) - float(actual), 2)
    return {
        "code": "unresolved_reference_baseline_discrepancy",
        "severity": "warning",
        "documented_in": "BASELINE_RECONCILIATION.md",
        "current_formula_cost_baseline_chf": actual,
        "expected_reference_cost_baseline_chf": expected,
        "difference_chf": difference,
        "message": (
            "The supplied sources do not establish a unique project-level formula that reproduces "
            "the expected CHF 414,489.12 baseline. Position-level golden results remain unchanged."
        ),
    }


def _normalise_position_payload(row: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    catalog_by_id = {item["product_id"]: item for item in data["catalog"]}
    productivity_by_code = {item["install_code"]: item for item in data["productivity"]}
    product_id = row.get("matched_product_id")
    install_code = row.get("install_code")
    product = catalog_by_id.get(product_id) if product_id else None
    productivity = productivity_by_code.get(install_code) if install_code else None
    payload = dict(row)
    payload.setdefault("system", None)
    payload.setdefault("source_language", "de")
    payload.setdefault("original_description", payload.get("description", ""))
    payload.setdefault("description", payload.get("original_description", ""))
    payload.setdefault("original_unit", payload.get("unit"))
    payload.setdefault("source_line", "")
    payload.setdefault("evidence", "")
    payload.setdefault("technical_attributes", {})
    payload.setdefault("match_method", "verified_reference" if product_id else "unmatched")
    payload.setdefault("match_reason", "")
    payload.setdefault("classification", "priceable_candidate" if product_id else "ambiguous_extraction")
    payload.setdefault("classification_reason_code", "matched_or_matchable_position" if product_id else "")
    payload.setdefault("classification_reason", "")
    payload.setdefault("unmatched_specifications", [])
    payload.setdefault("conflict_flags", [])
    payload.setdefault("duplicate_group_id", None)
    payload.setdefault("duplicate_count", 1)
    payload.setdefault("duplicate_classification", "unique")
    payload.setdefault("duplicate_review_required", False)
    supplier_quote_required = bool(
        payload.get("supplier_quote_required")
        or (product and product["supplier_quote_required"].strip().lower() == "true")
    )
    payload["supplier_quote_required"] = supplier_quote_required
    if supplier_quote_required:
        payload.setdefault("material_cost_basis", "supplier_package_catalogue_estimate_pending_quote")
        payload.setdefault("labour_cost_basis", "productivity_rule_estimate")
        payload.setdefault("direct_cost_basis", "provisional_material_estimate_plus_labour_estimate")
        payload.setdefault("cost_confirmation_status", "provisional_supplier_quote_required")
        payload.setdefault("match_confirmation_status", "candidate_for_estimator_and_supplier_review")
    elif product_id:
        payload.setdefault("material_cost_basis", "catalogue_net_cost")
        payload.setdefault("labour_cost_basis", "productivity_rule_estimate")
        payload.setdefault("direct_cost_basis", "catalogue_material_estimate_plus_labour_estimate")
        payload.setdefault("cost_confirmation_status", "confirmed_catalogue_cost_basis")
        payload.setdefault("match_confirmation_status", "confirmed_by_deterministic_rule_or_reference")
    pricing_authorized = payload.get("status") in TOTAL_INCLUDED_STATUSES and _has_pricing_fields(payload)
    payload["pricing_authorized"] = pricing_authorized
    payload.setdefault("accepted_material_cost_chf", payload.get("material_cost_chf") if pricing_authorized else None)
    payload.setdefault("accepted_labour_cost_chf", payload.get("labour_cost_chf") if pricing_authorized else None)
    payload.setdefault(
        "accepted_direct_position_cost_chf",
        payload.get("direct_position_cost_chf") if pricing_authorized else None,
    )
    payload.setdefault(
        "review_state",
        {
            "has_overrides": False,
            "overridden_fields": [],
            "estimator_notes": "",
            "updated_at": None,
            "pricing_authorized": pricing_authorized,
            "recalculation_status": "machine_result",
            "validation_flags": [],
        },
    )
    payload["catalogue_traceability"] = _catalogue_traceability(product)
    payload["productivity_traceability"] = _productivity_traceability(productivity)
    return payload


def _catalogue_traceability(product: dict[str, str] | None) -> dict[str, Any] | None:
    if not product:
        return None
    return {
        "product_id": product["product_id"],
        "category": product["category"],
        "subcategory": product["subcategory"],
        "manufacturer": product["manufacturer"],
        "model": product["model"],
        "description": product["description"],
        "unit": product["unit"],
        "install_code": product["install_code"],
        "source_type": product["source_type"],
        "supplier_quote_required": product["supplier_quote_required"].strip().lower() == "true",
    }


def _productivity_traceability(productivity: dict[str, str] | None) -> dict[str, Any] | None:
    if not productivity:
        return None
    return {
        "install_code": productivity["install_code"],
        "work_type": productivity["work_type"],
        "unit": productivity["unit"],
        "base_hours_per_unit": float(productivity["base_hours_per_unit"]),
        "labour_role": productivity["labour_role"],
        "default_hourly_rate_chf": float(productivity["default_hourly_rate_chf"]),
        "factor_keys": productivity["factor_keys"],
    }


def _project_totals_payload(
    *,
    rows: list[dict[str, Any]],
    parameters: dict[str, Any],
    excluded_position_count: int,
    included_statuses: list[str],
    label: str,
) -> dict[str, Any]:
    breakdown = calculate_project_cost_breakdown(rows, parameters) if rows else {}
    summary = {
        "material_cost_chf": breakdown.get("material_cost_chf", 0.0),
        "labour_cost_chf": breakdown.get("labour_cost_chf", 0.0),
        "direct_cost_chf": breakdown.get("direct_cost_chf", 0.0),
        "cost_baseline_chf": breakdown.get("cost_baseline_chf", 0.0),
    }
    return {
        "label": label,
        "summary": summary,
        "breakdown": breakdown,
        "included_position_count": len(rows),
        "excluded_position_count": excluded_position_count,
        "included_statuses": included_statuses,
        "formula_note": "Uses the documented Phase 1 formula; unresolved reference discrepancy is reported separately.",
    }


def _has_pricing_fields(row: dict[str, Any]) -> bool:
    required = (
        "material_cost_chf",
        "labour_cost_chf",
        "direct_position_cost_chf",
        "price_source",
    )
    return all(field in row and row[field] is not None for field in required)


def _load_optional_full_output(project_root: Path) -> list[dict[str, Any]]:
    output_path = project_root / FULL_TENDER_OUTPUT_PATH
    if not output_path.exists():
        return []
    return json.loads(output_path.read_text(encoding="utf-8"))


def _link_full_rows_to_examples(
    full_rows: list[dict[str, Any]],
    examples: list[dict[str, str]],
) -> dict[str, dict[str, Any]]:
    linked: dict[str, dict[str, Any]] = {}
    for example in examples:
        candidates = [
            row
            for row in full_rows
            if row.get("source_page") == int(example["source_page"])
            and row.get("quantity") == float(example["quantity"])
            and row.get("unit") == example["unit"]
            and row.get("matched_product_id") == example["suggested_product_id"]
        ]
        if candidates:
            linked[example["lv_id"]] = candidates[0]
    return linked


def _linked_value(linked: dict[str, Any] | None, key: str, fallback: Any) -> Any:
    if linked and key in linked:
        return linked[key]
    return fallback


def _example_traceability_warnings(
    full_rows_by_example: dict[str, dict[str, Any]],
    examples: list[dict[str, str]],
) -> list[str]:
    missing = [example["lv_id"] for example in examples if example["lv_id"] not in full_rows_by_example]
    if not missing:
        return []
    return [
        "Some verified example rows could not be linked to German Phase 2 extraction output: "
        + ", ".join(missing)
    ]
