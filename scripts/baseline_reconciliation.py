from __future__ import annotations

import csv
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def load_csv(name: str) -> list[dict[str, str]]:
    with (PROJECT_ROOT / name).open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    parameters = json.loads((PROJECT_ROOT / "project_parameters.json").read_text(encoding="utf-8"))
    expected = json.loads((PROJECT_ROOT / "expected_output_example.json").read_text(encoding="utf-8"))
    catalog = {row["product_id"]: row for row in load_csv("catalog.csv")}
    productivity = {row["install_code"]: row for row in load_csv("productivity.csv")}
    examples = load_csv("example_lv_positions.csv")

    raw_positions: list[tuple[Decimal, Decimal, str]] = []
    rounded_positions: list[tuple[Decimal, Decimal, str]] = []
    for example in examples:
        product = catalog[example["suggested_product_id"]]
        rule = productivity[example["expected_install_code"]]
        quantity = Decimal(example["quantity"])
        net_unit_cost = Decimal(product["net_cost_chf"])
        material = quantity * net_unit_cost * (
            Decimal("1") + Decimal(str(parameters["allowances"]["material_waste_pct"])) / 100
        )

        factor_multiplier = Decimal("1")
        for key in [part for part in rule["factor_keys"].split("|") if part]:
            factor = Decimal(str(parameters["productivity_factors"][key]))
            factor_multiplier *= Decimal("1") / factor if key == "site_efficiency" else factor
        labour = (
            quantity
            * Decimal(rule["base_hours_per_unit"])
            * factor_multiplier
            * Decimal(rule["default_hourly_rate_chf"])
        )
        raw_positions.append((material, labour, product["source_type"]))
        rounded_positions.append((money(material), money(labour), product["source_type"]))

    material = sum(row[0] for row in rounded_positions)
    labour = sum(row[1] for row in rounded_positions)
    direct = money(material + labour)
    supplier_material = sum(row[0] for row in rounded_positions if row[2] == "supplier_package")

    small_pct = Decimal(str(parameters["allowances"]["small_material_pct"])) / 100
    transport_pct = Decimal(str(parameters["allowances"]["transport_equipment_pct"])) / 100
    supplier_pct = Decimal(str(parameters["allowances"]["supplier_package_contingency_pct"])) / 100
    overhead_pct = Decimal(str(parameters["commercial"]["overhead_pct"])) / 100
    expected_baseline = Decimal(str(expected["example_subset_summary"]["cost_baseline_chf"]))

    alternatives = {
        "current_direct_plus_small_material_plus_overhead": direct + material * small_pct + direct * overhead_pct,
        "readme_direct_plus_overhead_only": direct + direct * overhead_pct,
        "overhead_after_small_material": (direct + material * small_pct) * (Decimal("1") + overhead_pct),
        "current_plus_transport": direct + material * small_pct + direct * overhead_pct + direct * transport_pct,
        "current_plus_supplier_contingency": (
            direct + material * small_pct + direct * overhead_pct + supplier_material * supplier_pct
        ),
        "direct_plus_transport_plus_overhead": direct + direct * transport_pct + direct * overhead_pct,
    }

    print("Independent baseline reconciliation")
    print(f"positions: {len(examples)}")
    print(f"material: {material}")
    print(f"labour: {labour}")
    print(f"direct: {direct}")
    print(f"expected_baseline: {expected_baseline}")
    print(f"raw_rounding_delta_material: {money(sum(row[0] for row in raw_positions)) - material}")
    print(f"raw_rounding_delta_labour: {money(sum(row[1] for row in raw_positions)) - labour}")
    for name, value in alternatives.items():
        result = money(value)
        print(f"{name}: {result} diff={money(result - expected_baseline)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

