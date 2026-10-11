"""STEP 3 — LLM translate + retrieve + rerank matching.

    matched = match_positions(positions, catalog, llm=..., config=...)

Pipeline per position:
    1. TRANSLATE  description -> English (any source language), original kept.
    2. RETRIEVE   shortlist N catalogue candidates by keyword + size proximity.
    3. RERANK     LLM picks the best candidate, or "none", with confidence + reason.
    4. GUARD      deterministic post-checks so the model cannot emit an inconsistent row.

Output rows carry the position fields plus the match columns the pricing engine
(step 4) expects: product_id, install_code, status, category, qty_factor.
"""
from __future__ import annotations

import re

from .config import LLMConfig, MatchConfig
from .llm import LLMError, build_llm

STATUSES = ["calculated", "supplier_quote_required", "assumption_applied", "review_required",
            "insufficient_information", "out_of_scope", "non_priceable"]
PRICED_STATUSES = {"calculated", "supplier_quote_required", "assumption_applied"}

MATCH_COLUMNS = ["product_id", "install_code", "status", "match_confidence", "match_reason",
                 "category", "qty_factor", "description_en", "matcher"]

TRANSLATE_SYSTEM = (
    "You translate HVAC tender item descriptions into concise technical English. "
    "You keep product designations, article codes and dimensions exactly as written. "
    "You return ONLY JSON."
)
TRANSLATE_USER = """Translate each description into English.

{items}

Rules:
- Keep all numbers, sizes and designations verbatim (e.g. "DN125", "400x300", "TVR-D").
- Use standard HVAC English (Tellerventil -> supply/exhaust air valve, Schalldämpfer -> silencer,
  Volumenstromregler -> volume flow controller, Brandschutzklappe -> fire damper).
- Do not add or omit information.

Reply with JSON only: {{"items": [{{"id": <id>, "en": "<english>"}}]}}
"""

RERANK_SYSTEM = (
    "You are an HVAC estimator matching Swiss BKP-244 tender positions to a product catalogue. "
    "You NEVER force a match: if no candidate is a defensible technical equivalent you return an "
    "empty product_id. You return ONLY JSON."
)
RERANK_USER = """For each tender position choose the best catalogue item from ITS candidate list.

Positions:
{blocks}

Rules:
- product_id MUST be copied from that position's candidate list, or "" if none fits.
- install_code MUST be that candidate's install_code.
- status: calculated (confident equivalent) | supplier_quote_required (packages/special items)
  | assumption_applied (nearest size / reasonable substitute) | review_required (no defensible match)
  | insufficient_information (no quantity) | non_priceable (services, sundries, lump sums).
- quantity is NOT used to choose a product except to sanity-check size.
- confidence: 0..1, and give a ONE SENTENCE reason naming the deciding attribute.
- Match on FUNCTION, SIZE and TYPE. A grille is not a valve; a duct is not a fitting.

Reply with JSON only: {{"matches": [{{"position_id": "", "product_id": "", "install_code": "",
"status": "", "confidence": 0.0, "reason": ""}}]}}
"""


# --------------------------------------------------------------------------- catalogue sizes
def _nums(s: str):
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", s or "")]


def catalog_with_sizes(catalog):
    """Attach s_dn / s_w / s_h / s_l / s_airflow parsed from the model string.

    Mirrors engine/matcher.py:catalog_sizes so this step stays self-contained.
    """
    out = catalog.copy()
    dn, w, h, l, af = [], [], [], [], []
    for _, r in out.iterrows():
        n = _nums(str(r.get("model", "")).replace("x", " "))
        sub, ic = str(r.get("subcategory", "")), str(r.get("install_code", ""))
        d = ww = hh = ll = a = None
        if ic in ("AHU_LARGE", "FAN"):
            a = n[0] if n else None
        elif ic == "DUCT_FITTING" and len(n) >= 2:
            d = n[1]
        elif sub in ("Rectangular", "VAV rectangular", "Rectangular duct", "Rectangular seal",
                     "Inspection cover") and len(n) >= 2:
            ww, hh = n[0], n[1]
            ll = n[2] if len(n) >= 3 else None
        elif n:
            d = n[-1]
            if "Compact" in sub and len(n) >= 2:
                d, ll = n[0], n[1]
        dn.append(d); w.append(ww); h.append(hh); l.append(ll); af.append(a)
    out["s_dn"], out["s_w"], out["s_h"], out["s_l"], out["s_airflow"] = dn, w, h, l, af
    return out


def _tok(s: str):
    return {t for t in re.findall(r"[a-zA-ZäöüÄÖÜß]{3,}", (s or "").lower())}


def retrieve_candidates(position: dict, cat, k: int = 12):
    """Top-k catalogue rows for a position, by keyword overlap + size proximity."""
    text = " ".join(str(position.get(f, "")) for f in ("description", "description_en", "title"))
    tok = _tok(text)
    p_dn, p_w, p_h, p_af = (position.get(f) for f in ("dn_mm", "w_mm", "h_mm", "airflow_m3h"))
    scored = []
    for _, r in cat.iterrows():
        ctok = _tok(f"{r.get('description','')} {r.get('subcategory','')} {r.get('category','')} "
                    f"{r.get('model','')} {r.get('manufacturer','')}")
        score = 2.0 * len(tok & ctok) / max(1, min(len(tok), 12))
        if p_dn and r.get("s_dn") is not None:
            rel = abs(r["s_dn"] - p_dn) / max(1.0, p_dn)
            score += 1.0 if rel < 0.02 else (0.5 if rel < 0.2 else 0.0)
        if p_w and p_h and r.get("s_w") is not None and r.get("s_h") is not None:
            a = abs(r["s_w"] - p_w) + abs(r["s_h"] - p_h)
            b = abs(r["s_w"] - p_h) + abs(r["s_h"] - p_w)
            rel = min(a, b) / max(1.0, p_w + p_h)
            score += 1.0 if rel < 0.05 else (0.5 if rel < 0.4 else 0.0)
        if p_af and r.get("s_airflow"):
            score += 1.0 if r["s_airflow"] >= p_af else 0.3
        scored.append((score, r))
    scored.sort(key=lambda t: -t[0])
    return [r for _, r in scored[:k]]


# --------------------------------------------------------------------------- translate
def translate_descriptions(llm, positions: list[dict], batch: int = 40) -> dict[str, str]:
    """original description -> English. Returns {} on failure (caller keeps originals)."""
    uniq = []
    seen = set()
    for p in positions:
        d = str(p.get("description") or "").strip()
        if d and d not in seen:
            seen.add(d)
            uniq.append(d)
    if not uniq:
        return {}
    mapping: dict[str, str] = {}
    for i in range(0, len(uniq), batch):
        chunk = uniq[i:i + batch]
        items = "\n".join(f'{{"id": {j}, "text": {chunk[j - i]!r}}}' for j in range(i, i + len(chunk)))
        try:
            reply = llm.complete_json(TRANSLATE_SYSTEM, TRANSLATE_USER.format(items=items), tag="translate")
        except LLMError:
            continue
        for it in (reply.get("items", []) if isinstance(reply, dict) else []):
            try:
                idx = int(it["id"])
                mapping[chunk[idx - i]] = str(it.get("en") or "").strip()
            except (KeyError, ValueError, IndexError, TypeError):
                continue
    return mapping


# --------------------------------------------------------------------------- guard
def _guard(position: dict, cand: dict | None, product_id: str, install_code: str = "",
           status: str = "", conf=None, reason: str = "", trust_status: bool = False) -> dict:
    """Deterministic post-checks. The LLM proposes; this decides what is allowed."""
    qty = position.get("quantity")
    if not product_id or cand is None:
        # No catalogue product -> the row stays UNPRICED, but a labour-only rule
        # (SUPPORT_SET, LABOUR_DAY, DUCT_FITTING, ...) must keep its install_code,
        # otherwise the hours are lost and the row prices at zero.
        st = status if status in STATUSES else "review_required"
        # A PRICED status without a catalogue product is only allowed when the rule
        # matcher deliberately priced a labour-only row (man-days, drawings) and we
        # were told to trust it. Any unpriced status is kept as given.
        if st in PRICED_STATUSES and not trust_status:
            st = "insufficient_information" if qty in (None, "") else "review_required"
        return {"product_id": "",
                "install_code": install_code
                                 or (cand.get("install_code") if cand is not None else "")
                                 or "UNKNOWN",
                "status": st,
                "match_confidence": min(float(conf or 0.0), 0.4),
                "match_reason": reason or "No defensible catalogue match – manual review",
                "category": (cand.get("category") if cand is not None else None) or "Other",
                "qty_factor": 1.0}
    supplier = (str(cand.get("supplier_quote_required", "")).lower() == "true"
                or cand.get("source_type") == "supplier_package")
    st = status if status in STATUSES else "assumption_applied"
    if st in PRICED_STATUSES and supplier and st == "calculated":
        st = "supplier_quote_required"
    if st not in PRICED_STATUSES:
        st = "review_required"
    return {"product_id": product_id,
            "install_code": install_code or cand.get("install_code", "UNKNOWN"),
            "status": st,
            "match_confidence": float(conf) if conf is not None else 0.6,
            "match_reason": reason or "LLM match",
            "category": cand.get("category", "Other"),
            "qty_factor": 1.0}


def _rule_match(position: dict, catalog):
    """Per-row fallback: the existing deterministic keyword matcher."""
    try:
        from engine.matcher import catalog_sizes, match_position
    except ImportError:
        return None
    try:
        res = match_position(position, catalog_sizes(catalog))
    except Exception:                              # noqa: BLE001
        return None
    pid = res.get("product_id", "")
    cand = catalog[catalog["product_id"] == pid]
    row = cand.iloc[0].to_dict() if len(cand) else None
    merged = _guard(position, row, pid, res.get("install_code", ""),
                    res.get("status", "review_required"),
                    res.get("match_confidence"), res.get("match_reason", ""),
                    trust_status=True)
    # rows whose quantity is blank in the tender get the assumed quantity (mirrors match_all)
    qa = res.get("quantity_assumed")
    if qa is not None and position.get("quantity") in (None, ""):
        merged["quantity"] = qa
    return merged


# --------------------------------------------------------------------------- main
def match_positions(positions: list[dict], catalog, llm=None, config: MatchConfig | None = None,
                    llm_config: LLMConfig | None = None, progress=None) -> list[dict]:
    """STEP 3. positions + catalogue -> rows with product_id / install_code / status / confidence / reason."""
    cfg = config or MatchConfig()
    llm = llm if llm is not None else build_llm(llm_config)
    cat = catalog_with_sizes(catalog)
    by_id = cat.set_index("product_id")

    # 1. translate
    translations: dict[str, str] = {}
    if cfg.translate:
        translations = translate_descriptions(llm, positions, batch=cfg.translate_batch)
        if progress:
            progress(0.25)

    rows = []
    # 2. retrieve
    prepared = []
    for p in positions:
        p = dict(p)
        p["description_en"] = translations.get(str(p.get("description") or "").strip(), "")
        cands = retrieve_candidates(p, cat, k=cfg.n_candidates)
        prepared.append((p, cands))

    # 3. rerank in batches
    results: dict[str, dict] = {}
    if cfg.use_llm:
        for i in range(0, len(prepared), cfg.batch_size):
            chunk = prepared[i:i + cfg.batch_size]
            blocks = []
            for p, cands in chunk:
                listing = "\n".join(
                    f"      {r.get('product_id', '')} | {r.get('install_code', '')} | {r.get('description', '')} "
                    f"| unit {r.get('unit', '')} | {r.get('source_type', '')}" for r in cands)
                blocks.append(
                    f"- position_id {p.get('position_id')}\n"
                    f"  text: {p.get('description','')}\n"
                    f"  english: {p.get('description_en','')}\n"
                    f"  qty {p.get('quantity')} {p.get('unit','')}, dn {p.get('dn_mm')}, "
                    f"w {p.get('w_mm')}, h {p.get('h_mm')}, l {p.get('l_mm')}, "
                    f"airflow {p.get('airflow_m3h')}\n"
                    f"  candidates:\n{listing}")
            try:
                reply = llm.complete_json(RERANK_SYSTEM, RERANK_USER.format(blocks="\n".join(blocks)), tag="rerank")
                for m in (reply.get("matches", []) if isinstance(reply, dict) else []):
                    if isinstance(m, dict) and m.get("position_id"):
                        results[str(m["position_id"])] = m
            except LLMError:
                pass
            if progress:
                progress(0.25 + 0.75 * min(1.0, (i + cfg.batch_size) / max(1, len(prepared))))

    # 4. guard + fallback
    #   valid LLM product        -> use the LLM decision
    #   LLM said "none"          -> respect the judgement: leave the row unpriced
    #   LLM answer invalid/absent -> fall back to the deterministic rule matcher
    for p, _cands in prepared:
        pid = str(p.get("position_id") or "")
        m = results.get(pid)
        cand = None
        llm_says_none = False
        if m is not None:
            proposed = str(m.get("product_id") or "")
            if proposed and proposed in by_id.index:
                cand = by_id.loc[[proposed]].iloc[0].to_dict()
            elif not proposed:
                llm_says_none = True          # deliberate "no defensible match"

        if m is not None and cand is not None:
            merged = _guard(p, cand, str(m["product_id"]), str(m.get("install_code") or ""),
                            str(m.get("status") or ""), m.get("confidence"), str(m.get("reason") or ""))
            merged["matcher"] = "llm"
        elif llm_says_none:
            merged = _guard(p, None, "", "", "review_required", m.get("confidence"),
                            str(m.get("reason") or "No defensible catalogue match"))
            merged["matcher"] = "llm"
        else:
            merged = _rule_match(p, catalog)
            if merged is None:
                merged = _guard(p, None, "", "", "review_required", 0.0, "no matcher available")
            merged["matcher"] = "rules"
        rows.append({**p, **merged})
    return rows
