import asyncio
import inspect
import json
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from routers import filings
from services import (
    supervisor_guided_mapping_correction,
    supervisor_production_review,
)
from services.supervisor_rollout_observability import (
    build_supervisor_rollout_operational_report,
)
from tests.supervisor_review_fakes import FakeSupervisorSession
from tests.test_supervisor_review_api import build_supervisor_review_app


class SupervisorRolloutSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_provider_concurrency_is_bounded_per_process(self):
        active = 0
        maximum_active = 0

        async def worker():
            nonlocal active, maximum_active
            async with supervisor_production_review.supervisor_live_call_slot(
                max_concurrent=1,
                wait_timeout_seconds=2,
            ):
                active += 1
                maximum_active = max(maximum_active, active)
                await asyncio.sleep(0.01)
                active -= 1

        await asyncio.gather(worker(), worker(), worker())
        self.assertEqual(maximum_active, 1)

    def test_action_paths_take_database_row_locks_for_duplicate_protection(self):
        loader_source = inspect.getsource(
            supervisor_production_review.load_ai_mapping_suggestion_for_supervisor
        )
        review_source = inspect.getsource(
            supervisor_production_review._create_supervisor_review_for_suggestion
        )
        correction_source = inspect.getsource(
            supervisor_guided_mapping_correction.run_supervisor_guided_mapping_correction
        )
        self.assertIn("with_for_update", loader_source)
        self.assertIn("lock_for_update=True", review_source)
        self.assertIn("lock_for_update=True", correction_source)

    def test_operational_report_uses_existing_records_and_keeps_safety_zero(self):
        started = datetime(2026, 7, 28, 10, 0, 0)
        suggestion = SimpleNamespace(
            id="suggestion-1",
            job_id=101,
            extracted_data_item_id="row-1",
            suggested_template_field_id="ifrs-smes:Revenue",
            status="accepted",
            job=SimpleNamespace(user_id=1),
        )
        review = SimpleNamespace(
            id="review-1",
            user_id=1,
            job_id=101,
            extracted_data_item_id="row-1",
            llm_mapping_suggestion_id="suggestion-1",
            mapper_selected_qname="ifrs-smes:Revenue",
            review_status="completed",
            supervisor_decision="agree",
            supervisor_risk_level="low",
            supervisor_recommended_action="accept",
            supervisor_model_provider="hf",
            supervisor_model_id="unit-supervisor",
            supervisor_prompt_version="17d-b-hotfix-6",
            supervisor_schema_version="17d-b",
            source="live",
            started_at=started,
            completed_at=started + timedelta(seconds=2),
            created_at=started,
        )
        revision = SimpleNamespace(
            id="revision-1",
            job_id=101,
            parent_suggestion_id="suggestion-1",
            supervisor_review_id="review-1",
            correction_attempt=1,
            correction_source="supervisor_feedback",
            original_suggested_qname="ifrs-smes:Revenue",
            revised_suggested_qname="ifrs-smes:OtherIncome",
            supervisor_decision="needs_human_review",
            status="completed",
            model_id="unit-qwen",
            created_at=started,
            completed_at=started + timedelta(seconds=3),
        )
        plan = {
            "policy_eligible_count": 1,
            "high_priority_count": 1,
            "medium_priority_count": 0,
            "items": [
                {
                    "remapping_action_block_reason": (
                        "correction_retry_limit_reached"
                    )
                }
            ],
            "safety_summary": {
                "auto_review_calls": 0,
                "auto_remap_calls": 0,
                "auto_apply_count": 0,
                "confirmed_tag_id_mutations": 0,
                "final_mapping_mutations": 0,
            },
        }

        report = build_supervisor_rollout_operational_report(
            plans=[plan],
            reviews=[review],
            revisions=[revision],
            suggestions=[suggestion],
        )

        metrics = report["metrics"]
        self.assertEqual(metrics["supervisor_review_attempts"], 1)
        self.assertEqual(metrics["supervisor_review_successes"], 1)
        self.assertEqual(metrics["supervisor_provider_latency_ms_average"], 2000)
        self.assertEqual(metrics["changed_qname"], 1)
        self.assertEqual(metrics["retry_blocked_count"], 1)
        self.assertEqual(metrics["eventual_accept"], 1)
        self.assertTrue(all(value == 0 for value in report["safety_counters"].values()))
        self.assertEqual(len(report["audit_rows"]), 2)
        revision_event = report["audit_rows"][1]
        self.assertEqual(revision_event["user_id"], 1)
        self.assertEqual(revision_event["user_id_source"], "linked_review")
        self.assertTrue(revision_event["requires_human_review"])
        self.assertFalse(revision_event["safe_for_auto_apply"])
        encoded = json.dumps(report).lower()
        for forbidden in (
            "auditor_xml",
            "parsed_xml_fact",
            "gold_answer",
            "target_correct_qname",
            "evaluation_label",
        ):
            self.assertNotIn(forbidden, encoded)


class SupervisorRolloutConfigurationTests(unittest.TestCase):
    def test_repository_examples_remain_disabled_and_restrictive(self):
        backend = Path(".env.example").read_text(encoding="utf-8")
        docker = Path(".env.docker.example").read_text(encoding="utf-8")
        frontend = Path("frontend/.env.example").read_text(encoding="utf-8")
        for content in (backend, docker):
            self.assertIn("SUPERVISOR_PRODUCTION_LIVE_ENABLED=false", content)
            self.assertIn("SUPERVISOR_MAPPER_FEEDBACK_ENABLED=false", content)
            self.assertIn("SUPERVISOR_ORCHESTRATION_ENABLED=false", content)
            self.assertIn("SUPERVISOR_ORCHESTRATION_AUTO_REVIEW=false", content)
            self.assertIn("SUPERVISOR_ORCHESTRATION_AUTO_REMAP=false", content)
            self.assertIn("SUPERVISOR_ORCHESTRATION_ADMIN_ONLY=true", content)
            self.assertIn("SUPERVISOR_ORCHESTRATION_ALLOWED_USER_IDS=", content)
            self.assertIn("SUPERVISOR_ORCHESTRATION_MAX_BATCH_SIZE=10", content)
            self.assertIn("SUPERVISOR_ORCHESTRATION_MAX_REMAP_RETRIES=1", content)
        self.assertIn(
            "VITE_SHOW_SUPERVISOR_ORCHESTRATION_QUEUE=false",
            frontend,
        )
        self.assertIn("VITE_SHOW_SUPERVISOR_MAPPER_FEEDBACK=false", frontend)
        self.assertIn("VITE_SHOW_SUPERVISOR_MOCK_CONTROLS=false", frontend)

    def test_disabling_flags_preserves_existing_audit_history(self):
        session = FakeSupervisorSession()
        app = build_supervisor_review_app(session, user_id=1)
        with TestClient(app) as client:
            created = client.post(
                "/api/v1/filings/jobs/101/supervisor-reviews/run",
                json={"llm_mapping_suggestion_id": "suggestion-a"},
            )
        self.assertEqual(created.status_code, 200)
        self.assertEqual(len(session.reviews), 1)

        with patch.object(
            filings.settings,
            "supervisor_production_live_enabled",
            False,
        ), patch.object(
            filings.settings,
            "supervisor_mapper_feedback_enabled",
            False,
        ), patch.object(
            filings.settings,
            "supervisor_orchestration_enabled",
            False,
        ), TestClient(app) as client:
            history = client.get(
                "/api/v1/filings/jobs/101/supervisor-reviews"
            )
            plan = client.get(
                "/api/v1/filings/jobs/101/supervisor-orchestration/plan"
            )

        self.assertEqual(history.status_code, 200)
        self.assertEqual(len(history.json()), 1)
        self.assertEqual(plan.status_code, 403)
        self.assertEqual(len(session.reviews), 1)


if __name__ == "__main__":
    unittest.main()
