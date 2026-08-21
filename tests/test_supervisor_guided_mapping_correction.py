import inspect
import json
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from database import MappingSupervisorReview, SupervisorGuidedMappingRevision
from services.llm_taxonomy_mapping import LLMMappingConfig
from services.supervisor_guided_mapping_correction import (
    SupervisorGuidedCorrectionConfig,
    SupervisorGuidedCorrectionDisabled,
    SupervisorGuidedCorrectionNotEligible,
    SupervisorGuidedCorrectionRetryLimit,
    run_supervisor_guided_mapping_correction,
)
from services.supervisor_mapper_feedback import (
    FORBIDDEN_FEEDBACK_KEYS,
    assert_supervisor_mapper_feedback_safe,
    build_supervisor_guided_mapping_prompt,
    build_supervisor_mapper_feedback_payload,
    supervisor_feedback_eligibility,
)
from tests.supervisor_review_fakes import (
    FakeSupervisorSession,
    supervisor_template_metadata,
    supervisor_test_playbook,
)
from tests.test_supervisor_review_api import build_supervisor_review_app


def make_review(
    *,
    review_id="review-correction",
    suggestion_id="suggestion-a",
    decision="disagree",
    action="request_better_candidate",
    issues=None,
    status="completed",
    error_type=None,
):
    now = datetime(2026, 7, 21, 12, 0, 0)
    return MappingSupervisorReview(
        id=review_id,
        user_id=1,
        job_id=101,
        extracted_data_item_id="item-a",
        llm_mapping_suggestion_id=suggestion_id,
        mapper_selected_template_field_id="ifrs-smes:CashAndCashEquivalents",
        mapper_selected_qname="ifrs-smes:CashAndCashEquivalents",
        mapper_confidence=0.97,
        mapper_status="suggested",
        review_status=status,
        supervisor_decision=decision,
        supervisor_risk_level="medium",
        supervisor_recommended_action=action,
        supervisor_safe_to_accept=False,
        calibrated_safe_to_accept=False,
        supervisor_confidence_adjustment="decrease",
        supervisor_issues_json=json.dumps(
            issues
            if issues is not None
            else [{"type": "weak_label_match", "description": "Review the specific label."}]
        ),
        supervisor_reason="The selected candidate needs reconsideration.",
        supervisor_model_provider="mock",
        supervisor_model_id="mock-supervisor",
        error_type=error_type,
        review_attempt=1,
        source="mock",
        is_latest=True,
        created_at=now,
        updated_at=now,
        completed_at=now,
    )


def mapping_config():
    return LLMMappingConfig(
        model_id="unit-correction-mapper",
        max_candidates=8,
        timeout_seconds=10,
        high_confidence_threshold=0.88,
        min_display_confidence=0.5,
        min_manual_confidence=0.0,
        max_rows_per_job=1,
        fewshot_enabled=False,
    )


def completed_mapping_run(selected="ifrs-smes:Revenue"):
    return {
        "validated_mapping": {
            "selected_template_field_id": selected,
            "confidence": 0.76,
            "reason": "Supervisor issues were reconsidered against the bounded candidates.",
            "ranked_candidates": [],
            "requires_human_confirmation": True,
            "rejection_reason": None,
            "status": "suggested",
            "invalid_response": False,
            "hallucinated_concept": False,
            "model_id": "unit-correction-mapper",
        },
        "parsed_output": {
            "addressed_supervisor_issues": [
                {"type": "weak_label_match", "resolution": "Compared candidate labels."}
            ],
            "remaining_ambiguities": ["Statement-family evidence remains mixed."],
        },
    }


class SupervisorMapperFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.metadata_patch = patch(
            "services.supervisor_mapper_feedback.suggestion_template_metadata",
            side_effect=supervisor_template_metadata,
        )
        self.production_metadata_patch = patch(
            "services.supervisor_production_review.suggestion_template_metadata",
            side_effect=supervisor_template_metadata,
        )
        self.playbook_patch = patch(
            "services.supervisor_mapping_review.load_concept_playbook",
            return_value=supervisor_test_playbook(),
        )
        self.metadata_patch.start()
        self.production_metadata_patch.start()
        self.playbook_patch.start()
        self.addCleanup(self.metadata_patch.stop)
        self.addCleanup(self.production_metadata_patch.stop)
        self.addCleanup(self.playbook_patch.stop)

    def test_agree_review_is_not_eligible(self):
        eligible, reason = supervisor_feedback_eligibility(
            make_review(decision="agree", action="accept", issues=[])
        )
        self.assertFalse(eligible)
        self.assertEqual(reason, "supervisor_agreed")

    def test_disagree_prefer_alternative_and_request_better_candidate_are_eligible(self):
        cases = [
            make_review(decision="disagree", action="reject"),
            make_review(decision="needs_human_review", action="prefer_alternative_candidate"),
            make_review(decision="needs_human_review", action="request_better_candidate"),
        ]
        self.assertTrue(all(supervisor_feedback_eligibility(review)[0] for review in cases))

    def test_missing_incomplete_and_unsafe_reviews_are_rejected(self):
        self.assertFalse(supervisor_feedback_eligibility(None)[0])
        self.assertFalse(
            supervisor_feedback_eligibility(make_review(status="failed"))[0]
        )
        unsafe = make_review(
            issues=[{"type": "invalid_supervisor_response", "description": "invalid"}]
        )
        self.assertFalse(supervisor_feedback_eligibility(unsafe)[0])

    def test_feedback_payload_is_whitelisted_and_prompt_is_strict_advisory_json(self):
        session = FakeSupervisorSession()
        suggestion = session.suggestions["suggestion-a"]
        suggestion.ranked_candidates_json = json.dumps(
            [
                {"template_field_id": "ifrs-smes:CashAndCashEquivalents", "confidence": 0.97},
                {"template_field_id": "ifrs-smes:Revenue", "confidence": 0.61},
            ]
        )
        payload = build_supervisor_mapper_feedback_payload(suggestion, make_review())
        prompt = build_supervisor_guided_mapping_prompt(payload)
        serialized = json.dumps(payload, sort_keys=True).lower()

        self.assertIn("supervisor feedback is advisory evidence", prompt.lower())
        self.assertIn("not guaranteed to be correct", prompt.lower())
        self.assertIn("return strict json only", prompt.lower())
        self.assertNotIn("retrieved_fewshot_examples", payload)
        self.assertNotIn("example_mappings", serialized)
        for forbidden in FORBIDDEN_FEEDBACK_KEYS:
            self.assertNotIn(f'"{forbidden.lower()}"', serialized)

    def test_forbidden_gold_or_evaluation_fields_fail_closed(self):
        for key in sorted(FORBIDDEN_FEEDBACK_KEYS):
            with self.assertRaises(ValueError):
                assert_supervisor_mapper_feedback_safe({"row": {key: "forbidden"}})

    def test_no_recursive_supervisor_or_auto_apply_path_exists(self):
        from services import supervisor_guided_mapping_correction as service

        source = inspect.getsource(service.run_supervisor_guided_mapping_correction)
        self.assertNotIn("run_supervisor_review_for_suggestion", source)
        self.assertNotIn("confirmed_tag_id =", source)
        self.assertNotIn("template_field_id =", source)


class SupervisorGuidedCorrectionServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.metadata_patch = patch(
            "services.supervisor_mapper_feedback.suggestion_template_metadata",
            side_effect=supervisor_template_metadata,
        )
        self.production_metadata_patch = patch(
            "services.supervisor_production_review.suggestion_template_metadata",
            side_effect=supervisor_template_metadata,
        )
        self.playbook_patch = patch(
            "services.supervisor_mapping_review.load_concept_playbook",
            return_value=supervisor_test_playbook(),
        )
        self.metadata_patch.start()
        self.production_metadata_patch.start()
        self.playbook_patch.start()
        self.addCleanup(self.metadata_patch.stop)
        self.addCleanup(self.production_metadata_patch.stop)
        self.addCleanup(self.playbook_patch.stop)

    async def test_disabled_flag_fails_before_any_mapper_call(self):
        session = FakeSupervisorSession()
        mapper = AsyncMock()
        with self.assertRaises(SupervisorGuidedCorrectionDisabled):
            await run_supervisor_guided_mapping_correction(
                session,
                job_id=101,
                suggestion_id="suggestion-a",
                user_id=1,
                is_admin=True,
                config=SupervisorGuidedCorrectionConfig(enabled=False),
                llm_client=mapper,
            )
        mapper.assert_not_called()
        self.assertEqual(session.mapping_revisions, [])

    async def test_success_persists_separate_revision_and_preserves_initial_suggestion(self):
        session = FakeSupervisorSession()
        session.reviews.append(make_review())
        session._wire_relationships()
        suggestion = session.suggestions["suggestion-a"]
        suggestion.ranked_candidates_json = json.dumps(
            [
                {"template_field_id": "ifrs-smes:CashAndCashEquivalents", "confidence": 0.97},
                {"template_field_id": "ifrs-smes:Revenue", "confidence": 0.61},
            ]
        )
        initial_snapshot = (
            suggestion.suggested_template_field_id,
            suggestion.confidence,
            suggestion.reason,
            suggestion.status,
        )

        with patch(
            "services.supervisor_guided_mapping_correction.run_llm_mapping_advisory_prompt",
            new=AsyncMock(return_value=completed_mapping_run()),
        ):
            response = await run_supervisor_guided_mapping_correction(
                session,
                job_id=101,
                suggestion_id="suggestion-a",
                user_id=1,
                is_admin=False,
                config=SupervisorGuidedCorrectionConfig(
                    enabled=True,
                    auto_run=False,
                    max_retries=1,
                    admin_only=False,
                    allowed_user_ids="1",
                ),
                llm_config=mapping_config(),
            )

        self.assertEqual(len(session.mapping_revisions), 1)
        revision = session.mapping_revisions[0]
        self.assertIsInstance(revision, SupervisorGuidedMappingRevision)
        self.assertEqual(revision.parent_suggestion_id, suggestion.id)
        self.assertEqual(revision.revised_suggested_qname, "ifrs-smes:Revenue")
        self.assertTrue(revision.requires_human_review)
        self.assertFalse(revision.safe_for_auto_apply)
        self.assertEqual(
            initial_snapshot,
            (
                suggestion.suggested_template_field_id,
                suggestion.confidence,
                suggestion.reason,
                suggestion.status,
            ),
        )
        self.assertEqual(response["safety"]["confirmed_tag_id_mutations"], 0)
        self.assertEqual(response["safety"]["final_mapping_mutations"], 0)
        self.assertEqual(response["safety"]["auto_apply_count"], 0)
        self.assertEqual(response["safety"]["auto_accept_count"], 0)
        self.assertIsNone(session.items["item-a"].confirmed_tag_id)
        self.assertIsNone(session.items["item-a"].template_field_id)

    async def test_retry_limit_is_durable_and_second_mapper_call_is_blocked(self):
        session = FakeSupervisorSession()
        session.reviews.append(make_review())
        session._wire_relationships()
        mapper_run = AsyncMock(return_value=completed_mapping_run())
        config = SupervisorGuidedCorrectionConfig(
            enabled=True,
            auto_run=False,
            max_retries=1,
            admin_only=False,
            allowed_user_ids="1",
        )

        with patch(
            "services.supervisor_guided_mapping_correction.run_llm_mapping_advisory_prompt",
            new=mapper_run,
        ):
            await run_supervisor_guided_mapping_correction(
                session,
                job_id=101,
                suggestion_id="suggestion-a",
                user_id=1,
                is_admin=False,
                config=config,
                llm_config=mapping_config(),
            )
            with self.assertRaises(SupervisorGuidedCorrectionRetryLimit):
                await run_supervisor_guided_mapping_correction(
                    session,
                    job_id=101,
                    suggestion_id="suggestion-a",
                    user_id=1,
                    is_admin=False,
                    config=config,
                    llm_config=mapping_config(),
                )

        self.assertEqual(mapper_run.await_count, 1)
        self.assertEqual(len(session.mapping_revisions), 1)

    async def test_missing_eligible_review_is_rejected(self):
        with self.assertRaises(SupervisorGuidedCorrectionNotEligible):
            await run_supervisor_guided_mapping_correction(
                FakeSupervisorSession(),
                job_id=101,
                suggestion_id="suggestion-a",
                user_id=1,
                is_admin=False,
                config=SupervisorGuidedCorrectionConfig(
                    enabled=True,
                    max_retries=1,
                    admin_only=False,
                    allowed_user_ids="1",
                ),
                llm_config=mapping_config(),
            )


class SupervisorGuidedCorrectionApiTests(unittest.TestCase):
    def test_endpoint_fails_closed_when_disabled(self):
        session = FakeSupervisorSession()
        app = build_supervisor_review_app(session, user_id=1)
        with patch.object(
            __import__("routers.filings", fromlist=["settings"]).settings,
            "supervisor_mapper_feedback_enabled",
            False,
        ), TestClient(app) as client:
            response = client.post(
                "/api/v1/filings/jobs/101/suggestions/suggestion-a/remap-with-supervisor-feedback"
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(session.mapping_revisions, [])

    def test_endpoint_requires_owned_job(self):
        session = FakeSupervisorSession()
        app = build_supervisor_review_app(session, user_id=1)
        with patch("routers.filings.settings.supervisor_mapper_feedback_enabled", True), patch(
            "routers.filings.settings.supervisor_mapper_feedback_admin_only", False
        ), TestClient(app) as client:
            response = client.post(
                "/api/v1/filings/jobs/202/suggestions/suggestion-b/remap-with-supervisor-feedback"
            )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(session.mapping_revisions, [])

    def test_owned_manual_run_returns_separate_revision_and_enforces_retry(self):
        session = FakeSupervisorSession()
        session.reviews.append(make_review())
        session._wire_relationships()
        session.suggestions["suggestion-a"].ranked_candidates_json = json.dumps(
            [
                {"template_field_id": "ifrs-smes:CashAndCashEquivalents", "confidence": 0.97},
                {"template_field_id": "ifrs-smes:Revenue", "confidence": 0.61},
            ]
        )
        app = build_supervisor_review_app(session, user_id=1)
        mapper_run = AsyncMock(return_value=completed_mapping_run())

        with patch("routers.filings.settings.supervisor_mapper_feedback_enabled", True), patch(
            "routers.filings.settings.supervisor_mapper_feedback_auto_run", False
        ), patch(
            "routers.filings.settings.supervisor_mapper_feedback_admin_only", False
        ), patch(
            "routers.filings.settings.supervisor_mapper_feedback_max_retries", 1
        ), patch(
            "routers.filings.settings.supervisor_orchestration_allowed_user_ids", "1"
        ), patch(
            "services.supervisor_guided_mapping_correction.run_llm_mapping_advisory_prompt",
            new=mapper_run,
        ), patch(
            "services.supervisor_mapper_feedback.suggestion_template_metadata",
            side_effect=supervisor_template_metadata,
        ), patch(
            "services.supervisor_production_review.suggestion_template_metadata",
            side_effect=supervisor_template_metadata,
        ), patch(
            "services.supervisor_mapping_review.load_concept_playbook",
            return_value=supervisor_test_playbook(),
        ), TestClient(app) as client:
            capabilities = client.get(
                "/api/v1/filings/jobs/101/supervisor-mapper-feedback/capabilities"
            )
            first = client.post(
                "/api/v1/filings/jobs/101/suggestions/suggestion-a/remap-with-supervisor-feedback"
            )
            listed = client.get(
                "/api/v1/filings/jobs/101/supervisor-guided-mapping-revisions"
            )
            second = client.post(
                "/api/v1/filings/jobs/101/suggestions/suggestion-a/remap-with-supervisor-feedback"
            )

        self.assertEqual(capabilities.status_code, 200)
        self.assertTrue(capabilities.json()["available"])
        self.assertEqual(first.status_code, 200)
        body = first.json()
        self.assertEqual(body["initial_suggestion"]["id"], "suggestion-a")
        self.assertEqual(
            body["revised_suggestion"]["revised_suggested_qname"],
            "ifrs-smes:Revenue",
        )
        self.assertTrue(body["revised_suggestion"]["requires_human_review"])
        self.assertFalse(body["revised_suggestion"]["safe_for_auto_apply"])
        self.assertEqual(body["safety"]["confirmed_tag_id_mutations"], 0)
        self.assertEqual(body["safety"]["final_mapping_mutations"], 0)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()), 1)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(mapper_run.await_count, 1)
        self.assertEqual(session.suggestions["suggestion-a"].status, "suggested")
        self.assertIsNone(session.items["item-a"].confirmed_tag_id)


class SupervisorGuidedRevisionPersistenceTests(unittest.TestCase):
    def test_model_and_migration_enforce_separate_human_review_only_revision(self):
        table = SupervisorGuidedMappingRevision.__table__
        columns = set(table.columns.keys())
        self.assertEqual(table.name, "supervisor_guided_mapping_revisions")
        for field in (
            "parent_suggestion_id",
            "supervisor_review_id",
            "correction_attempt",
            "original_suggested_qname",
            "revised_suggested_qname",
            "requires_human_review",
            "safe_for_auto_apply",
        ):
            self.assertIn(field, columns)
        self.assertNotIn("confirmed_tag_id", columns)
        self.assertNotIn("final_mapping", columns)

        migration = Path(
            "migrations/013_add_supervisor_guided_mapping_revisions.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS supervisor_guided_mapping_revisions", migration)
        self.assertIn("requires_human_review = TRUE", migration)
        self.assertIn("safe_for_auto_apply = FALSE", migration)
        self.assertIn("UNIQUE INDEX IF NOT EXISTS idx_supervisor_guided_revisions_parent", migration)


if __name__ == "__main__":
    unittest.main()
