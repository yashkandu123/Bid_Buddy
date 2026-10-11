from pathlib import Path
import os
import sys
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
BUNDLE_ROOT = ROOT / "experiments" / "pipeline_bundle"
sys.path.insert(0, str(BUNDLE_ROOT))

from pipeline import (  # noqa: E402
    LLMConfig,
    MatchConfig,
    StubLLM,
    build_llm,
    catalog_with_sizes,
    match_positions,
    retrieve_candidates,
)


class PipelineBundleCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = pd.read_csv(ROOT / "catalog.csv")
        cls.sized_catalog = catalog_with_sizes(cls.catalog)

    def test_translated_multilingual_retrieval_is_catalogue_bounded(self) -> None:
        catalogue_ids = set(self.catalog["product_id"])
        for language, description in (
            ("de", "Zuluft Tellerventil DN125"),
            ("fr", "Bouche de soufflage DN125"),
            ("en", "Supply air valve DN125"),
        ):
            with self.subTest(language=language):
                candidates = retrieve_candidates(
                    {
                        "description": description,
                        "description_en": "Supply air valve DN125",
                        "dn_mm": 125,
                        "w_mm": None,
                        "h_mm": None,
                        "airflow_m3h": None,
                    },
                    self.sized_catalog,
                    k=5,
                )
                self.assertLessEqual(len(candidates), 5)
                self.assertTrue({row["product_id"] for row in candidates} <= catalogue_ids)
                self.assertEqual(candidates[0]["product_id"], "P-AIR-002")

    def test_hallucinated_product_id_is_rejected_offline(self) -> None:
        position = {
            "position_id": "AUDIT-1",
            "description": "Zuluft Tellerventil DN125",
            "description_en": "Supply air valve DN125",
            "quantity": 1,
            "unit": "pc",
            "dn_mm": 125,
            "w_mm": None,
            "h_mm": None,
            "airflow_m3h": None,
        }
        provider = StubLLM(
            [{"matches": [{
                "position_id": "AUDIT-1",
                "product_id": "NOT-IN-CATALOGUE",
                "install_code": "DIFFUSER",
                "status": "calculated",
                "confidence": 0.99,
                "reason": "invalid test response",
            }]}]
        )
        result = match_positions(
            [position],
            self.catalog,
            llm=provider,
            config=MatchConfig(use_llm=True, translate=False, batch_size=1),
        )[0]
        self.assertNotEqual(result["product_id"], "NOT-IN-CATALOGUE")
        self.assertEqual(result["matcher"], "rules")

    def test_no_environment_key_selects_stub_without_network(self) -> None:
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "", "DEEPSEEK_API_KEY": "", "OPENROUTER_API_KEY": ""},
            clear=False,
        ):
            provider = build_llm(LLMConfig(provider="openai", api_key=""))
        self.assertIsInstance(provider, StubLLM)


if __name__ == "__main__":
    unittest.main()
