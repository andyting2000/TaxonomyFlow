import json
import unittest
from pathlib import Path
from unittest.mock import patch

from services import supervisor_production_review as service
from services.supervisor_llm_client import SupervisorLLMConfig, SupervisorLLMInvalidResponseError
from tests.supervisor_review_fakes import (
    FakeSupervisorSession,
    supervisor_template_metadata,
    supervisor_test_playbook,
)


FORBIDDEN_PAYLOAD_TEXT = [
    "auditor_xml",
    "parsed_xml_fact",
    "parsed_xml_facts",
    "xml_facts",
    "gold_answer",
    "expected_qname",
    "target_correct_qname",
    "target_template_field_id",
    "evaluation_label",
    "benchmark_label",
    "strict_accuracy",
    "accuracy_when_predicted",
]


def _valid_live_review():
    return {
        "review_decision": "agree",
        "risk_level": "low",
        "reason": "Live fake Supervisor agrees based on the supplied evidence.",
        "issues": [],
        "recommended_action": "accept",
        "confidence_adjustment": "keep",
        "safe_to_accept": True,
    }


class FakeLiveSupervisorClient:
    def __init__(self, *, response=None, exc=None):
        self.response = response or _valid_live_review()
        self.exc = exc
        self.calls = []

    async def complete_review(self, prompt, *, payload, config=None):
        self.calls.append({"prompt": prompt, "payload": payload, "config": config})
        if self.exc is not None:
            raise self.exc
        return {
            "review": self.response,
            "raw_response_shape": "unit_fake",
            "attempt_count": 1,
            "repair_attempted": False,
            "repair_succeeded": False,
        }


class SupervisorProductionReviewServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.metadata_patch = patch(
            "services.supervisor_production_review.suggestion_template_metadata",
            side_effect=supervisor_template_metadata,
        )
        self.playbook_patch = patch(
            "services.supervisor_mapping_review.load_concept_playbook",
            return_value=supervisor_test_playbook(),
        )
        self.metadata_patch.start()
        self.playbook_patch.start()
        self.addCleanup(self.metadata_patch.stop)
        self.addCleanup(self.playbook_patch.stop)

    def test_live_gate_defaults_are_safe(self):
        config_source = Path("config.py").read_text(encoding="utf-8")

        self.assertIn('"SUPERVISOR_PRODUCTION_LIVE_ENABLED",\n        "false"', config_source)
        self.assertIn('"SUPERVISOR_PRODUCTION_LIVE_ADMIN_ONLY",\n        "true"', config_source)
        self.assertIn('"SUPERVISOR_PRODUCTION_LIVE_MAX_BATCH_SIZE", "10"', config_source)
        self.assertIn('"SUPERVISOR_PRODUCTION_LIVE_DEFAULT_MODE",\n        "mock"', config_source)

    def test_payload_builder_excludes_forbidden_benchmark_and_xml_keys(self):
        session = FakeSupervisorSession()
        payload = service.build_production_supervisor_payload(session.suggestions["suggestion-a"])
        text = json.dumps(payload, sort_keys=True).lower()

        service.assert_production_supervisor_payload_safe(payload)
        self.assertEqual(payload["run_metadata"]["feature"], "17D-C-C")
        self.assertTrue(payload["run_metadata"]["mock_review_only"])
        self.assertFalse(payload["safety"]["external_llm_required"])
        for forbidden in FORBIDDEN_PAYLOAD_TEXT:
            self.assertNotIn(forbidden, text)

    async def test_create_mock_review_for_one_suggestion_without_mapping_mutation(self):
        session = FakeSupervisorSession()

        review, created = await service.run_mock_supervisor_review_for_suggestion(
            session,
            job_id=101,
            suggestion_id="suggestion-a",
            user_id=1,
        )

        self.assertTrue(created)
        self.assertEqual(review.review_status, "completed")
        self.assertEqual(review.source, "mock")
        self.assertEqual(review.supervisor_model_provider, "mock")
        self.assertEqual(review.supervisor_model_id, "mock-supervisor-17d-c-c")
        self.assertEqual(review.supervisor_prompt_version, "supervisor-production-mock-v1")
        self.assertEqual(review.supervisor_schema_version, "mapping-supervisor-review-v1")
        self.assertEqual(len(session.reviews), 1)
        self.assertEqual(session.commits, 1)

        item = session.items["item-a"]
        suggestion = session.suggestions["suggestion-a"]
        self.assertIsNone(item.template_field_id)
        self.assertIsNone(item.confirmed_tag_id)
        self.assertFalse(item.is_reviewed)
        self.assertEqual(suggestion.status, "suggested")

    async def test_list_and_get_reviews(self):
        session = FakeSupervisorSession()
        review, _created = await service.run_mock_supervisor_review_for_suggestion(
            session,
            job_id=101,
            suggestion_id="suggestion-a",
            user_id=1,
        )

        reviews = await service.list_supervisor_reviews_for_job(session, job_id=101)
        found = await service.get_supervisor_review_for_job(
            session,
            job_id=101,
            review_id=review.id,
        )

        self.assertEqual([row.id for row in reviews], [review.id])
        self.assertEqual(found.id, review.id)

    async def test_existing_completed_review_reused_without_force_refresh(self):
        session = FakeSupervisorSession()
        first, first_created = await service.run_mock_supervisor_review_for_suggestion(
            session,
            job_id=101,
            suggestion_id="suggestion-a",
            user_id=1,
        )
        second, second_created = await service.run_mock_supervisor_review_for_suggestion(
            session,
            job_id=101,
            suggestion_id="suggestion-a",
            user_id=1,
        )

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first.id, second.id)
        self.assertEqual(len(session.reviews), 1)
        self.assertEqual(session.commits, 1)

    async def test_force_refresh_creates_new_latest_attempt(self):
        session = FakeSupervisorSession()
        first, _ = await service.run_mock_supervisor_review_for_suggestion(
            session,
            job_id=101,
            suggestion_id="suggestion-a",
            user_id=1,
        )
        second, created = await service.run_mock_supervisor_review_for_suggestion(
            session,
            job_id=101,
            suggestion_id="suggestion-a",
            user_id=1,
            force_refresh=True,
        )

        self.assertTrue(created)
        self.assertNotEqual(first.id, second.id)
        self.assertFalse(first.is_latest)
        self.assertTrue(second.is_latest)
        self.assertEqual(second.review_attempt, 2)
        self.assertEqual(len(session.reviews), 2)

    async def test_batch_review_runs_for_owned_job_suggestions(self):
        session = FakeSupervisorSession()

        result = await service.run_mock_supervisor_reviews_for_job(
            session,
            job_id=101,
            user_id=1,
        )

        self.assertIsNotNone(result)
        reviews, created_count, reused_count = result
        self.assertEqual(len(reviews), 2)
        self.assertEqual(created_count, 2)
        self.assertEqual(reused_count, 0)
        self.assertEqual({review.job_id for review in reviews}, {101})
        self.assertEqual(len(session.reviews), 2)

    async def test_live_review_persists_source_and_model_metadata_without_mapping_mutation(self):
        session = FakeSupervisorSession()
        client = FakeLiveSupervisorClient()
        config = SupervisorLLMConfig(
            enabled=True,
            provider="hf",
            api_token="supervisor-token",
            model_id="supervisor-model",
        )

        review, created = await service.run_supervisor_review_for_suggestion(
            session,
            job_id=101,
            suggestion_id="suggestion-a",
            user_id=1,
            source="live",
            live_client=client,
            live_config=config,
        )

        self.assertTrue(created)
        self.assertEqual(review.review_status, "completed")
        self.assertEqual(review.source, "live")
        self.assertEqual(review.supervisor_model_provider, "hf")
        self.assertEqual(review.supervisor_model_id, "supervisor-model")
        self.assertEqual(review.supervisor_prompt_version, "supervisor-production-live-v1")
        self.assertTrue(review.supervisor_safe_to_accept)
        self.assertEqual(len(client.calls), 1)
        self.assertIn("SUPERVISOR_REVIEW_INPUT_JSON", client.calls[0]["prompt"])
        payload_text = json.dumps(client.calls[0]["payload"], sort_keys=True).lower()
        prompt_text = client.calls[0]["prompt"].lower()
        for forbidden in FORBIDDEN_PAYLOAD_TEXT:
            self.assertNotIn(forbidden, payload_text)
            self.assertNotIn(forbidden, prompt_text)

        item = session.items["item-a"]
        suggestion = session.suggestions["suggestion-a"]
        self.assertIsNone(item.template_field_id)
        self.assertIsNone(item.confirmed_tag_id)
        self.assertFalse(item.is_reviewed)
        self.assertEqual(suggestion.status, "suggested")

    async def test_live_safe_accept_guardrail_reason_is_persisted_as_visible_issue(self):
        session = FakeSupervisorSession()
        session.suggestions["suggestion-a"].confidence = 0.89
        client = FakeLiveSupervisorClient()
        config = SupervisorLLMConfig(
            enabled=True,
            provider="hf",
            api_token="supervisor-token",
            model_id="supervisor-model",
        )

        review, created = await service.run_supervisor_review_for_suggestion(
            session,
            job_id=101,
            suggestion_id="suggestion-a",
            user_id=1,
            source="live",
            live_client=client,
            live_config=config,
        )

        self.assertTrue(created)
        self.assertEqual(review.supervisor_decision, "agree")
        self.assertEqual(review.supervisor_risk_level, "low")
        self.assertEqual(review.supervisor_recommended_action, "accept")
        self.assertFalse(review.supervisor_safe_to_accept)
        self.assertFalse(review.calibrated_safe_to_accept)
        issues = json.loads(review.supervisor_issues_json)
        self.assertEqual(issues[0]["type"], "other")
        self.assertIn("Safe flag withheld by guardrail", issues[0]["description"])
        self.assertIn("mapper confidence was below the safe-accept threshold", issues[0]["description"])
        serialized = service.serialize_supervisor_review(review)
        self.assertEqual(serialized["supervisor_issues"][0]["type"], "other")
        self.assertIn("Safe flag withheld by guardrail", serialized["supervisor_issues"][0]["description"])

    async def test_mock_and_live_reviews_have_separate_latest_attempts(self):
        session = FakeSupervisorSession()
        client = FakeLiveSupervisorClient()
        config = SupervisorLLMConfig(
            enabled=True,
            provider="hf",
            api_token="supervisor-token",
            model_id="supervisor-model",
        )

        mock_review, _ = await service.run_supervisor_review_for_suggestion(
            session,
            job_id=101,
            suggestion_id="suggestion-a",
            user_id=1,
            source="mock",
        )
        live_review, created = await service.run_supervisor_review_for_suggestion(
            session,
            job_id=101,
            suggestion_id="suggestion-a",
            user_id=1,
            source="live",
            live_client=client,
            live_config=config,
        )
        live_reused, reused_created = await service.run_supervisor_review_for_suggestion(
            session,
            job_id=101,
            suggestion_id="suggestion-a",
            user_id=1,
            source="live",
            live_client=client,
            live_config=config,
        )

        self.assertTrue(created)
        self.assertFalse(reused_created)
        self.assertEqual(live_review.id, live_reused.id)
        self.assertTrue(mock_review.is_latest)
        self.assertTrue(live_review.is_latest)
        self.assertEqual(len(session.reviews), 2)
        self.assertEqual(len(client.calls), 1)

    async def test_live_provider_failure_persists_failed_review_without_mock_fallback(self):
        session = FakeSupervisorSession()
        client = FakeLiveSupervisorClient(exc=RuntimeError("provider failed for secret-supervisor-token"))
        config = SupervisorLLMConfig(
            enabled=True,
            provider="hf",
            api_token="secret-supervisor-token",
            model_id="supervisor-model",
        )

        review, created = await service.run_supervisor_review_for_suggestion(
            session,
            job_id=101,
            suggestion_id="suggestion-a",
            user_id=1,
            source="live",
            live_client=client,
            live_config=config,
        )

        self.assertTrue(created)
        self.assertEqual(review.review_status, "failed")
        self.assertEqual(review.source, "live")
        self.assertFalse(review.supervisor_safe_to_accept)
        self.assertFalse(review.calibrated_safe_to_accept)
        self.assertEqual(review.error_type, "RuntimeError")
        self.assertIn("[REDACTED_SUPERVISOR_TOKEN]", review.error_message_sanitized)
        self.assertNotIn("secret-supervisor-token", review.error_message_sanitized)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(review.supervisor_model_provider, "hf")
        self.assertEqual(review.supervisor_model_id, "supervisor-model")

    async def test_live_invalid_response_is_persisted_failed_and_not_safe_to_accept(self):
        session = FakeSupervisorSession()
        invalid = SupervisorLLMInvalidResponseError(
            "invalid_json",
            "Supervisor LLM response was not a valid JSON object.",
            raw_text="not json",
            raw_response_shape="chat_completion_message_content",
        )
        client = FakeLiveSupervisorClient(exc=invalid)
        config = SupervisorLLMConfig(
            enabled=True,
            provider="hf",
            api_token="supervisor-token",
            model_id="supervisor-model",
        )

        review, created = await service.run_supervisor_review_for_suggestion(
            session,
            job_id=101,
            suggestion_id="suggestion-a",
            user_id=1,
            source="live",
            live_client=client,
            live_config=config,
        )

        self.assertTrue(created)
        self.assertEqual(review.review_status, "failed")
        self.assertEqual(review.error_type, "invalid_supervisor_response")
        self.assertFalse(review.supervisor_safe_to_accept)
        self.assertFalse(review.calibrated_safe_to_accept)

    async def test_live_batch_enforces_max_batch_size_before_provider_call(self):
        session = FakeSupervisorSession()
        client = FakeLiveSupervisorClient()
        config = SupervisorLLMConfig(
            enabled=True,
            provider="hf",
            api_token="supervisor-token",
            model_id="supervisor-model",
        )

        with self.assertRaises(service.SupervisorLiveBatchSizeExceeded) as ctx:
            await service.run_supervisor_reviews_for_job(
                session,
                job_id=101,
                user_id=1,
                source="live",
                live_client=client,
                live_config=config,
                max_batch_size=1,
            )

        self.assertEqual(ctx.exception.count, 2)
        self.assertEqual(ctx.exception.max_batch_size, 1)
        self.assertEqual(len(client.calls), 0)
        self.assertEqual(session.reviews, [])

    async def test_owned_job_check_hides_other_users_job(self):
        session = FakeSupervisorSession()

        review, created = await service.run_mock_supervisor_review_for_suggestion(
            session,
            job_id=202,
            suggestion_id="suggestion-b",
            user_id=1,
        )
        batch_result = await service.run_mock_supervisor_reviews_for_job(
            session,
            job_id=202,
            user_id=1,
        )

        self.assertIsNone(review)
        self.assertFalse(created)
        self.assertIsNone(batch_result)
        self.assertEqual(session.reviews, [])

    def test_service_does_not_import_qwen_mapper_client_or_mapper_config(self):
        source = Path(service.__file__).read_text(encoding="utf-8")

        self.assertNotIn("HuggingFaceQwenMappingClient", source)
        self.assertNotIn("model_api_token", source)
        self.assertNotIn("llm_mapping_model_id", source)


if __name__ == "__main__":
    unittest.main()
