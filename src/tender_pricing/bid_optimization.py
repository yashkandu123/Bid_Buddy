from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP
from typing import Any


CENT = Decimal("0.01")
PROBABILITY_DP = Decimal("0.01")
INCOMPLETE_STATUSES = ("insufficient_information", "review_required")


class BidOptimizationError(ValueError):
    pass


def build_bid_scenarios(
    result: dict[str, Any],
    parameters: dict[str, Any],
    selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = parameters.get("stretch_bid_optimization", {})
    if not settings.get("enabled", False):
        raise BidOptimizationError("Bid optimization is disabled in project_parameters.json.")

    cost_basis = _combined_cost_basis(result)
    audit = _formula_audit(parameters)
    warnings = _scenario_warnings(result, cost_basis)
    scenarios = [
        _build_scenario(name, settings["scenario_margins_pct"][name], cost_basis, parameters, audit)
        for name in settings.get("scenario_names", [])
        if name in settings.get("scenario_margins_pct", {})
    ]

    selected_name = (selection or {}).get("scenario_name")
    if selected_name and selected_name not in {scenario["scenario"] for scenario in scenarios}:
        selected_name = None

    return {
        "schema_version": "phase8d.bid_scenarios.v1",
        "job_id": result.get("job_id"),
        "currency": parameters["project"]["currency"],
        "cost_basis": cost_basis,
        "scenarios": scenarios,
        "selection": {
            "scenario_name": selected_name,
            "updated_at": (selection or {}).get("updated_at") if selected_name else None,
        },
        "warnings": warnings,
        "formula_audit": audit,
    }


def validate_bid_selection(payload: dict[str, Any], scenario_names: set[str]) -> dict[str, str]:
    allowed = {"scenario_name"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise BidOptimizationError(f"Unsupported bid-selection fields: {', '.join(unknown)}")
    scenario_name = payload.get("scenario_name")
    if not isinstance(scenario_name, str) or not scenario_name.strip():
        raise BidOptimizationError("scenario_name is required.")
    scenario_name = scenario_name.strip()
    if scenario_name not in scenario_names:
        raise BidOptimizationError(f"Unsupported scenario_name: {scenario_name}")
    return {"scenario_name": scenario_name}


def _build_scenario(
    name: str,
    margin_pct: float | int | str,
    cost_basis: dict[str, Any],
    parameters: dict[str, Any],
    audit: dict[str, Any],
) -> dict[str, Any]:
    baseline = _decimal(cost_basis["cost_baseline_chf"])
    margin = _decimal(margin_pct)
    if baseline is None or baseline <= 0:
        return _unavailable_scenario(name, margin, "Cost baseline must be greater than zero.")
    if margin is None or margin < 0 or margin >= 100:
        return _unavailable_scenario(name, margin, "Scenario margin must be between 0 and 100 percent.")

    raw_bid = baseline / (Decimal("1") - margin / Decimal("100"))
    bid_price = _round_up(raw_bid, _decimal(parameters["commercial"].get("round_to_chf", 1000)) or Decimal("1000"))
    probability = _heuristic_probability(margin, parameters)
    expected_contribution = None
    if probability is not None:
        expected_contribution = _money((bid_price - baseline) * probability)

    return {
        "scenario": name,
        "margin_pct": float(margin),
        "cost_baseline_chf": float(_money(baseline)),
        "raw_bid_price_chf": float(_money(raw_bid)),
        "bid_price_chf": float(bid_price),
        "rounding_increment_chf": float(_decimal(parameters["commercial"].get("round_to_chf", 1000)) or Decimal("1000")),
        "estimated_win_probability": float(probability) if probability is not None else None,
        "probability_available": probability is not None,
        "probability_model": audit["probability_model"],
        "expected_contribution_chf": float(expected_contribution) if expected_contribution is not None else None,
        "expected_contribution_definition": (
            "(rounded_bid_price_chf - cost_baseline_chf) * estimated_win_probability"
        ),
        "complete": not cost_basis["has_unresolved_positions"] and not cost_basis["has_provisional_supplier_estimates"],
        "completion_reasons": _completion_reasons(cost_basis),
    }


def _unavailable_scenario(name: str, margin: Decimal | None, reason: str) -> dict[str, Any]:
    return {
        "scenario": name,
        "margin_pct": float(margin) if margin is not None else None,
        "cost_baseline_chf": None,
        "raw_bid_price_chf": None,
        "bid_price_chf": None,
        "rounding_increment_chf": None,
        "estimated_win_probability": None,
        "probability_available": False,
        "probability_model": "unavailable",
        "expected_contribution_chf": None,
        "expected_contribution_definition": (
            "(rounded_bid_price_chf - cost_baseline_chf) * estimated_win_probability"
        ),
        "complete": False,
        "completion_reasons": [reason],
    }


def _combined_cost_basis(result: dict[str, Any]) -> dict[str, Any]:
    totals = result.get("project_totals", {})
    combined = totals.get("combined_estimate", {}).get("summary", {})
    confirmed = totals.get("confirmed", {}).get("summary", {})
    provisional = totals.get("provisional", {}).get("summary", {})
    status_counts = result.get("status_counts", {})
    unresolved_counts = {status: int(status_counts.get(status, 0)) for status in INCOMPLETE_STATUSES}
    non_priceable_count = int(status_counts.get("non_priceable", 0))
    supplier_quotes = int(totals.get("supplier_quotes_outstanding", 0))
    return {
        "basis": "combined_confirmed_and_provisional_estimate",
        "currency": "CHF",
        "cost_baseline_chf": combined.get("cost_baseline_chf", 0.0),
        "direct_cost_chf": combined.get("direct_cost_chf", 0.0),
        "confirmed_cost_baseline_chf": confirmed.get("cost_baseline_chf", 0.0),
        "provisional_cost_baseline_chf": provisional.get("cost_baseline_chf", 0.0),
        "confirmed_direct_cost_chf": confirmed.get("direct_cost_chf", 0.0),
        "provisional_direct_cost_chf": provisional.get("direct_cost_chf", 0.0),
        "included_statuses": totals.get("included_statuses", []),
        "included_position_count": totals.get("included_position_count", 0),
        "excluded_position_count": totals.get("excluded_position_count", 0),
        "unresolved_position_counts": unresolved_counts,
        "supplier_quotes_outstanding": supplier_quotes,
        "non_priceable_position_count": non_priceable_count,
        "has_unresolved_positions": any(count > 0 for count in unresolved_counts.values()),
        "has_provisional_supplier_estimates": supplier_quotes > 0,
        "formula_note": totals.get("formula_note", ""),
    }


def _scenario_warnings(result: dict[str, Any], cost_basis: dict[str, Any]) -> list[dict[str, str]]:
    warnings = [
        {
            "code": "probability_is_heuristic",
            "severity": "warning",
            "message": (
                "Win probability uses configured heuristic parameters only; it is not calibrated with historical bids."
            ),
        }
    ]
    if cost_basis["has_provisional_supplier_estimates"]:
        warnings.append(
            {
                "code": "supplier_quotes_outstanding",
                "severity": "warning",
                "message": (
                    "Scenario cost basis includes provisional supplier-package catalogue estimates; "
                    "confirmed supplier quotations are still outstanding."
                ),
            }
        )
    if cost_basis["has_unresolved_positions"]:
        warnings.append(
            {
                "code": "unresolved_positions_excluded",
                "severity": "warning",
                "message": (
                    "Rows marked insufficient_information or review_required are excluded from the bid cost basis."
                ),
            }
        )
    baseline_warning = result.get("baseline_reconciliation_warning")
    if baseline_warning:
        warnings.append(
            {
                "code": str(baseline_warning.get("code", "baseline_warning")),
                "severity": str(baseline_warning.get("severity", "warning")),
                "message": str(baseline_warning.get("message", "")),
            }
        )
    return warnings


def _completion_reasons(cost_basis: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if cost_basis["has_unresolved_positions"]:
        reasons.append("Unresolved review_required or insufficient_information rows are excluded from the cost basis.")
    if cost_basis["has_provisional_supplier_estimates"]:
        reasons.append("Supplier-package estimates are provisional until supplier quotes are confirmed.")
    return reasons


def _formula_audit(parameters: dict[str, Any]) -> dict[str, Any]:
    settings = parameters["stretch_bid_optimization"]
    commercial = parameters["commercial"]
    model_inputs = settings.get("model_inputs", [])
    supported_probability_inputs = [
        "reference_win_probability",
        "price_sensitivity_probability_points_per_1pct_price",
        "strategic_appetite_adjustment",
        "competition_adjustment",
        "minimum_probability",
        "maximum_probability",
    ]
    return {
        "cost_basis": (
            "Uses project_totals.combined_estimate.summary.cost_baseline_chf after saved estimator review state "
            "has been applied. Confirmed catalogue costs and provisional supplier-package estimates are shown "
            "separately; unresolved rows are excluded."
        ),
        "overhead_and_project_costs": (
            "Cost baseline is the existing Phase 1 formula: direct_cost + small_material_allowance_on_material "
            "+ overhead_on_direct_cost. Engineering, commissioning, hygiene, documentation, transport/equipment "
            "and supplier-package contingency remain reported in the breakdown but are not included in the "
            "implemented baseline."
        ),
        "bid_price_formula": "round_up(cost_baseline_chf / (1 - margin_pct / 100), round_to_chf)",
        "rounding": (
            f"CHF {commercial.get('round_to_chf', 1000)} upward rounding is applied after margin markup."
        ),
        "probability_model": (
            "Heuristic: clamp(reference_win_probability + (commercial.target_margin_pct - scenario_margin_pct) "
            "* price_sensitivity_probability_points_per_1pct_price + strategic_appetite_adjustment "
            "+ competition_adjustment, minimum_probability, maximum_probability)."
        ),
        "probability_supported_inputs": supported_probability_inputs,
        "probability_unsupported_model_inputs": [
            item
            for item in model_inputs
            if item
            not in {
                "strategic_appetite",
                "client_price_sensitivity",
            }
        ],
        "expected_contribution_definition": (
            "(rounded_bid_price_chf - cost_baseline_chf) * estimated_win_probability"
        ),
        "reference_output_limitation": (
            "expected_output_example.json contains scenario outputs, but it does not uniquely establish the "
            "probability or expected-contribution formulas."
        ),
    }


def _heuristic_probability(margin: Decimal, parameters: dict[str, Any]) -> Decimal | None:
    try:
        settings = parameters["stretch_bid_optimization"]
        commercial = parameters["commercial"]
        probability = (
            _decimal(settings["reference_win_probability"])
            + (_decimal(commercial["target_margin_pct"]) - margin)
            * _decimal(settings["price_sensitivity_probability_points_per_1pct_price"])
            + _decimal(settings.get("strategic_appetite_adjustment", 0))
            + _decimal(settings.get("competition_adjustment", 0))
        )
        minimum = _decimal(settings.get("minimum_probability", 0))
        maximum = _decimal(settings.get("maximum_probability", 1))
    except (KeyError, TypeError):
        return None
    if None in {probability, minimum, maximum}:
        return None
    probability = max(minimum, min(maximum, probability))
    return probability.quantize(PROBABILITY_DP, rounding=ROUND_HALF_UP)


def _round_up(value: Decimal, increment: Decimal) -> Decimal:
    if increment <= 0:
        return _money(value)
    units = (value / increment).to_integral_value(rounding=ROUND_CEILING)
    return _money(units * increment)


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _decimal(value: Any) -> Decimal | None:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    try:
        if not math.isfinite(float(decimal)):
            return None
    except (OverflowError, ValueError):
        return None
    return decimal
