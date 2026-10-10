from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any


CENT = Decimal("0.01")
FOUR_DP = Decimal("0.0001")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def quantity(value: str) -> Decimal:
    return Decimal(str(value).strip())


def by_key(rows: list[dict[str, str]], key: str) -> dict[str, dict[str, str]]:
    return {row[key]: row for row in rows}


def resolve_factor_multiplier(factor_keys: str, parameters: dict[str, Any]) -> Decimal:
    factors = parameters["productivity_factors"]
    multiplier = Decimal("1")
    for key in [part.strip() for part in factor_keys.split("|") if part.strip()]:
        factor = Decimal(str(factors[key]))
        if key == "site_efficiency":
            multiplier *= Decimal("1") / factor
        else:
            multiplier *= factor
    return multiplier


def calculate_position(
    example: dict[str, str],
    catalog_by_id: dict[str, dict[str, str]],
    productivity_by_code: dict[str, dict[str, str]],
    parameters: dict[str, Any],
) -> dict[str, Any]:
    product_id = example["suggested_product_id"]
    install_code = example["expected_install_code"]
    product = catalog_by_id[product_id]
    productivity = productivity_by_code[install_code]

    q = quantity(example["quantity"])
    net_unit_cost = Decimal(str(product["net_cost_chf"]))
    waste_multiplier = Decimal("1") + Decimal(str(parameters["allowances"]["material_waste_pct"])) / Decimal("100")
    material_cost = money(q * net_unit_cost * waste_multiplier)

    factor_multiplier = resolve_factor_multiplier(productivity["factor_keys"], parameters)
    install_hours_raw = q * Decimal(str(productivity["base_hours_per_unit"])) * factor_multiplier
    labour_cost = money(install_hours_raw * Decimal(str(productivity["default_hourly_rate_chf"])))

    supplier_quote_required = product["supplier_quote_required"].strip().lower() == "true"
    price_source = product["source_type"]
    if supplier_quote_required:
        material_cost_basis = "supplier_package_catalogue_estimate_pending_quote"
        direct_cost_basis = "provisional_material_estimate_plus_labour_estimate"
        cost_confirmation_status = "provisional_supplier_quote_required"
    else:
        material_cost_basis = "catalogue_net_cost"
        direct_cost_basis = "catalogue_material_estimate_plus_labour_estimate"
        cost_confirmation_status = "confirmed_catalogue_cost_basis"

    return {
        "lv_id": example["lv_id"],
        "source_page": int(example["source_page"]),
        "matched_product_id": product_id,
        "install_code": install_code,
        "quantity": float(q),
        "unit": example["unit"],
        "net_unit_cost_chf": float(net_unit_cost),
        "material_cost_chf": float(material_cost),
        "adjusted_install_hours": float(install_hours_raw.quantize(CENT, rounding=ROUND_HALF_UP)),
        "labour_cost_chf": float(labour_cost),
        "direct_position_cost_chf": float(money(material_cost + labour_cost)),
        "price_source": price_source,
        "supplier_quote_required": supplier_quote_required,
        "material_cost_basis": material_cost_basis,
        "labour_cost_basis": "productivity_rule_estimate",
        "direct_cost_basis": direct_cost_basis,
        "cost_confirmation_status": cost_confirmation_status,
        "match_confidence": 0.72 if supplier_quote_required else 0.92,
        "review_required": supplier_quote_required,
        "status": example["ground_truth_status"],
    }


def calculate_positions(data: dict[str, Any]) -> list[dict[str, Any]]:
    catalog_by_id = by_key(data["catalog"], "product_id")
    productivity_by_code = by_key(data["productivity"], "install_code")
    return [
        calculate_position(example, catalog_by_id, productivity_by_code, data["parameters"])
        for example in data["examples"]
    ]


def calculate_example_summary(positions: list[dict[str, Any]], parameters: dict[str, Any]) -> dict[str, float]:
    breakdown = calculate_project_cost_breakdown(positions, parameters)
    return {
        "material_cost_chf": breakdown["material_cost_chf"],
        "labour_cost_chf": breakdown["labour_cost_chf"],
        "direct_cost_chf": breakdown["direct_cost_chf"],
        "cost_baseline_chf": breakdown["cost_baseline_chf"],
    }


def calculate_project_cost_breakdown(
    positions: list[dict[str, Any]],
    parameters: dict[str, Any],
) -> dict[str, float]:
    material = money(sum((Decimal(str(row["material_cost_chf"])) for row in positions), Decimal("0")))
    labour = money(sum((Decimal(str(row["labour_cost_chf"])) for row in positions), Decimal("0")))
    direct = money(material + labour)

    supplier_package_material = money(
        sum(
            (
                Decimal(str(row["material_cost_chf"]))
                for row in positions
                if row["price_source"] == "supplier_package"
            ),
            Decimal("0"),
        ),
    )
    catalog_material = money(material - supplier_package_material)

    overhead = money(direct * Decimal(str(parameters["commercial"]["overhead_pct"])) / Decimal("100"))
    small_material = money(material * Decimal(str(parameters["allowances"]["small_material_pct"])) / Decimal("100"))
    transport_equipment = money(
        direct * Decimal(str(parameters["allowances"]["transport_equipment_pct"])) / Decimal("100")
    )
    supplier_package_contingency = money(
        supplier_package_material
        * Decimal(str(parameters["allowances"]["supplier_package_contingency_pct"]))
        / Decimal("100")
    )

    project_costs = parameters["project_costs"]
    engineering = money(
        Decimal(str(project_costs["engineering_hours"]))
        * Decimal(str(project_costs["engineering_rate_chf_per_h"]))
    )
    commissioning = money(
        Decimal(str(project_costs["commissioning_hours"]))
        * Decimal(str(project_costs["commissioning_rate_chf_per_h"]))
    )
    hygiene_inspection = money(Decimal(str(project_costs["hygiene_inspection_chf"])))
    documentation = money(Decimal(str(project_costs["documentation_chf"])))

    cost_baseline = money(direct + small_material + overhead)

    return {
        "material_cost_chf": float(material),
        "labour_cost_chf": float(labour),
        "direct_cost_chf": float(direct),
        "catalog_material_cost_chf": float(catalog_material),
        "supplier_package_material_cost_chf": float(supplier_package_material),
        "small_material_allowance_chf": float(small_material),
        "transport_equipment_allowance_chf": float(transport_equipment),
        "supplier_package_contingency_chf": float(supplier_package_contingency),
        "engineering_chf": float(engineering),
        "commissioning_chf": float(commissioning),
        "hygiene_inspection_chf": float(hygiene_inspection),
        "documentation_chf": float(documentation),
        "overhead_chf": float(overhead),
        "cost_baseline_chf": float(cost_baseline),
        "cost_baseline_formula": (
            "direct_cost + small_material_allowance_on_material + overhead_on_direct_cost"
        ),
    }


def validate_against_reference(
    positions: list[dict[str, Any]],
    summary: dict[str, float],
    expected: dict[str, Any],
) -> dict[str, Any]:
    expected_by_id = {row["lv_id"]: row for row in expected["position_results"]}
    position_differences: list[dict[str, Any]] = []
    numeric_fields = (
        "material_cost_chf",
        "adjusted_install_hours",
        "labour_cost_chf",
        "direct_position_cost_chf",
    )

    for position in positions:
        expected_position = expected_by_id[position["lv_id"]]
        diffs: dict[str, Any] = {}
        for field in numeric_fields:
            actual = Decimal(str(position[field]))
            reference = Decimal(str(expected_position[field]))
            if abs(actual - reference) > Decimal("0.01"):
                diffs[field] = {"actual": float(actual), "expected": float(reference)}
        for field in ("matched_product_id", "install_code", "status", "price_source", "review_required"):
            if position[field] != expected_position[field]:
                diffs[field] = {"actual": position[field], "expected": expected_position[field]}
        if diffs:
            position_differences.append({"lv_id": position["lv_id"], "differences": diffs})

    summary_differences: dict[str, dict[str, float]] = {}
    expected_summary = expected["example_subset_summary"]
    for field, actual_value in summary.items():
        actual = Decimal(str(actual_value))
        reference = Decimal(str(expected_summary[field]))
        if abs(actual - reference) > Decimal("0.01"):
            summary_differences[field] = {"actual": float(actual), "expected": float(reference)}

    return {
        "positions_match_reference": not position_differences,
        "position_differences": position_differences,
        "summary_differences": summary_differences,
    }

