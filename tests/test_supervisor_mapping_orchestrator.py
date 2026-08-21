import inspect
import json
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from database import MappingSupervisorReview, SupervisorGuidedMappingRevision
from services import supervisor_mapping_orchestrator as orchestrator_module
from services.supervisor_mapping_orchestrator import (
    SupervisorOrchestrationBatchLimit,
    SupervisorOrchestrationConfig,
    SupervisorOrchestrationDisabled,
    SupervisorOrchestrationForbidden,
    SupervisorOrchestrationNotFound,
    SupervisorOrchestrationUnsafeConfig,
    build_supervisor_orchestration_plan,
    plan_supervisor_orchestration_for_job,
    run_manual_batch_reviews,
    run_manual_guided_remap,
    run_manual_single_review,
)
from tests.supervisor_review_fakes import FakeSupervisorSession
from tests.test_supervisor_review_api import build_supervisor_review_app


def enabled_config(**overrides):
    values = {
        "enabled": True,
        "default_mode": "manual",
        "auto_eligibility": True,
        "auto_review": False,
        "auto_remap": False,
        "admin_only": False,
        "max_batch_size": 2,
        "max_remap_retries": 1,
        "min_risk": "medium",
        "max_concurrent_live_calls": 2,
        "confidence_threshold": 0.85,
        "per_row_timeout_seconds": 10,
        "review_execution_enabled": True,
        "review_execution_admin_only": False,
        "remap_execution_enabled": True,
        "remap_execution_auto_run": False,
        "remap_execution_admin_only": False,
        "remap_execution_max_retries": 1,
        "allowed_user_ids": "1",
    }
    values.update(overrides)
    return SupervisorOrchestrationConfig(**values)


def eligible_review(suggestion_id="suggestion-cashflow"):
    now = datetime(2026, 7, 23, 12, 0, 0)
    return MappingSupervisorReview(
        id=f"review-{suggestion_id}",
        user_id=1,
        job_id=101,
        extracted_data_item_id="item-cashflow",
        llm_mapping_suggestion_id=suggestion_id,
        mapper_selected_template_field_id="ifrs-smes:CashAndCashEquivalents",
        mapper_selected_qname="ifrs-smes:CashAndCashEquivalents",
        mapper_confidence=0.97,
        mapper_status="suggested",
        review_status="completed",
        supervisor_decision="needs_human_review",
        supervisor_risk_level="medium",
        supervisor_recommended_action="keep_for_human_review",
        supervisor_safe_to_accept=False,
        calibrated_safe_to_accept=False,
        supervisor_confidence_adjustment="decrease",
        supervisor_issues_json=json.dumps(
            [{"type": "statement_family_mismatch", "description": "wrong family"}]
        ),
        supervisor_reason="Review the statement family.",
        supervisor_model_provider="mock",
        supervisor_model_id="mock-supervisor",
        supervisor_prompt_version="unit",
        review_attempt=1,
        source="mock",
        is_latest=True,
        created_at=now,
        updated_at=now,
        completed_at=now,
    )


class SupervisorMappingOrchestratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_plan_only_generates_queue_without_live_calls(self):
        session = FakeSupervisorSession()
        review_runner = AsyncMock()
        remap_runner = AsyncMock()
        with patch.object(
            orchestrator_module,
            "run_supervisor_review_for_suggestion",
            review_runner,
        ), patch.object(
            orchestrator_module,
            "run_supervisor_guided_mapping_correction",
            remap_runner,
        ):
            plan = await plan_supervisor_orchestration_for_job(
                session,
                job_id=101,
                user_id=1,
                is_admin=False,
                config=enabled_config(),
            )

        self.assertEqual(plan["mode"], "plan_only")
        self.assertEqual(plan["total_suggestions"], 2)
        self.assertEqual(plan["eligible_count"], 1)
        self.assertEqual(plan["not_eligible_count"], 1)
        self.assertEqual(plan["safety_summary"]["external_calls"], 0)
        self.assertTrue(
            all(
                isinstance(item["eligibility_score"], int)
                and isinstance(item["strong_signals"], list)
                and isinstance(item["weak_signals"], list)
                for item in plan["items"]
            )
        )
        review_runner.assert_not_awaited()
        remap_runner.assert_not_awaited()

    async def test_disabled_feature_fails_closed(self):
        session = FakeSupervisorSession()
        with self.assertRaises(SupervisorOrchestrationDisabled):
            await plan_supervisor_orchestration_for_job(
                session,
                job_id=101,
                user_id=1,
                is_admin=False,
                config=enabled_config(enabled=False),
            )

    async def test_owned_job_access_is_enforced(self):
        session = FakeSupervisorSession()
        with self.assertRaises(SupervisorOrchestrationNotFound):
            await plan_supervisor_orchestration_for_job(
                session,
                job_id=202,
                user_id=1,
                is_admin=False,
                config=enabled_config(),
            )

    async def test_admin_only_gate_is_enforced(self):
        with self.assertRaises(SupervisorOrchestrationForbidden):
            await plan_supervisor_orchestration_for_job(
                FakeSupervisorSession(),
                job_id=101,
                user_id=1,
                is_admin=False,
                config=enabled_config(admin_only=True, allowed_user_ids=""),
            )

    async def test_unsafe_auto_execution_config_fails_closed(self):
        with self.assertRaises(SupervisorOrchestrationUnsafeConfig):
            await plan_supervisor_orchestration_for_job(
                FakeSupervisorSession(),
                job_id=101,
                user_id=1,
                is_admin=True,
                config=enabled_config(auto_review=True),
            )

    async def test_manual_single_delegates_only_after_explicit_request(self):
        delegate = AsyncMock(return_value=("review", True))
        result = await run_manual_single_review(
            FakeSupervisorSession(),
            job_id=101,
            suggestion_id="suggestion-a",
            user_id=1,
            is_admin=False,
            explicit_manual_request=True,
            config=enabled_config(),
            delegate=delegate,
        )
        self.assertEqual(result, ("review", True))
        delegate.assert_awaited_once()

        blocked_delegate = AsyncMock()
        with self.assertRaises(SupervisorOrchestrationForbidden):
            await run_manual_single_review(
                FakeSupervisorSession(),
                job_id=101,
                suggestion_id="suggestion-a",
                user_id=1,
                is_admin=False,
                explicit_manual_request=False,
                config=enabled_config(),
                delegate=blocked_delegate,
            )
        blocked_delegate.assert_not_awaited()

    async def test_bounded_batch_limit_is_enforced_before_delegate(self):
        delegate = AsyncMock()
        with self.assertRaises(SupervisorOrchestrationBatchLimit):
            await run_manual_batch_reviews(
                FakeSupervisorSession(),
                job_id=101,
                user_id=1,
                is_admin=False,
                requested_count=3,
                explicit_manual_request=True,
                config=enabled_config(max_batch_size=2),
                delegate=delegate,
            )
        delegate.assert_not_awaited()

    async def test_remapping_available_only_after_eligible_completed_review(self):
        session = FakeSupervisorSession()
        before = build_supervisor_orchestration_plan(
            job=session.jobs[101],
            suggestions=[session.suggestions["suggestion-cashflow"]],
            reviews=[],
            revisions=[],
            config=enabled_config(),
            user_id=1,
        )
        self.assertEqual(
            before["items"][0]["remapping_eligibility"],
            "remapping_not_evaluated",
        )

        after = build_supervisor_orchestration_plan(
            job=session.jobs[101],
            suggestions=[session.suggestions["suggestion-cashflow"]],
            reviews=[eligible_review()],
            revisions=[],
            config=enabled_config(),
            user_id=1,
        )
        self.assertEqual(
            after["items"][0]["remapping_eligibility"],
            "remapping_available",
        )
        self.assertEqual(after["remapping_available_count"], 1)

    async def test_plan_preserves_original_and_advisory_safety_fields(self):
        session = FakeSupervisorSession()
        suggestion = session.suggestions["suggestion-cashflow"]
        item = suggestion.extracted_data_item
        snapshot = (
            suggestion.status,
            suggestion.suggested_template_field_id,
            item.template_field_id,
            item.confirmed_tag_id,
            item.is_reviewed,
        )
        plan = await plan_supervisor_orchestration_for_job(
            session,
            job_id=101,
            user_id=1,
            is_admin=False,
            config=enabled_config(),
        )
        self.assertEqual(
            snapshot,
            (
                suggestion.status,
                suggestion.suggested_template_field_id,
                item.template_field_id,
                item.confirmed_tag_id,
                item.is_reviewed,
            ),
        )
        for queue_item in plan["items"]:
            self.assertTrue(queue_item["requires_human_review"])
            self.assertFalse(queue_item["safe_for_auto_apply"])
        self.assertEqual(plan["safety_summary"]["confirmed_tag_id_mutations"], 0)
        self.assertEqual(plan["safety_summary"]["final_mapping_mutations"], 0)

    async def test_supervisor_and_remapping_failures_are_isolated(self):
        session = FakeSupervisorSession()
        suggestion = session.suggestions["suggestion-a"]
        item = suggestion.extracted_data_item
        snapshot = (
            suggestion.status,
            suggestion.suggested_template_field_id,
            item.template_field_id,
            item.confirmed_tag_id,
        )
        failed_review = AsyncMock(side_effect=RuntimeError("review failed"))
        with self.assertRaises(RuntimeError):
            await run_manual_single_review(
                session,
                job_id=101,
                suggestion_id=suggestion.id,
                user_id=1,
                is_admin=False,
                explicit_manual_request=True,
                config=enabled_config(),
                delegate=failed_review,
            )
        failed_remap = AsyncMock(side_effect=RuntimeError("remap failed"))
        with self.assertRaises(RuntimeError):
            await run_manual_guided_remap(
                session,
                job_id=101,
                suggestion_id=suggestion.id,
                user_id=1,
                is_admin=False,
                explicit_manual_request=True,
                config=enabled_config(),
                delegate=failed_remap,
            )
        self.assertEqual(
            snapshot,
            (
                suggestion.status,
                suggestion.suggested_template_field_id,
                item.template_field_id,
                item.confirmed_tag_id,
            ),
        )
        self.assertEqual(session.mapping_revisions, [])

    def test_no_recursion_or_final_mapping_mutation_path_exists(self):
        plan_source = inspect.getsource(
            orchestrator_module.plan_supervisor_orchestration_for_job
        )
        self.assertNotIn("run_manual_single_review", plan_source)
        self.assertNotIn("run_manual_guided_remap", plan_source)
        self.assertNotIn("confirmed_tag_id =", inspect.getsource(orchestrator_module))
        self.assertNotIn("template_field_id =", inspect.getsource(orchestrator_module))


class SupervisorMappingOrchestrationApiTests(unittest.TestCase):
    def test_capabilities_visible_while_disabled_and_plan_fails_closed(self):
        app = build_supervisor_review_app(FakeSupervisorSession(), user_id=1)
        with patch("routers.filings.settings.supervisor_orchestration_enabled", False), patch(
            "routers.filings.settings.supervisor_orchestration_admin_only", False
        ), TestClient(app) as client:
            capabilities = client.get(
                "/api/v1/filings/jobs/101/supervisor-orchestration/capabilities"
            )
            plan = client.get(
                "/api/v1/filings/jobs/101/supervisor-orchestration/plan"
            )
        self.assertEqual(capabilities.status_code, 200)
        self.assertFalse(capabilities.json()["enabled"])
        self.assertFalse(capabilities.json()["available"])
        self.assertEqual(plan.status_code, 403)

    def test_plan_endpoint_returns_valid_read_only_queue(self):
        session = FakeSupervisorSession()
        app = build_supervisor_review_app(session, user_id=1)
        patches = [
            patch("routers.filings.settings.supervisor_orchestration_enabled", True),
            patch("routers.filings.settings.supervisor_orchestration_admin_only", False),
            patch("routers.filings.settings.supervisor_orchestration_default_mode", "manual"),
            patch("routers.filings.settings.supervisor_orchestration_auto_review", False),
            patch("routers.filings.settings.supervisor_orchestration_auto_remap", False),
            patch("routers.filings.settings.supervisor_orchestration_max_remap_retries", 1),
            patch("routers.filings.settings.supervisor_orchestration_allowed_user_ids", "1"),
        ]
        for active_patch in patches:
            active_patch.start()
            self.addCleanup(active_patch.stop)
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/filings/jobs/101/supervisor-orchestration/plan"
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["mode"], "plan_only")
        self.assertEqual(body["total_suggestions"], 2)
        self.assertEqual(
            body["high_priority_count"] + body["medium_priority_count"],
            body["eligible_count"],
        )
        self.assertEqual(body["safety_summary"]["external_calls"], 0)
        self.assertEqual(body["safety_summary"]["planning_live_calls"], 0)
        self.assertEqual(body["safety_summary"]["auto_review_calls"], 0)
        self.assertEqual(body["safety_summary"]["auto_remap_calls"], 0)
        self.assertEqual(body["safety_summary"]["confirmed_tag_id_mutations"], 0)
        self.assertEqual(body["safety_summary"]["final_mapping_mutations"], 0)
        self.assertEqual(body["safety_summary"]["safe_for_auto_apply_count"], 0)
        self.assertTrue(body["safety_summary"]["human_review_required"])
        self.assertTrue(all(item["requires_human_review"] for item in body["items"]))
        self.assertTrue(
            all(not item["safe_for_auto_apply"] for item in body["items"])
        )
        self.assertTrue(
            all(
                "eligibility_score" in item
                and "strong_signals" in item
                and "weak_signals" in item
                for item in body["items"]
            )
        )

    def test_plan_endpoint_enforces_owned_job_access(self):
        app = build_supervisor_review_app(FakeSupervisorSession(), user_id=1)
        with patch("routers.filings.settings.supervisor_orchestration_enabled", True), patch(
            "routers.filings.settings.supervisor_orchestration_admin_only", False
        ), TestClient(app) as client:
            response = client.get(
                "/api/v1/filings/jobs/202/supervisor-orchestration/plan"
            )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
