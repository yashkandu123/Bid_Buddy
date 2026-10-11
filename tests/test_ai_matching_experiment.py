from __future__ import annotations

import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

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
    run_page_batched_experiment,
    run_experiment,
    validate_page_ai_ranker_output,
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
        self.assertEqual(
            {row["product_id"] for row in prompt_case["catalogue_candidates"]},
            {"P-AIR-001", "P-AIR-002", "P-AIR-003"},
        )
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

    def test_supplier_package_accept_is_downgraded_to_review(self) -> None:
        record = {
            "lv_id": "SUPPLIER-1",
            "source_page": 1,
            "source_language": "de",
            "original_description": "Schalldämpfer 400x300x1250 mm Stk 1",
            "source_line": "400x300x1250 mm Stk 1",
            "quantity": 1,
            "unit": "pc",
            "technical_attributes": {
                "dimensions": [{"values_mm": [400, 300, 1250]}],
            },
            "status": "review_required",
        }
        result = run_ai_matching_case(
            build_position_input(record),
            self.data["catalog"],
            FakeAIProvider(decision="accept", recommended_product_id="P-SIL-001"),
        )

        self.assertEqual(result["ai_result"]["safe_decision"], "review")
        self.assertFalse(result["ai_result"]["pricing_authorized"])
        self.assertIn(
            "supplier_quote_required",
            {flag["code"] for flag in result["ai_result"]["validation_flags"]},
        )

    def test_local_smoke_detector_cannot_inherit_actuator_candidate(self) -> None:
        position = build_position_input({
            "lv_id": "CONTROL-CONTEXT-1",
            "source_page": 1,
            "source_language": "de",
            "original_description": "Drehantrieb AC/DC 24 V Stk 2 Kanalrauchmelder Stk 1",
            "source_line": "Kanalrauchmelder Stk 1",
            "quantity": 1,
            "unit": "pc",
            "technical_attributes": {},
            "status": "review_required",
        })
        candidate = next(
            row for row in self.data["catalog"] if row["product_id"] == "P-CTL-003"
        )
        bounded_candidate = {
            key: candidate[key]
            for key in (
                "product_id", "category", "subcategory", "manufacturer", "model",
                "description", "unit", "install_code", "source_type",
                "supplier_quote_required",
            )
        }
        bounded_candidate["supplier_quote_required"] = False
        result = validate_ai_ranker_output(
            {
                "lv_id": "CONTROL-CONTEXT-1",
                "ranked_candidates": [{"product_id": "P-CTL-003"}],
                "ambiguity": [],
                "recommendation": "accept",
                "recommended_product_id": "P-CTL-003",
                "rationale": "bad inherited-context match",
            },
            {"P-CTL-003"},
            position,
            [bounded_candidate],
        )

        self.assertEqual(result["safe_decision"], "review")
        self.assertIn(
            "component_type_mismatch",
            {flag["code"] for flag in result["validation_flags"]},
        )

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

    def test_review_ranking_is_scored_without_treating_it_as_price_authority(self) -> None:
        records = [dict(self.sample_records[0])]
        records[0]["human_labels"] = {
            "confirmed_product_id": "P-AIR-003",
            "technical_compatibility": "conflict_requires_review",
            "priceability": "uncertain",
            "confidence": "high",
        }
        result = run_ai_matching_case(
            build_position_input(records[0]),
            self.data["catalog"],
            FakeAIProvider(decision="review"),
        )

        evaluation = evaluate_against_human_labels(records, [result])

        self.assertEqual(evaluation["top1_accuracy"], 1.0)
        self.assertEqual(evaluation["safe_calculation_candidate_count"], 0)

    def test_page_batch_preserves_source_association_and_never_authorizes_pricing(self) -> None:
        records = [dict(self.sample_records[0]), dict(self.sample_records[1])]
        records[1]["source"] = dict(records[1].get("source", {}), source_page=79)
        records[1]["machine_values"] = dict(records[1].get("machine_values", {}), source_page=79)

        payload = run_page_batched_experiment(
            records,
            self.data["catalog"],
            FakeAIProvider(decision="review"),
            max_candidates=3,
        )

        self.assertEqual(payload["page_batch_count"], 1)
        self.assertEqual(len(payload["batch_metrics"]), 1)
        self.assertEqual(payload["batch_metrics"][0]["position_count"], 2)
        self.assertEqual(payload["record_count"], 2)
        self.assertTrue(all(row["page_batch_size"] == 2 for row in payload["results"]))
        self.assertTrue(all(row["evaluation_ready"] for row in payload["results"]))
        self.assertTrue(all(not row["ai_result"]["pricing_authorized"] for row in payload["results"]))

    def test_page_validation_rejects_wrong_source_line_quantity_and_unit(self) -> None:
        position = build_position_input(self.sample_records[0])
        candidates = retrieve_catalogue_candidates(position, self.data["catalog"], max_candidates=3)
        base = FakeAIProvider(decision="review").rank_page(
            [{"position": position, "candidates": candidates}]
        )[0]
        for field, wrong, message in (
            ("source_line", "another row", "source line"),
            ("quantity", float(position["quantity"]) + 1, "quantity"),
            ("unit", "m", "unit"),
        ):
            with self.subTest(field=field):
                with self.assertRaisesRegex(AIMatchingValidationError, message):
                    validate_page_ai_ranker_output({**base, field: wrong}, position, candidates)

    def test_rule_llm_product_conflict_is_review_only(self) -> None:
        position = build_position_input(self.sample_records[0])
        candidates = retrieve_catalogue_candidates(position, self.data["catalog"], max_candidates=3)
        conflicting_id = next(
            candidate["product_id"]
            for candidate in candidates
            if candidate["product_id"] != position["deterministic_match"]["matched_product_id"]
        )
        output = FakeAIProvider(
            decision="accept", recommended_product_id=conflicting_id
        ).rank_page([{"position": position, "candidates": candidates}])[0]

        validated = validate_page_ai_ranker_output(output, position, candidates)

        self.assertEqual(validated["safe_decision"], "review")
        self.assertFalse(validated["pricing_authorized"])
        self.assertIn(
            "rule_llm_product_conflict",
            {flag["code"] for flag in validated["validation_flags"]},
        )

    def test_real_page_provider_caches_only_successful_structured_response(self) -> None:
        position = build_position_input(self.sample_records[0])
        candidates = retrieve_catalogue_candidates(position, self.data["catalog"], max_candidates=3)
        selected = candidates[0]["product_id"]
        body = {
            "positions": [
                {
                    "position_id": position["position_id"],
                    "source_page": position["source_page"],
                    "source_line": position["source_line"],
                    "quantity": position["quantity"],
                    "unit": position["unit"],
                    "ranked_candidates": [
                        {
                            "product_id": selected,
                            "confidence": 0.7,
                            "evidence": ["bounded test candidate"],
                            "technical_mismatches": [],
                            "missing_evidence": [],
                        }
                    ],
                    "ambiguity": [],
                    "recommendation": "review",
                    "recommended_product_id": None,
                    "rationale": "test",
                }
            ]
        }
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "output_text": json.dumps(body),
            "usage": {"input_tokens": 20, "output_tokens": 10},
        }
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temp_dir:
            provider = OpenAIResponsesProvider(
                api_key="test-key",
                enabled=True,
                cache_dir=Path(temp_dir),
            )
            with patch("httpx.post", return_value=response) as post:
                first = provider.rank_page([{"position": position, "candidates": candidates}])
                second = provider.rank_page([{"position": position, "candidates": candidates}])

        self.assertEqual(first, second)
        self.assertEqual(post.call_count, 1)
        self.assertTrue(provider.last_cache_hit)

    def test_page_batch_provider_failure_preserves_deterministic_fallback(self) -> None:
        payload = run_page_batched_experiment(
            [self.sample_records[0]],
            self.data["catalog"],
            FakeAIProvider(fail=True),
            max_candidates=3,
        )

        result = payload["results"][0]
        expected = build_position_input(self.sample_records[0])["deterministic_match"]
        self.assertIsNotNone(result["provider_error"])
        self.assertIsNone(result["ai_result"])
        self.assertEqual(result["deterministic_fallback"], expected)

    def test_missing_required_candidate_diameter_downgrades_accept(self) -> None:
        position = {
            "position_id": "REQUIRED-DN-1",
            "source_page": 1,
            "source_language": "de",
            "original_german_description": "Bauteil DN100",
            "source_line": "Bauteil DN100 Stk 1",
            "quantity": 1.0,
            "unit": "pc",
            "technical_attributes": {"diameters": [{"value_mm": 100.0}]},
            "current_status": "review_required",
            "deterministic_match": {"matched_product_id": None, "conflict_flags": []},
        }
        catalog_row = next(row for row in self.data["catalog"] if row["product_id"] == "P-CTL-003")
        candidate = {
            key: catalog_row[key]
            for key in (
                "product_id", "category", "subcategory", "manufacturer", "model",
                "description", "unit", "install_code", "source_type",
            )
        }
        candidate["supplier_quote_required"] = False
        output = FakeAIProvider(
            decision="accept", recommended_product_id=candidate["product_id"]
        ).rank_page([{"position": position, "candidates": [candidate]}])[0]

        validated = validate_page_ai_ranker_output(output, position, [candidate])

        self.assertEqual(validated["safe_decision"], "review")
        self.assertIn(
            "diameter_not_confirmed",
            {flag["code"] for flag in validated["validation_flags"]},
        )
        self.assertFalse(validated["pricing_authorized"])


if __name__ == "__main__":
    unittest.main()
