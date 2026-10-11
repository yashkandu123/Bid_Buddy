"""Pricing & labour math (PRD §3) plus project aggregation and Bid Optimization (PRD §6).

Position level
    net_unit_cost      = list_price × (1 − discount)             (or reviewer's custom unit cost)
    material_cost      = qty × net_unit_cost × (1 + waste)
    install_hours      = qty × base_hours × (1/site_efficiency) × Π(other factor_keys)
    labour_cost        = install_hours × hourly_rate
    direct_cost        = (material + labour) × (1 + group markup)      # markup defaults to 0
Project level
    project_direct     = Σ(material + labour) + small material + supplier contingency
                         + transport/equipment + engineering + commissioning + special costs
    cost_baseline      = project_direct × (1 + overhead)
    selling_price      = cost_baseline / (1 − target margin)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .matcher import PRICED_STATUSES

HOURS_PER_DAY = 8.0
LABOUR_PSEUDO = {  # labour-only rows from the tender (man-days, hourly items)
    "LABOUR_DAY": {"rate_role": "installer", "rate": 96.0},
    "LABOUR_HOUR": {"rate_role": "installer", "rate": 96.0},
    "LABOUR_COMMISSIONING": {"rate_role": "commissioning_specialist", "rate": 155.0},
}


@dataclass
class SimSettings:
    tier: str = "Standard"                 # Standard | Wholesale | Custom
    global_discount_pct: float = 0.0       # Standard/Wholesale: extra discount on top; Custom: replaces catalogue discount
    wholesale_extra_pct: float = 5.0
    discount_supplier_packages: bool = False
    group_markup_pct: dict = field(default_factory=dict)   # category -> %
    factors: dict = field(default_factory=dict)            # productivity factor overrides
    material_waste_pct: float = 4.0
    labour_rate_multiplier: float = 1.0
    overhead_pct: float = 8.5
    target_margin_pct: float = 5.5
    small_material_pct: float = 3.5
    transport_equipment_pct: float = 2.5
    supplier_package_contingency_pct: float = 3.0
    include_small_material: bool = True
    include_supplier_contingency: bool = True
    include_transport: bool = True
    include_engineering: bool = True
    include_commissioning: bool = True
    include_special: bool = True
    round_to_chf: int = 1000

    @classmethod
    def from_params(cls, params: dict, **kw):
        a, c = params["allowances"], params["commercial"]
        s = cls(material_waste_pct=a["material_waste_pct"], small_material_pct=a["small_material_pct"],
                transport_equipment_pct=a["transport_equipment_pct"],
                supplier_package_contingency_pct=a["supplier_package_contingency_pct"],
                overhead_pct=c["overhead_pct"], target_margin_pct=c["target_margin_pct"],
                round_to_chf=c.get("round_to_chf", 1000), factors=dict(params["productivity_factors"]))
        for k, v in kw.items():
            setattr(s, k, v)
        return s


def _f(x):
    try:
        if x is None or (isinstance(x, float) and math.isnan(x)) or x == "":
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def calc_positions(df: pd.DataFrame, catalog: pd.DataFrame, productivity: pd.DataFrame, sim: SimSettings) -> pd.DataFrame:
    cat = catalog.set_index("product_id")
    prod = productivity.set_index("install_code")
    rows = []
    for r in df.to_dict("records"):
        qty = _f(r.get("quantity")) or 0.0
        pid = r.get("product_id") or ""
        ic = r.get("install_code") or "UNKNOWN"
        out = dict(list_price_chf=np.nan, catalog_discount_pct=np.nan, effective_discount_pct=np.nan,
                   net_unit_cost_chf=np.nan, material_cost_chf=np.nan, price_source="none",
                   base_hours_per_unit=0.0, factor_multiplier=np.nan, adjusted_install_hours=0.0,
                   hourly_rate_chf=0.0, labour_cost_chf=0.0)
        supplier = False
        if pid and pid in cat.index:
            p = cat.loc[pid]
            supplier = p["source_type"] == "supplier_package"
            lp, cd = float(p["list_price_chf"]), float(p["discount_pct"])
            disc = cd
            if not supplier or sim.discount_supplier_packages:
                if sim.tier == "Wholesale":
                    disc = cd + sim.wholesale_extra_pct
                elif sim.tier == "Custom":
                    disc = sim.global_discount_pct
                if sim.tier != "Custom" and sim.global_discount_pct:
                    disc = 100 - (100 - disc) * (1 - sim.global_discount_pct / 100)
            disc = min(max(disc, 0.0), 95.0)
            net = lp * (1 - disc / 100)
            out.update(list_price_chf=lp, catalog_discount_pct=cd, effective_discount_pct=disc,
                       net_unit_cost_chf=net, price_source="supplier_package" if supplier else "catalog")
        custom = _f(r.get("custom_unit_cost_chf"))
        if custom is not None:
            out["net_unit_cost_chf"] = custom
            out["price_source"] = "reviewer_override"
        if not np.isnan(out["net_unit_cost_chf"]):
            qf = _f(r.get("qty_factor")) or 1.0
            if out["price_source"] == "reviewer_override":
                qf = 1.0                                     # custom cost is per tender unit
            out["material_cost_chf"] = qty * qf * out["net_unit_cost_chf"] * (1 + sim.material_waste_pct / 100)

        # labour
        if ic in LABOUR_PSEUDO:
            hrs = qty * (HOURS_PER_DAY if ic == "LABOUR_DAY" else 1.0)
            rate = LABOUR_PSEUDO[ic]["rate"] * sim.labour_rate_multiplier
            out.update(base_hours_per_unit=HOURS_PER_DAY if ic == "LABOUR_DAY" else 1.0, factor_multiplier=1.0,
                       adjusted_install_hours=hrs, hourly_rate_chf=rate, labour_cost_chf=hrs * rate)
            if out["price_source"] == "none":
                out["price_source"] = "labour"
        elif ic in prod.index:
            pr = prod.loc[ic]
            base = float(pr["base_hours_per_unit"])
            keys = [k for k in str(pr["factor_keys"]).split("|") if k and k != "nan"]
            mult = 1.0
            sports_hall = str(r.get("system", "")).startswith("244.05")
            for k in keys:
                if k == "mounting_height_school" and sports_hall and "mounting_height_sports_hall" in sim.factors:
                    k = "mounting_height_sports_hall"         # LA05 Turnhalle: higher mounting height
                v = float(sim.factors.get(k, 1.0))
                mult *= (1.0 / v) if k == "site_efficiency" else v
            hrs = qty * base * mult
            rate = float(pr["default_hourly_rate_chf"]) * sim.labour_rate_multiplier
            out.update(base_hours_per_unit=base, factor_multiplier=mult, adjusted_install_hours=hrs,
                       hourly_rate_chf=rate, labour_cost_chf=hrs * rate)
        mat = 0.0 if np.isnan(out["material_cost_chf"]) else out["material_cost_chf"]
        cat_name = r.get("category") or "Other"
        mk = float(sim.group_markup_pct.get(cat_name, 0.0))
        out["group_markup_pct"] = mk
        out["direct_position_cost_chf"] = (mat + out["labour_cost_chf"]) * (1 + mk / 100)
        out["is_supplier_package"] = supplier
        include = r.get("include", True)
        include = True if include is None or (isinstance(include, float) and np.isnan(include)) else bool(include)
        out["in_totals"] = include and (r.get("status") in PRICED_STATUSES)
        rows.append(out)
    res = pd.concat([df.reset_index(drop=True).drop(columns=[c for c in rows[0] if c in df.columns], errors="ignore"),
                     pd.DataFrame(rows)], axis=1) if rows else df.copy()
    return res


def project_summary(calc: pd.DataFrame, params: dict, sim: SimSettings) -> dict:
    t = calc[calc["in_totals"]]
    mat_markup = t["material_cost_chf"].fillna(0) * (1 + t["group_markup_pct"] / 100)
    lab_markup = t["labour_cost_chf"] * (1 + t["group_markup_pct"] / 100)
    sup = t["is_supplier_package"]
    material_catalog = float(mat_markup[~sup].sum())
    material_supplier = float(mat_markup[sup].sum())
    labour = float(lab_markup.sum())
    position_direct = material_catalog + material_supplier + labour
    pc = params["project_costs"]
    lines = {
        "Material (catalogue)": material_catalog,
        "Supplier packages": material_supplier,
        "Installation labour": labour,
        "Small material allowance": material_catalog * sim.small_material_pct / 100 if sim.include_small_material else 0.0,
        "Supplier package contingency": material_supplier * sim.supplier_package_contingency_pct / 100 if sim.include_supplier_contingency else 0.0,
        "Transport & equipment": position_direct * sim.transport_equipment_pct / 100 if sim.include_transport else 0.0,
        "Engineering / project management": pc["engineering_hours"] * pc["engineering_rate_chf_per_h"] if sim.include_engineering else 0.0,
        "Commissioning": pc["commissioning_hours"] * pc["commissioning_rate_chf_per_h"] if sim.include_commissioning else 0.0,
        "Hygiene inspection": pc["hygiene_inspection_chf"] if sim.include_special else 0.0,
        "Documentation": pc["documentation_chf"] if sim.include_special else 0.0,
    }
    project_direct = sum(lines.values())
    overhead = project_direct * sim.overhead_pct / 100
    baseline = project_direct + overhead
    selling = baseline / (1 - sim.target_margin_pct / 100)
    step = sim.round_to_chf or 1
    return {
        "lines": lines,
        "position_direct": position_direct,
        "material_total": material_catalog + material_supplier,
        "labour_total": labour,
        "hours_total": float(t["adjusted_install_hours"].sum()),
        "project_direct": project_direct,
        "overhead": overhead,
        "cost_baseline": baseline,
        "selling_price": selling,
        "selling_price_rounded": math.ceil(selling / step) * step,
        "positions_total": int(len(calc)),
        "positions_in_totals": int(len(t)),
    }


# --------------------------------------------------------------------------- bid optimisation
@dataclass
class BidModel:
    reference_win_probability: float = 0.55
    price_sensitivity: float = 0.05          # probability points per 1 % price vs reference
    strategic_appetite_adjustment: float = 0.05
    competition_adjustment: float = -0.05
    capacity_adjustment: float = 0.0
    minimum_probability: float = 0.05
    maximum_probability: float = 0.95

    @classmethod
    def from_params(cls, params: dict):
        b = params["stretch_bid_optimization"]
        return cls(reference_win_probability=b["reference_win_probability"],
                   price_sensitivity=b["price_sensitivity_probability_points_per_1pct_price"],
                   strategic_appetite_adjustment=b["strategic_appetite_adjustment"],
                   competition_adjustment=b["competition_adjustment"],
                   minimum_probability=b["minimum_probability"], maximum_probability=b["maximum_probability"])

    def win_probability(self, bid: float, reference_price: float) -> float:
        rel_pct = (bid / reference_price - 1) * 100
        p = (self.reference_win_probability + self.strategic_appetite_adjustment + self.competition_adjustment
             + self.capacity_adjustment - self.price_sensitivity * rel_pct)
        return float(min(max(p, self.minimum_probability), self.maximum_probability))


def bid_scenarios(baseline: float, margins: dict, reference_margin_pct: float, model: BidModel, round_to: int = 1000):
    """Reference price = baseline at the project's target margin (unrounded)."""
    ref = baseline / (1 - reference_margin_pct / 100)
    out = []
    for name, m in margins.items():
        bid = math.ceil(baseline / (1 - m / 100) / round_to) * round_to
        p = model.win_probability(bid, ref)
        contribution = bid - baseline
        out.append({"scenario": name, "bid_price_chf": bid, "margin_pct": m,
                    "realised_margin_pct": contribution / bid * 100,
                    "estimated_win_probability": p, "contribution_if_won_chf": contribution,
                    "expected_contribution_chf": p * contribution})
    return out, ref


def bid_curve(baseline: float, reference_margin_pct: float, model: BidModel, lo=0.0, hi=12.0, step=0.25):
    ref = baseline / (1 - reference_margin_pct / 100)
    rows = []
    for m in np.arange(lo, hi + 1e-9, step):
        bid = baseline / (1 - m / 100)
        p = model.win_probability(bid, ref)
        rows.append({"margin_pct": m, "bid_price_chf": bid, "win_probability": p,
                     "expected_contribution_chf": p * (bid - baseline)})
    return pd.DataFrame(rows)
