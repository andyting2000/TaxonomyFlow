import asyncio
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from scripts.evaluate_supervisor_live_17d import PREFLIGHT_PROMPT, _mapping_score, _summary, build_reports, run_preflight
from services.supervisor_llm_client import (
    MISSING_CONFIG_MESSAGE,
    SupervisorLLMClient,
    SupervisorLLMConfig,
    SupervisorLLMConfigurationError,
    SupervisorLLMInvalidResponseError,
    SupervisorProviderHTTPError,
    SupervisorLLMRateLimitError,
    _post_chat_completion,
    _response_format_payload,
    build_supervisor_repair_prompt,
    parse_supervisor_llm_response,
    provider_error_guidance,
    supervisor_independence_status,
)


def _payload():
    return {
        "mapper_suggestion": {
            "selected_template_field_id": "ifrs-smes:CashAndCashEquivalents",
            "selected_concept_qname": "ifrs-smes:CashAndCashEquivalents",
        },
        "candidate_concepts": [
            {
                "template_field_id": "ifrs-smes:CashAndCashEquivalents",
                "concept_qname": "ifrs-smes:CashAndCashEquivalents",
                "label": "Cash and cash equivalents",
            }
        ],
    }


def _valid_review():
    return {
        "review_decision": "agree",
        "risk_level": "low",
        "reason": "The mapper selection is supported by the provided evidence.",
        "issues": [],
        "recommended_action": "accept",
        "confidence_adjustment": "keep",
        "safe_to_accept": True,
    }


class FakeSettings:
    model_api_token = "mapper-token"
    hugging_face_token = "mapper-token"
    llm_mapping_model_id = "mapper-model"
    ai_text_model_id = "text-model"


class Fake429(Exception):
    status_code = 429
    headers = {"Retry-After": "0"}


class FakeHTTP400(urllib.error.HTTPError):
    def __init__(self, body):
        super().__init__(
            "https://router.huggingface.co/v1/chat/completions",
            400,
            "Bad Request",
            {},
            io.BytesIO(body.encode("utf-8")),
        )


class SupervisorLLMClientTests(unittest.TestCase):
    def test_missing_supervisor_config_blocks_live_run(self):
        config = SupervisorLLMConfig(enabled=False, api_token="", model_id="")

        with self.assertRaises(SupervisorLLMConfigurationError) as ctx:
            config.require_live_config()

        self.assertEqual(str(ctx.exception), MISSING_CONFIG_MESSAGE)

    def test_no_silent_fallback_to_mapper_model_or_token(self):
        config = SupervisorLLMConfig(enabled=True, api_token="", model_id="")

        with self.assertRaises(SupervisorLLMConfigurationError):
            config.require_live_config()

    def test_independence_status_reports_limited_when_token_or_model_matches_mapper(self):
        same_token = SupervisorLLMConfig(enabled=True, api_token="mapper-token", model_id="supervisor-model")
        same_model = SupervisorLLMConfig(enabled=True, api_token="supervisor-token", model_id="mapper-model")
        independent = SupervisorLLMConfig(enabled=True, api_token="supervisor-token", model_id="supervisor-model")

        self.assertEqual(
            supervisor_independence_status(same_token, settings_obj=FakeSettings),
            "limited_same_model_or_token",
        )
        self.assertEqual(
            supervisor_independence_status(same_model, settings_obj=FakeSettings),
            "limited_same_model_or_token",
        )
        self.assertEqual(
            supervisor_independence_status(independent, settings_obj=FakeSettings),
            "independent_model_or_token",
        )

    def test_openai_style_response_envelope_is_parsed(self):
        raw = {"choices": [{"message": {"content": json.dumps(_valid_review())}}]}

        parsed = parse_supervisor_llm_response(raw, payload=_payload())

        self.assertEqual(parsed["review"]["review_decision"], "agree")
        self.assertEqual(parsed["raw_response_shape"], "chat_completion_message_content")

    def test_markdown_fenced_json_is_parsed(self):
        raw = {"choices": [{"message": {"content": "```json\n" + json.dumps(_valid_review()) + "\n```"}}]}

        parsed = parse_supervisor_llm_response(raw, payload=_payload())

        self.assertEqual(parsed["review"]["recommended_action"], "accept")
        self.assertEqual(parsed["raw_response_shape"], "markdown_json")

    def test_leading_and_trailing_explanation_json_object_is_parsed(self):
        raw = {"choices": [{"message": {"content": "Here is the review:\n" + json.dumps(_valid_review()) + "\nDone."}}]}

        parsed = parse_supervisor_llm_response(raw, payload=_payload())

        self.assertEqual(parsed["review"]["review_decision"], "agree")

    def test_nested_json_string_content_is_parsed(self):
        raw = {"choices": [{"message": {"content": json.dumps(json.dumps(_valid_review()))}}]}

        parsed = parse_supervisor_llm_response(raw, payload=_payload())

        self.assertEqual(parsed["review"]["risk_level"], "low")

    def test_array_root_is_rejected(self):
        with self.assertRaises(SupervisorLLMInvalidResponseError) as ctx:
            parse_supervisor_llm_response({"choices": [{"message": {"content": json.dumps([_valid_review()])}}]}, payload=_payload())

        self.assertEqual(ctx.exception.category, "non_object_json_root")

    def test_invalid_json_is_rejected(self):
        with self.assertRaises(SupervisorLLMInvalidResponseError):
            parse_supervisor_llm_response({"choices": [{"message": {"content": "not json"}}]}, payload=_payload())

    def test_replacement_outside_candidates_is_rejected_by_client_validator(self):
        invalid = {
            **_valid_review(),
            "safe_to_accept": False,
            "replacement_concept_qname": "ifrs-smes:InventedConcept",
        }

        with self.assertRaises(SupervisorLLMInvalidResponseError) as ctx:
            parse_supervisor_llm_response({"choices": [{"message": {"content": json.dumps(invalid)}}]}, payload=_payload())

        self.assertEqual(ctx.exception.category, "schema_validation_error")

    def test_repair_prompt_excludes_full_project_payload_gold_and_xml(self):
        error = SupervisorLLMInvalidResponseError(
            "invalid_json",
            "bad json",
            raw_text='{"review_decision":"agree" TOKEN hf_abcdefghijklmnopqrstuvwxyz}',
            raw_response_shape="chat_completion_message_content",
            config=SupervisorLLMConfig(enabled=True, api_token="TOKEN", model_id="supervisor-model"),
        )

        prompt = build_supervisor_repair_prompt(error)

        self.assertIn("Repair this into valid JSON only", prompt)
        self.assertIn("[REDACTED_SUPERVISOR_TOKEN]", prompt)
        for forbidden in ["auditor_xml", "parsed_xml_fact", "target_gold_answer", "correct_concept_qname", "SUPERVISOR_REVIEW_INPUT_JSON"]:
            self.assertNotIn(forbidden, prompt)

    def test_provider_429_triggers_bounded_retry(self):
        attempts = {"count": 0}
        sleeps = []

        async def transport(_prompt, _config):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise Fake429("rate limited")
            return {"choices": [{"message": {"content": json.dumps(_valid_review())}}]}

        async def sleeper(delay):
            sleeps.append(delay)

        client = SupervisorLLMClient(transport=transport, sleeper=sleeper)
        config = SupervisorLLMConfig(
            enabled=True,
            api_token="supervisor-token",
            model_id="supervisor-model",
            max_retries=1,
            retry_base_seconds=0,
        )

        parsed = asyncio.run(client.complete_review("prompt", payload=_payload(), config=config))

        self.assertEqual(parsed["review"]["review_decision"], "agree")
        self.assertEqual(attempts["count"], 2)
        self.assertEqual(sleeps, [0.0])

    def test_rate_limit_after_retries_raises_typed_error(self):
        async def transport(_prompt, _config):
            raise Fake429("rate limited")

        client = SupervisorLLMClient(transport=transport, sleeper=self._done)
        config = SupervisorLLMConfig(
            enabled=True,
            api_token="supervisor-token",
            model_id="supervisor-model",
            max_retries=0,
        )

        with self.assertRaises(SupervisorLLMRateLimitError):
            asyncio.run(client.complete_review("prompt", payload=_payload(), config=config))

    async def _done(self, _delay):
        return None

    def test_invalid_response_repair_success_is_counted(self):
        attempts = {"count": 0}

        async def transport(prompt, _config):
            attempts["count"] += 1
            if attempts["count"] == 1:
                return {"choices": [{"message": {"content": "not json"}}]}
            self.assertIn("Repair this into valid JSON only", prompt)
            return {"choices": [{"message": {"content": json.dumps(_valid_review())}}]}

        client = SupervisorLLMClient(transport=transport)
        config = SupervisorLLMConfig(enabled=True, api_token="supervisor-token", model_id="supervisor-model")

        parsed = asyncio.run(client.complete_review("prompt", payload=_payload(), config=config))

        self.assertTrue(parsed["repair_attempted"])
        self.assertTrue(parsed["repair_succeeded"])
        self.assertEqual(parsed["review"]["review_decision"], "agree")
        self.assertEqual(attempts["count"], 2)

    def test_invalid_response_repair_failure_raises_typed_unrepaired_error(self):
        async def transport(_prompt, _config):
            return {"choices": [{"message": {"content": "not json"}}]}

        client = SupervisorLLMClient(transport=transport)
        config = SupervisorLLMConfig(enabled=True, api_token="supervisor-token", model_id="supervisor-model")

        with self.assertRaises(SupervisorLLMInvalidResponseError) as ctx:
            asyncio.run(client.complete_review("prompt", payload=_payload(), config=config))

        self.assertTrue(ctx.exception.repair_attempted)
        self.assertFalse(ctx.exception.repair_succeeded)

    def test_response_format_config_supports_json_schema_json_object_and_none(self):
        self.assertEqual(_response_format_payload("json_schema")["type"], "json_schema")
        self.assertEqual(_response_format_payload("json_object"), {"type": "json_object"})
        self.assertIsNone(_response_format_payload("none"))

    def test_http_error_400_body_is_captured_and_token_redacted(self):
        config = SupervisorLLMConfig(
            enabled=True,
            api_token="secret-supervisor-token",
            model_id="mistralai/Mistral-Medium-3.5-128B",
            response_format="json_schema",
        )
        body = "Bad request for secret-supervisor-token: unsupported response_format json_schema"

        with patch("urllib.request.urlopen", side_effect=FakeHTTP400(body)):
            with self.assertRaises(SupervisorProviderHTTPError) as ctx:
                _post_chat_completion("prompt", config)

        error = ctx.exception
        self.assertEqual(error.status_code, 400)
        self.assertIn("[REDACTED_SUPERVISOR_TOKEN]", error.sanitized_error_body)
        self.assertNotIn("secret-supervisor-token", error.sanitized_error_body)
        self.assertEqual(error.response_format_mode, "json_schema")
        self.assertTrue(error.json_schema_sent)

    def test_unsupported_response_format_and_model_guidance_are_generated(self):
        response_guidance = provider_error_guidance("unsupported response_format json_schema")
        model_guidance = provider_error_guidance("model not found or provider not supported")

        self.assertIn("Try SUPERVISOR_LLM_RESPONSE_FORMAT=json_object or none.", response_guidance)
        self.assertTrue(any("HF router suffix" in item for item in model_guidance))

    def test_preflight_sends_no_project_row_gold_or_evaluation_data(self):
        seen = {}

        async def transport(prompt, _config):
            seen["prompt"] = prompt
            return {"choices": [{"message": {"content": json.dumps(_valid_review())}}]}

        client = SupervisorLLMClient(transport=transport)
        config = SupervisorLLMConfig(
            enabled=True,
            api_token="supervisor-token",
            model_id="supervisor-model",
        )

        result = asyncio.run(run_preflight(client=client, config=config))

        self.assertEqual(result["status"], "completed")
        self.assertEqual(seen["prompt"], PREFLIGHT_PROMPT)
        forbidden = ["case_005", "correct_concept_qname", "evaluation_label", "auditor_xml", "parsed_xml_fact"]
        for marker in forbidden:
            self.assertNotIn(marker, seen["prompt"])

    def test_bad_request_produces_structured_partial_reports(self):
        async def transport(_prompt, _config):
            raise SupervisorProviderHTTPError(
                "bad request",
                status_code=400,
                reason="Bad Request",
                sanitized_error_body="unsupported response_format json_schema",
                model_id="supervisor-model",
                base_url="https://router.huggingface.co/v1",
                response_format_mode="json_schema",
                json_schema_sent=True,
            )

        config = SupervisorLLMConfig(
            enabled=True,
            api_token="supervisor-token",
            model_id="supervisor-model",
            response_format="json_schema",
        )
        client = SupervisorLLMClient(transport=transport)
        with tempfile.TemporaryDirectory() as tmp:
            with patch("scripts.evaluate_supervisor_live_17d.SupervisorLLMConfig.from_settings", return_value=config):
                paths = asyncio.run(
                    build_reports(
                        golden_dir="benchmark_mbrs_pairs",
                        reports_dir=tmp,
                        use_live_llm=True,
                        client=client,
                        limit=1,
                    )
                )
            report = json.loads(Path(paths["review_json"]).read_text(encoding="utf-8"))
            error_report = json.loads(Path(paths["error_analysis_json"]).read_text(encoding="utf-8"))

        self.assertTrue(report["run_metadata"]["partial"])
        self.assertEqual(report["run_metadata"]["live_status"], "blocked_provider_bad_request")
        self.assertEqual(report["run_metadata"]["provider_error_summary"]["status_code"], 400)
        self.assertEqual(error_report["provider_error_result"]["status_code"], 400)

    def test_repaired_response_is_counted_in_reports(self):
        attempts = {"count": 0}

        async def transport(_prompt, _config):
            attempts["count"] += 1
            if attempts["count"] == 1:
                return {"choices": [{"message": {"content": "not json with secret-supervisor-token"}}]}
            return {"choices": [{"message": {"content": json.dumps(_valid_review())}}]}

        config = SupervisorLLMConfig(
            enabled=True,
            api_token="secret-supervisor-token",
            model_id="supervisor-model",
            repair_enabled=True,
            max_repair_retries=1,
        )
        client = SupervisorLLMClient(transport=transport)
        with tempfile.TemporaryDirectory() as tmp:
            with patch("scripts.evaluate_supervisor_live_17d.SupervisorLLMConfig.from_settings", return_value=config):
                paths = asyncio.run(
                    build_reports(
                        golden_dir="benchmark_mbrs_pairs",
                        reports_dir=tmp,
                        use_live_llm=True,
                        client=client,
                        limit=1,
                    )
                )
            report = json.loads(Path(paths["review_json"]).read_text(encoding="utf-8"))
            error_report = json.loads(Path(paths["error_analysis_json"]).read_text(encoding="utf-8"))

        self.assertEqual(report["summary"]["invalid_response_count"], 1)
        self.assertEqual(report["summary"]["repaired_response_count"], 1)
        self.assertEqual(report["summary"]["unrepaired_invalid_response_count"], 0)
        self.assertEqual(error_report["invalid_response_diagnostics"][0]["repair_succeeded"], True)
        self.assertNotIn("secret-supervisor-token", json.dumps(error_report))

    def test_unrepaired_invalid_response_becomes_high_risk_human_review(self):
        async def transport(_prompt, _config):
            return {"choices": [{"message": {"content": "not json"}}]}

        config = SupervisorLLMConfig(
            enabled=True,
            api_token="supervisor-token",
            model_id="supervisor-model",
            repair_enabled=True,
            max_repair_retries=1,
        )
        client = SupervisorLLMClient(transport=transport)
        with tempfile.TemporaryDirectory() as tmp:
            with patch("scripts.evaluate_supervisor_live_17d.SupervisorLLMConfig.from_settings", return_value=config):
                paths = asyncio.run(
                    build_reports(
                        golden_dir="benchmark_mbrs_pairs",
                        reports_dir=tmp,
                        use_live_llm=True,
                        client=client,
                        limit=1,
                    )
                )
            report = json.loads(Path(paths["review_json"]).read_text(encoding="utf-8"))

        review = report["review_records"][0]["supervisor_review"]
        self.assertEqual(review["review_decision"], "needs_human_review")
        self.assertEqual(review["risk_level"], "high")
        self.assertFalse(review["safe_to_accept"])
        self.assertEqual(report["summary"]["invalid_response_count"], 1)
        self.assertEqual(report["summary"]["repaired_response_count"], 0)
        self.assertEqual(report["summary"]["unrepaired_invalid_response_count"], 1)
        self.assertEqual(review["issues"][0]["type"], "unrepaired_invalid_supervisor_response")

    def test_scoring_counts_false_agree_false_safe_accept_and_blocked_correct_consistently(self):
        wrong_row = {
            "correct_template_field_id": "ifrs-smes:Revenue",
            "correct_concept_qname": "ifrs-smes:Revenue",
        }
        wrong_mapper = {
            "predicted_template_field_id": "ifrs-smes:CurrentAssets",
            "predicted_concept_qname": "ifrs-smes:CurrentAssets",
        }
        correct_row = {
            "correct_template_field_id": "ifrs-smes:Revenue",
            "correct_concept_qname": "ifrs-smes:Revenue",
        }
        correct_mapper = {
            "predicted_template_field_id": "ifrs-smes:Revenue",
            "predicted_concept_qname": "ifrs-smes:Revenue",
        }
        agree_safe = {**_valid_review(), "review_decision": "agree", "safe_to_accept": True}
        agree_not_safe = {**_valid_review(), "review_decision": "agree", "safe_to_accept": False}
        records = [
            {
                "supervisor_review": agree_safe,
                "local_scoring": _mapping_score(wrong_row, wrong_mapper, agree_safe),
            },
            {
                "supervisor_review": agree_not_safe,
                "local_scoring": _mapping_score(wrong_row, wrong_mapper, agree_not_safe),
            },
            {
                "supervisor_review": agree_not_safe,
                "local_scoring": _mapping_score(correct_row, correct_mapper, agree_not_safe),
            },
        ]

        summary = _summary(records)

        self.assertEqual(summary["false_agree_count"], 2)
        self.assertEqual(summary["false_safe_accept_count"], 1)
        self.assertEqual(summary["wrong_mapper_mappings_caught"], 1)
        self.assertEqual(summary["wrong_mapper_mappings_missed"], 1)
        self.assertEqual(summary["correct_mappings_unnecessarily_blocked"], 1)
        self.assertEqual(summary["blocked_correct_mapping_count"], 1)

    def test_partial_result_report_is_saved_on_rate_limit(self):
        async def sleeper(_delay):
            return None

        async def transport(_prompt, _config):
            raise Fake429("rate limited")

        config = SupervisorLLMConfig(
            enabled=True,
            api_token="supervisor-token",
            model_id="supervisor-model",
            max_retries=0,
        )
        client = SupervisorLLMClient(transport=transport, sleeper=sleeper)
        with tempfile.TemporaryDirectory() as tmp:
            with patch("scripts.evaluate_supervisor_live_17d.SupervisorLLMConfig.from_settings", return_value=config):
                paths = asyncio.run(
                    build_reports(
                        golden_dir="benchmark_mbrs_pairs",
                        reports_dir=tmp,
                        use_live_llm=True,
                        client=client,
                        limit=1,
                    )
                )
            report = json.loads(Path(paths["review_json"]).read_text(encoding="utf-8"))

        self.assertTrue(report["run_metadata"]["partial"])
        self.assertEqual(report["summary"]["total_reviewed"], 0)
        self.assertEqual(report["run_metadata"]["rate_limit_summary"]["failed_row_id"], "case_005:candidate:14:14")


if __name__ == "__main__":
    unittest.main()
