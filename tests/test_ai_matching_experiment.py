from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from src.tender_pricing.ai_matching_experiment import (
    AIMatchingValidationError,
    FakeAIProvider,
    OpenAIResponsesProvider,
    _parse_openai_response,
    build_ai_matching_prompt_case,
    build_position_input,
    create_provider,
    evaluate_against_human_labels,
    load_project_env,
    load_jsonl,
    retrieve_catalogue_candidates,
    run_ai_matching_case,
    run_experiment,
    validate_ai_ranker_output,
)
from src.tender_pricing.data_loading import load_project_data


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class MalformedProvider:
    name = "malformed"

    def rank_candidates(self, position, candidates):
        return {
            "lv_id": position["position_id"],
            "ranked_candidates": [{"product_id": "P-OUTSIDE-CATALOGUE"}],
            "recommendation": "accept",
            "recommended_product_id": "P-OUTSIDE-CATALOGUE",
            "rationale": "bad output",
        }


class Phase5AIMatchingExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = load_project_data(PROJECT_ROOT)
        cls.sample_records = load_jsonl(PROJECT_ROOT / "outputs" / "phase2_review_sample.jsonl")

    def test_position_input_schema_preserves_german_source_and_deterministic_result(self) -> None:
        position = build_position_input(self.sample_records[0])

        self.assertEqual(position["position_id"], "PDF079-02")
        self.assertEqual(position["source_language"], "de")
        self.assertIn("Abluft - Tellerventil", position["original_german_description"])
        self.assertEqual(position["current_status"], "review_required")
        self.assertEqual(position["deterministic_match"]["matched_product_id"], "P-AIR-003")
        self.assertIn("diameter_mismatch", {flag["code"] for flag in position["deterministic_match"]["conflict_flags"]})

    def test_candidate_retrieval_returns_only_catalogue_products_and_bounded_count(self) -> None:
        position = build_position_input(self.sample_records[0])
        candidates = retrieve_catalogue_candidates(position, self.data["catalog"], max_candidates=5)
        catalogue_ids = {row["product_id"] for row in self.data["catalog"]}

        self.assertLessEqual(len(candidates), 5)
        self.assertTrue(candidates)
        self.assertTrue({candidate["product_id"] for candidate in candidates} <= catalogue_ids)
        self.assertIn("P-AIR-003", {candidate["product_id"] for candidate in candidates})
        self.assertNotIn("net_cost_chf", candidates[0])

    def test_prompt_case_contains_no_prices_and_keeps_catalogue_candidate_boundary(self) -> None:
        position = build_position_input(self.sample_records[0])
        candidates = retrieve_catalogue_candidates(position, self.data["catalog"], max_candidates=3)
        prompt_case = build_ai_matching_prompt_case(position, candidates)

        self.assertIn("Abluft - Tellerventil", prompt_case["position"]["original_german_description"])
        self.assertEqual(len(prompt_case["catalogue_candidates"]), 3)
        self.assertNotIn("list_price_chf", prompt_case["catalogue_candidates"][0])
        self.assertIn("Do not invent products", prompt_case["task"])

    def test_validation_rejects_invented_product_ids(self) -> None:
        with self.assertRaises(AIMatchingValidationError):
            validate_ai_ranker_output(
                {
                    "lv_id": "PDF080-04",
                    "ranked_candidates": [{"product_id": "P-DOES-NOT-EXIST"}],
                    "recommendation": "accept",
                    "recommended_product_id": "P-DOES-NOT-EXIST",
                },
                {"P-AIR-001"},
            )

    def test_validation_rejects_malformed_abstention_with_product_id(self) -> None:
        with self.assertRaises(AIMatchingValidationError):
            validate_ai_ranker_output(
                {
                    "lv_id": "PDF080-04",
                    "ranked_candidates": [],
                    "recommendation": "abstain",
                    "recommended_product_id": "P-AIR-001",
                },
                {"P-AIR-001"},
            )

    def test_critical_technical_mismatch_downgrades_accept_to_review_only(self) -> None:
        position = build_position_input(self.sample_records[0])
        candidates = retrieve_catalogue_candidates(position, self.data["catalog"], max_candidates=5)
        result = validate_ai_ranker_output(
            {
                "lv_id": "PDF079-02",
                "ranked_candidates": [{"product_id": "P-AIR-003"}],
                "recommendation": "accept",
                "recommended_product_id": "P-AIR-003",
                "rationale": "fake accept",
            },
            {candidate["product_id"] for candidate in candidates},
            position,
            candidates,
        )

        self.assertEqual(result["recommendation"], "accept")
        self.assertEqual(result["safe_decision"], "review")
        self.assertFalse(result["pricing_authorized"])
        self.assertIn("diameter_mismatch", {flag["code"] for flag in result["validation_flags"]})

    def test_fake_provider_abstention_runs_without_network_or_costs(self) -> None:
        position = build_position_input(self.sample_records[9])
        result = run_ai_matching_case(position, self.data["catalog"], FakeAIProvider(decision="abstain"))

        self.assertIsNone(result["provider_error"])
        self.assertEqual(result["provider"], "fake")
        self.assertEqual(result["ai_result"]["recommendation"], "abstain")
        self.assertFalse(result["ai_result"]["pricing_authorized"])
        self.assertEqual(result["ai_result"]["usage"]["measurement_note"], "fake_provider_no_api_usage")

    def test_provider_errors_are_reported_without_fabricating_results(self) -> None:
        position = build_position_input(self.sample_records[0])
        result = run_ai_matching_case(position, self.data["catalog"], FakeAIProvider(fail=True))

        self.assertIsNotNone(result["provider_error"])
        self.assertIsNone(result["ai_result"])
        self.assertFalse(result["evaluation_ready"])

    def test_malformed_provider_output_fails_safely(self) -> None:
        position = build_position_input(self.sample_records[0])
        result = run_ai_matching_case(position, self.data["catalog"], MalformedProvider())

        self.assertIsNone(result["provider_error"])
        self.assertIsNotNone(result["validation_error"])
        self.assertIsNone(result["ai_result"])

    def test_fake_provider_is_default_factory(self) -> None:
        provider = create_provider("fake")

        self.assertIsInstance(provider, FakeAIProvider)

    def test_project_env_loader_reads_dotenv_without_overriding_existing_values(self) -> None:
        old_existing = os.environ.get("TENDER_AI_MODEL")
        old_loaded = os.environ.get("TENDER_AI_TEST_ONLY")
        try:
            os.environ["TENDER_AI_MODEL"] = "already-set"
            os.environ.pop("TENDER_AI_TEST_ONLY", None)
            with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temp_dir:
                temp_root = Path(temp_dir)
                (temp_root / ".env").write_text(
                    "\n".join(
                        [
                            "# local test env",
                            "TENDER_AI_MODEL=from-dotenv",
                            "TENDER_AI_TEST_ONLY='loaded-value'",
                            "INVALID-KEY=ignored",
                        ]
                    ),
                    encoding="utf-8",
                )

                loaded = load_project_env(temp_root)

            self.assertTrue(loaded)
            self.assertEqual(os.environ["TENDER_AI_MODEL"], "already-set")
            self.assertEqual(os.environ["TENDER_AI_TEST_ONLY"], "loaded-value")
            self.assertNotIn("INVALID-KEY", os.environ)
        finally:
            if old_existing is None:
                os.environ.pop("TENDER_AI_MODEL", None)
            else:
                os.environ["TENDER_AI_MODEL"] = old_existing
            if old_loaded is None:
                os.environ.pop("TENDER_AI_TEST_ONLY", None)
            else:
                os.environ["TENDER_AI_TEST_ONLY"] = old_loaded

    def test_real_provider_requires_explicit_enablement(self) -> None:
        provider = OpenAIResponsesProvider(api_key="test-key", enabled=False)
        position = build_position_input(self.sample_records[0])

        with self.assertRaisesRegex(Exception, "disabled"):
            provider.rank_candidates(position, [])

    def test_openai_response_usage_is_reported_without_invented_cost(self) -> None:
        payload = {
            "output_text": (
                '{"ranked_candidates":[],"ambiguity":[],"recommendation":"abstain",'
                '"recommended_product_id":null,"rationale":"no fit"}'
            ),
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

        parsed = _parse_openai_response("PDF080-04", payload)

        self.assertEqual(parsed["usage"]["input_tokens"], 10)
        self.assertEqual(parsed["usage"]["output_tokens"], 5)
        self.assertIsNone(parsed["usage"]["estimated_cost_chf"])
        self.assertEqual(parsed["usage"]["measurement_note"], "token_usage_reported_cost_not_available")

    def test_missing_information_case_can_abstain(self) -> None:
        position = build_position_input(next(row for row in self.sample_records if row["position_id"] == "PDF187-06"))
        result = run_ai_matching_case(position, self.data["catalog"], FakeAIProvider(decision="abstain"))

        self.assertEqual(position["current_status"], "insufficient_information")
        self.assertEqual(result["ai_result"]["safe_decision"], "abstain")
        self.assertFalse(result["ai_result"]["pricing_authorized"])

    def test_evaluation_is_blocked_without_human_labels(self) -> None:
        payload = run_experiment(self.sample_records, self.data["catalog"], FakeAIProvider(decision="review"))

        self.assertEqual(payload["record_count"], 16)
        self.assertEqual(payload["evaluation"]["status"], "blocked_missing_human_labels")
        self.assertEqual(payload["evaluation"]["labelled_count"], 0)

    def test_evaluation_metrics_run_when_human_label_is_present(self) -> None:
        records = [dict(self.sample_records[0])]
        records[0]["human_labels"] = {
            "confirmed_product_id": "P-AIR-003",
            "technical_compatibility": "compatible",
            "priceability": "priceable_with_existing_catalogue",
            "correction_category": "matching_rule",
            "reviewer_notes": "test label",
            "confidence": "high",
        }
        position = build_position_input(records[0])
        result = run_ai_matching_case(
            position,
            self.data["catalog"],
            FakeAIProvider(decision="accept", recommended_product_id="P-AIR-003"),
        )
        evaluation = evaluate_against_human_labels(records, [result])

        self.assertEqual(evaluation["status"], "evaluated")
        self.assertEqual(evaluation["labelled_count"], 1)
        self.assertEqual(evaluation["top1_accuracy"], 1.0)


if __name__ == "__main__":
    unittest.main()
