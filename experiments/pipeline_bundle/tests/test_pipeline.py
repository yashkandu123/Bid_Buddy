"""Tests for pipeline steps 2 and 3 (no API key required)."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.pricing import SimSettings, calc_positions, project_summary   # noqa: E402
from pipeline import (                                                    # noqa: E402
    ExtractConfig, LLMConfig, MatchConfig, StubLLM, build_llm,
    extract_positions, match_positions, parse_json_response, translate_descriptions,
)

D = ROOT / "data"
LV_BASELINE = 1697469.34          # locked scope: LV pages only


@pytest.fixture(scope="module")
def data():
    return {
        "catalog": pd.read_csv(D / "catalog.csv"),
        "productivity": pd.read_csv(D / "productivity.csv"),
        "params": json.loads((D / "project_parameters.json").read_text()),
        "pdf": (D / "BKP_244_LV_Lueftung_260804.pdf").read_bytes(),
    }


@pytest.fixture(scope="module")
def positions(data):
    return extract_positions(
        data["pdf"], llm=StubLLM([]), config=ExtractConfig(use_docling=False, use_llm=False)
    )


# ------------------------------------------------------------------ llm layer
def test_parse_json_tolerates_fences_and_prose():
    assert parse_json_response('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_response('Here you go: {"a": [1, 2]} thanks') == {"a": [1, 2]}
    assert parse_json_response('[{"x": 1}]') == [{"x": 1}]


def test_stub_llm_repeats_last_response():
    llm = StubLLM([{"n": 1}, {"n": 2}])
    assert llm.complete_json("s", "u") == {"n": 1}
    assert llm.complete_json("s", "u") == {"n": 2}
    assert llm.complete_json("s", "u") == {"n": 2}


def test_build_llm_without_key_is_stub():
    llm = build_llm(LLMConfig(provider="openai", api_key=""))
    assert isinstance(llm, StubLLM)


# ------------------------------------------------------------------ step 2
def test_step2_extracts_lv_pages_only(positions):
    assert len(positions) == 263, f"expected 263 LV positions, got {len(positions)}"
    assert all(p["source_kind"] == "LV" for p in positions)
    assert all(p["extractor"] == "regex" for p in positions)
    assert len({p["position_id"] for p in positions}) == 263


def test_step2_rows_are_pricing_engine_compatible(positions):
    required = {"position_id", "system", "section", "source_page", "description",
                "quantity", "unit", "dn_mm", "w_mm", "h_mm", "l_mm", "airflow_m3h"}
    assert required.issubset(positions[0].keys())


# ------------------------------------------------------------------ step 3
def test_step3_rule_path_reproduces_locked_baseline(data, positions):
    matched = match_positions(positions, data["catalog"], llm=StubLLM([]),
                              config=MatchConfig(use_llm=False, translate=False))
    df = pd.DataFrame(matched)
    df["include"] = True
    df["custom_unit_cost_chf"] = np.nan
    sim = SimSettings.from_params(data["params"])
    calc = calc_positions(df, data["catalog"], data["productivity"], sim)
    summary = project_summary(calc, data["params"], sim)
    assert summary["positions_total"] == 263
    assert abs(summary["cost_baseline"] - LV_BASELINE) < 6.0, summary["cost_baseline"]


def test_step3_emits_match_columns(data, positions):
    matched = match_positions(positions, data["catalog"], llm=StubLLM([]),
                              config=MatchConfig(use_llm=False, translate=False))
    df = pd.DataFrame(matched)
    for col in ["product_id", "install_code", "status", "match_confidence",
                "match_reason", "category", "qty_factor", "description_en", "matcher"]:
        assert col in df.columns, col
    assert df["status"].isin(["calculated", "supplier_quote_required", "assumption_applied",
                              "review_required", "insufficient_information",
                              "non_priceable", "out_of_scope"]).all()


def test_step3_llm_path_applies_llm_match(data, positions):
    """Stub the LLM: translation reply first, then a rerank reply."""
    stub = StubLLM([
        {"items": [{"id": 0, "en": "Supply air valve DN100"}]},
        {"matches": [{"position_id": "P0001", "product_id": "P-AIR-001", "install_code": "DIFFUSER",
                      "status": "calculated", "confidence": 0.91, "reason": "stub match"}]},
    ])
    matched = match_positions(positions, data["catalog"], llm=stub,
                              config=MatchConfig(use_llm=True, translate=True,
                                                 translate_batch=10000, batch_size=500))
    by_id = {m["position_id"]: m for m in matched}
    assert by_id["P0001"]["product_id"] == "P-AIR-001"
    assert by_id["P0001"]["matcher"] == "llm"
    assert by_id["P0001"]["status"] == "calculated"
    assert len(stub.calls) >= 2


def test_guard_rejects_hallucinated_product(data, positions):
    """A product_id not in the catalogue must never be used; the row falls back to rules."""
    stub = StubLLM([
        {"items": []},
        {"matches": [{"position_id": "P0001", "product_id": "P-DOES-NOT-EXIST",
                      "install_code": "DIFFUSER", "status": "calculated",
                      "confidence": 0.99, "reason": "hallucinated"}]},
    ])
    matched = match_positions(positions[:5], data["catalog"], llm=stub,
                              config=MatchConfig(use_llm=True, translate=True,
                                                 translate_batch=10000, batch_size=500))
    row = next(m for m in matched if m["position_id"] == "P0001")
    assert row["product_id"] != "P-DOES-NOT-EXIST"      # hallucination rejected
    assert row["matcher"] == "rules"                     # deterministic fallback used


def test_llm_none_is_respected(data, positions):
    """When the LLM deliberately answers 'no defensible match', the row stays unpriced."""
    stub = StubLLM([
        {"items": []},
        {"matches": [{"position_id": "P0001", "product_id": "", "install_code": "",
                      "status": "review_required", "confidence": 0.2,
                      "reason": "nothing equivalent in the catalogue"}]},
    ])
    matched = match_positions(positions[:5], data["catalog"], llm=stub,
                              config=MatchConfig(use_llm=True, translate=True,
                                                 translate_batch=10000, batch_size=500))
    row = next(m for m in matched if m["position_id"] == "P0001")
    assert row["product_id"] == ""
    assert row["status"] == "review_required"
    assert row["matcher"] == "llm"


def test_guard_never_marks_supplier_package_calculated(data, positions):
    """The guard must downgrade a supplier package the LLM called 'calculated'."""
    stub = StubLLM([
        {"items": []},
        {"matches": [{"position_id": "P0001", "product_id": "P-AHU-1000", "install_code": "AHU_LARGE",
                      "status": "calculated", "confidence": 0.9, "reason": "supplier pkg"}]},
    ])
    matched = match_positions(positions[:5], data["catalog"], llm=stub,
                              config=MatchConfig(use_llm=True, translate=True,
                                                 translate_batch=10000, batch_size=500))
    row = next(m for m in matched if m["position_id"] == "P0001")
    assert row["product_id"] == "P-AHU-1000"
    assert row["status"] == "supplier_quote_required"


# ------------------------------------------------------------------ translation
def test_translate_maps_originals():
    stub = StubLLM([{"items": [{"id": 0, "en": "Fire damper DN100"}]}])
    descs = [{"description": "Brandschutzklappe DN100"}]
    out = translate_descriptions(stub, descs, batch=10)
    assert out["Brandschutzklappe DN100"] == "Fire damper DN100"


def test_translate_failure_returns_empty():
    class Boom:
        def complete_json(self, *a, **k):
            from pipeline import LLMError
            raise LLMError("down")

    assert translate_descriptions(Boom(), [{"description": "x"}]) == {}
