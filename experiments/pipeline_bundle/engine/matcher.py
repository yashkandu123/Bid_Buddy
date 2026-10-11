"""Rule-based semantic matcher: parsed tender position -> catalogue product / productivity rule / status.

Every row gets exactly one status from the PRD triage list. Nothing is force-priced: rows without a
defensible catalogue match keep `product_id = ""` and a review / non-priceable status.
"""
from __future__ import annotations

import re
import pandas as pd

STATUSES = ["calculated", "supplier_quote_required", "assumption_applied", "review_required",
            "insufficient_information", "out_of_scope", "non_priceable"]
PRICED_STATUSES = {"calculated", "supplier_quote_required", "assumption_applied"}

CONF = {"exact": 0.92, "supplier": 0.72, "nearest": 0.55, "assumption": 0.5, "review": 0.3,
        "fallback": 0.2, "classified": 0.8}


# --------------------------------------------------------------------------- catalogue helpers
def _nums(s: str):
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", s)]


def catalog_sizes(catalog: pd.DataFrame) -> pd.DataFrame:
    cat = catalog.copy()
    dn, w, h, l, af, ang = [], [], [], [], [], []
    for _, r in cat.iterrows():
        n = _nums(str(r["model"]).replace("x", " "))
        sub, ic = str(r["subcategory"]), r["install_code"]
        d = ww = hh = ll = a = g = None
        if ic in ("AHU_LARGE", "FAN"):
            a = n[0] if n else None
        elif ic == "DUCT_FITTING" and len(n) >= 2:
            g, d = n[0], n[1]             # B90-125 -> angle 90, DN125
        elif sub in ("Rectangular", "VAV rectangular", "Rectangular duct", "Rectangular seal", "Inspection cover") and len(n) >= 2:
            ww, hh = n[0], n[1]
            ll = n[2] if len(n) >= 3 else None
        elif n:
            d = n[-1]
            if "Compact" in sub and len(n) >= 2:
                d, ll = n[0], n[1]
        dn.append(d); w.append(ww); h.append(hh); l.append(ll); af.append(a); ang.append(g)
    cat["s_dn"], cat["s_w"], cat["s_h"], cat["s_l"], cat["s_airflow"], cat["s_angle"] = dn, w, h, l, af, ang
    return cat


def _pick_dn(cands: pd.DataFrame, dn):
    if cands.empty:
        return None, False
    if dn is None or pd.isna(dn):
        return cands.iloc[0], False
    d = (cands["s_dn"] - dn).abs()
    best = cands.loc[d.idxmin()]
    return best, bool(d.min() < 1)


def _pick_rect(cands: pd.DataFrame, w, h, l=None):
    if cands.empty:
        return None, False
    if w is None or pd.isna(w) or h is None or pd.isna(h):
        return cands.iloc[0], False
    def score(r):
        a = abs(r.s_w - w) + abs(r.s_h - h)
        b = abs(r.s_w - h) + abs(r.s_h - w)
        s = min(a, b)
        if l is not None and not pd.isna(l) and r.s_l is not None and not pd.isna(r.s_l):
            s += abs(r.s_l - l) * 0.5
        return s
    sc = cands.apply(score, axis=1)
    best = cands.loc[sc.idxmin()]
    return best, bool(sc.min() < 1)


def _pick_airflow(cands: pd.DataFrame, af):
    if cands.empty:
        return None, False
    if af is None or pd.isna(af):
        return cands.iloc[0], False
    bigger = cands[cands["s_airflow"] >= af]
    best = bigger.loc[bigger["s_airflow"].idxmin()] if not bigger.empty else cands.loc[cands["s_airflow"].idxmax()]
    return best, abs(best.s_airflow - af) / af <= 0.15


# --------------------------------------------------------------------------- core
def _result(product=None, install="UNKNOWN", status="review_required", conf=CONF["review"], reason="",
            category="Other", exact=None, qty_override=None):
    out = {"product_id": "", "install_code": install, "status": status, "match_confidence": conf,
           "match_reason": reason, "category": category, "quantity_assumed": qty_override, "qty_factor": 1.0}
    if product is not None:
        out["product_id"] = product["product_id"]
        out["install_code"] = product["install_code"]
        out["category"] = product["category"]
        supplier = str(product["supplier_quote_required"]).lower() == "true" or product["source_type"] == "supplier_package"
        if status in ("auto",):
            if supplier:
                out["status"] = "supplier_quote_required"
                out["match_confidence"] = CONF["supplier"] if exact else CONF["nearest"]
            elif exact:
                out["status"], out["match_confidence"] = "calculated", CONF["exact"]
            else:
                out["status"], out["match_confidence"] = "assumption_applied", CONF["nearest"]
                out["match_reason"] = (reason + "; nearest catalogue size used").strip("; ")
    return out


def match_position(row: dict, cat: pd.DataFrame, opts: dict | None = None) -> dict:
    opts = opts or {}
    title = str(row.get("title", ""))
    raw = str(row.get("raw_line", ""))
    primary = f"{title} {raw}".lower()
    ctx = str(row.get("context", "")).lower()
    code = row.get("component_code", "") or ""
    qty = row.get("quantity")
    unit = row.get("unit", "")
    dn, w, h, l = row.get("dn_mm"), row.get("w_mm"), row.get("h_mm"), row.get("l_mm")
    sub = lambda s: cat[cat["subcategory"] == s]
    has = lambda *ks: any(k in primary for k in ks)

    # ---- equipment block --------------------------------------------------------------
    if code == "SUBCOMPONENT":
        return _result(status="non_priceable", conf=CONF["classified"], category="Equipment",
                       reason="Sub-component of the air-handling unit above; included in AHU supplier package")
    if code == "EQUIPMENT":
        if title.lower().startswith(("fortluft", "abluft")):
            return _result(status="non_priceable", conf=CONF["classified"], category="Equipment",
                           reason="Exhaust section of the system AHU (same offer no.); priced within the AHU package")
        p, exact = _pick_airflow(sub("Air-handling unit"), row.get("airflow_m3h"))
        r = _result(p, status="auto", exact=exact,
                    reason=f"AHU sized by airflow {row.get('airflow_m3h') or '?'} m³/h → {p['model']}")
        if qty is None or pd.isna(qty):
            r["quantity_assumed"] = 1.0
            r["match_reason"] += "; quantity blank in tender, 1 unit assumed"
            r["match_confidence"] = min(r["match_confidence"], 0.6)
        return r

    # ---- Bauteilliste (duct take-off) -------------------------------------------------
    if row.get("source_kind") == "Bauteilliste":
        if code == "R-R":
            p, exact = _pick_dn(sub("Circular duct"), dn)
            return _result(p, status="auto", exact=exact, reason=f"Spiral duct DN{dn:.0f} from NOVA take-off")
        if code in ("L", "LT"):
            p, exact = _pick_rect(sub("Rectangular duct"), w, h)
            return _result(p, status="auto", exact=exact,
                           reason=f"Rectangular duct {w:.0f}x{h:.0f} → surface m² from length × perimeter")
        if code == "BGE":
            c = cat[(cat["subcategory"] == "Circular bend")]
            ang = row.get("angle_deg")
            same = c[c["s_angle"] == ang] if ang is not None and not pd.isna(ang) else c
            p, exact = _pick_dn(same if not same.empty else c, dn)
            return _result(p, status="auto", exact=exact, reason=f"Circular bend DN{dn:.0f} {ang or ''}°")
        if code in ("ATE", "USE"):
            p, _ = _pick_dn(cat[cat["subcategory"] == "Circular bend"], dn)
            r = _result(p, status="auto", exact=False, reason="Round tee/reducer priced with same-DN bend as proxy")
            r["status"], r["match_confidence"] = "assumption_applied", CONF["assumption"]
            return r
        if code in ("MFA", "DRE", "SR"):
            return _result(status="non_priceable", conf=CONF["classified"], category="Ductwork",
                           install="DUCT_FITTING", reason="Coupling / end cap / spigot – covered by small-material allowance")
        if opts.get("rect_fitting_equivalent", True) and w is not None and not pd.isna(w) and h is not None and not pd.isna(h):
            eq_len = float(opts.get("rect_fitting_equiv_length_m", 1.0))
            p, _ = _pick_rect(sub("Rectangular duct"), w, h)
            r = _result(p, status="auto", exact=False, reason="")
            perim = 2 * (w + h) / 1000.0
            r.update(install_code="DUCT_FITTING", status="assumption_applied", match_confidence=CONF["assumption"],
                     qty_factor=round(perim * eq_len, 4),
                     match_reason=f"Rectangular fitting priced as {perim * eq_len:.2f} m² of {p['model']} (perimeter × {eq_len} m); fitting labour")
            return r
        return _result(install="DUCT_FITTING", category="Ductwork",
                       reason="Rectangular fitting – no catalogue item; labour estimated, material needs review")

    # ---- scope / services -------------------------------------------------------------
    if "nicht bestandteil" in primary or "separate ausschreibung" in primary:
        return _result(status="out_of_scope", conf=CONF["classified"], reason="Explicitly excluded from this tender")
    if unit == "manday":
        return _result(install="LABOUR_DAY", status="assumption_applied", conf=CONF["assumption"], category="Services",
                       reason="Man-days converted at 8 h/day, installer rate")
    if unit == "h":
        if "einregul" in primary:
            return _result(install="LABOUR_COMMISSIONING", status="assumption_applied", conf=CONF["assumption"],
                           category="Services", reason="Hourly commissioning, commissioning-specialist rate")
        return _result(install="LABOUR_HOUR", status="assumption_applied", conf=CONF["assumption"], category="Services",
                       reason="Hourly installation work, installer rate")
    if "montage und transport" in primary:
        return _result(status="non_priceable", conf=CONF["classified"], category="Services",
                       reason="Lump-sum montage & transport: covered by position labour and transport/equipment %")
    if "hygiene" in ctx and ("montage und transport" in primary or "laboranalysen" in primary or "einbau der bauseits" in primary):
        return _result(status="non_priceable", conf=CONF["classified"], category="Services",
                       reason="Lump sum montage/transport/hygiene: covered by labour, transport % and hygiene allowance")
    if "kanaldichtheit" in primary:
        return _result(category="Services", reason="Third-party duct leakage test – obtain test-company quote")

    if qty is None or pd.isna(qty):
        return _result(status="insufficient_information", conf=CONF["review"],
                       reason="Quantity blank in tender – cannot price")

    # ---- air terminals ---------------------------------------------------------------
    if "tellerventil" in primary:
        if "abluft" in primary:
            p, exact = _pick_dn(sub("Exhaust valve"), dn)
        else:
            p, exact = _pick_dn(sub("Supply valve"), dn)
        return _result(p, status="auto", exact=exact, reason=f"Disc valve DN{dn or '?'}")
    if has("gitter", "regenhut", "lamellenhut", "überströmer", "wirbelstrahl", "düsenrohr", "frontplatte",
           "dekorlochblech", "einbausatz für überström"):
        return _result(install="DIFFUSER", category="Air terminal",
                       reason="Grille / cowl / special outlet – no catalogue item; supplier price needed")

    # ---- fire & dampers --------------------------------------------------------------
    if "brandschutzklappe" in primary:
        p, exact = _pick_dn(sub("Fire damper"), dn)
        return _result(p, status="auto", exact=exact, reason="Fire damper EI90-S with actuator")
    if "drosselklappe" in primary:
        p, exact = _pick_dn(sub("Manual damper"), dn)
        return _result(p, status="auto", exact=exact, reason="Manual balancing damper")

    # ---- flow controllers ------------------------------------------------------------
    if "volumenstromregler" in primary or re.search(r"\b(tvr|tvj|vfc)\b", primary):
        if "konstant" in primary or "vfc" in primary:
            p, exact = _pick_dn(sub("CAV circular"), dn)
            return _result(p, status="auto", exact=exact, reason="Constant-volume controller")
        if w is not None and not pd.isna(w):
            p, exact = _pick_rect(sub("VAV rectangular"), w, h)
        else:
            p, exact = _pick_dn(sub("VAV circular"), dn)
        return _result(p, status="auto", exact=exact, reason="Variable-volume controller")

    # ---- silencers -------------------------------------------------------------------
    if "schalldämpfer" in primary:
        if "kompakt" in primary or "rohrschall" in primary:
            n = _nums(re.sub(r"\d+(?:\.\d+)?x\d+(?:\.\d+)?", "", raw.split("Stk")[0]))
            d = n[1] * 10 if len(n) >= 2 and n[1] < 100 else dn
            p, exact = _pick_dn(sub("Compact"), d)
            r = _result(p, status="auto", exact=exact, reason=f"Compact/round silencer DN{d or '?'}")
            return r
        p, exact = _pick_rect(sub("Rectangular"), w, h, l)
        return _result(p, status="auto", exact=exact, reason=f"Rectangular silencer {w or '?'}x{h or '?'}x{l or '?'}")

    if re.search(r"revisi\w*deckel", primary):
        p, exact = _pick_rect(sub("Inspection cover"), w, h)
        return _result(p, status="auto", exact=exact, reason="Inspection cover in fire insulation")

    # ---- insulation ------------------------------------------------------------------
    if "dämmung" in primary or "ummantelung" in primary:
        if "brandschutz" in primary or re.search(r"\bei\s?\d{2}", primary):
            return _result(install="INSULATION_60", category="Insulation",
                           reason="Fire-rated insulation – no catalogue item; certified-system price needed")
        if has("wetterfest", "ummantelung", "verblechung"):
            p = cat[cat["product_id"] == "P-INS-003"].iloc[0]
            return _result(p, status="auto", exact=True, reason="Weatherproof 100 mm insulation with cladding")
        if re.search(r"\b30\s?/", primary) or "30 mm" in primary:
            p = cat[cat["product_id"] == "P-INS-001"].iloc[0]
            return _result(p, status="auto", exact=True, reason="30 mm mineral-wool insulation")
        if re.search(r"\b60\s?/", primary) or "60 mm" in primary:
            p = cat[cat["product_id"] == "P-INS-002"].iloc[0]
            return _result(p, status="auto", exact=True, reason="60 mm mineral-wool insulation")
        if re.search(r"\b100\s?/", primary):
            p = cat[cat["product_id"] == "P-INS-002"].iloc[0]
            return _result(p, status="auto", exact=False,
                           reason="100 mm thermal insulation – priced with 60 mm item (understated, review)")
        p = cat[cat["product_id"] == "P-INS-001"].iloc[0]
        return _result(p, status="auto", exact=False, reason="Thin duct insulation – priced with 30 mm item")

    # ---- fire stopping / supports / covers -------------------------------------------
    if "durchdringung" in primary or "brandabschnitt" in primary:
        if dn is not None and not pd.isna(dn):
            p, exact = _pick_dn(sub("Circular seal"), dn)
        else:
            p, exact = _pick_rect(sub("Rectangular seal"), w, h)
        return _result(p, status="auto", exact=exact, reason="EI30 certified penetration seal")
    if "anschlusswink" in primary:
        p = cat[cat["product_id"] == "P-SUP-001"].iloc[0]
        return _result(p, status="auto", exact=True, reason="Connection-angle set per penetration")
    if "putzdeckel" in primary or ("wie vorbeschrieben" in primary and "isoliert" in primary):
        p, _ = _pick_rect(sub("Inspection cover"), w, h)
        r = _result(p, status="auto", exact=False, reason="Cleaning cover priced with inspection-cover item")
        r["status"], r["match_confidence"] = "assumption_applied", CONF["assumption"]
        return r

    # ---- controls / field devices ----------------------------------------------------
    if has("drehantrieb", "klappenantrieb"):
        p = cat[cat["product_id"] == "P-CTL-003"].iloc[0]
        return _result(p, status="auto", exact=True, reason="Damper actuator 24 V")
    if has("temperaturfühler", "feuchtefühler", "frostschutz", "temperatur- und feuchte"):
        p = cat[cat["product_id"] == "P-CTL-002"].iloc[0]
        r = _result(p, status="auto", exact="feuchte" not in primary and "frost" not in primary, reason="Temperature sensor")
        return r
    if has("druckdifferenz", "druckwächter"):
        p = cat[cat["product_id"] == "P-CTL-001"].iloc[0]
        return _result(p, status="auto", exact="druckdifferenz" in primary, reason="Differential-pressure device")
    if has("volumenstrom-mess", "transmitter"):
        p = cat[cat["product_id"] == "P-CTL-004"].iloc[0]
        return _result(p, status="auto", exact=True, reason="Volume-flow transmitter")
    if has("rauchmelder", "zeigerthermometer", "montagerahmen"):
        return _result(install="CONTROL_POINT", category="Controls", reason="Field instrument – no catalogue item")

    # ---- minor items -----------------------------------------------------------------
    if has("bezeichnungsschild", "farbpfeil", "potentialverbindung"):
        return _result(status="non_priceable", conf=CONF["classified"],
                       reason="Labelling / bonding sundries – covered by small-material allowance")
    if has("farbbeschichtung", "verlängerung", "sockelrohr", "verbindungsflansch"):
        return _result(install="UNKNOWN", category="Air terminal", reason="Accessory to cowl – price with supplier offer")
    if "erdverleg" in ctx or has("erdverleg", "ringraumdichtung", "mauerkragen"):
        return _result(category="Ductwork", reason="Earth-laid duct system (special supplier offer) – request quote")
    if has("kassette", "lüftungsdecke", "l-profil", "deckenunterkonstruktion", "dqa", "dfd", "dsd", "evs-", "abziehen der folie") or title.strip() == "Küche":
        return _result(category="Kitchen ceiling", reason="Kitchen ventilation-ceiling package – supplier quote needed")
    if has("dehnungsmanschette", "manschette"):
        return _result(install="DUCT_FITTING", category="Ductwork", reason="Flexible connector – no catalogue item")
    if has("montagefüsse", "montageschiene"):
        return _result(install="SUPPORT_SET", category="Support", reason="Roof mounting system – no catalogue item")
    if has("versandkosten", "statische berechnung"):
        return _result(status="non_priceable", conf=CONF["classified"], category="Services",
                       reason="Freight / static calc of special supplier offer")
    return _result(status="review_required", conf=CONF["fallback"], reason="No matching rule – manual review")


def match_all(positions: pd.DataFrame, catalog: pd.DataFrame, opts: dict | None = None) -> pd.DataFrame:
    cat = catalog_sizes(catalog)
    res = [match_position(r, cat, opts) for r in positions.to_dict("records")]
    out = pd.concat([positions.reset_index(drop=True), pd.DataFrame(res)], axis=1)
    out["quantity_source"] = out["quantity"].apply(lambda q: "tender" if pd.notna(q) else "")
    out["quantity"] = pd.to_numeric(out["quantity"], errors="coerce").astype(float)
    qa = pd.to_numeric(out["quantity_assumed"], errors="coerce")
    m = qa.notna() & out["quantity"].isna()
    if m.any():
        out.loc[m, "quantity"] = qa[m].astype(float)
        out.loc[m, "quantity_source"] = "assumed"
    out["review_required"] = ~out["status"].isin(["calculated"]) & ~out["status"].isin(["out_of_scope", "non_priceable"])
    return out.drop(columns=["quantity_assumed"])
