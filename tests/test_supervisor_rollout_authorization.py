import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from routers import filings
from services.supervisor_llm_client import SupervisorLLMConfig
from services.supervisor_rollout_authorization import (
    authorize_supervisor_rollout_user,
    parse_supervisor_reviewer_allowlist,
)
from tests.supervisor_review_fakes import FakeSupervisorSession
from tests.test_supervisor_review_api import (
    FakeLiveSupervisorClient,
    build_supervisor_review_app,
)


class SupervisorRolloutAuthorizationUnitTests(unittest.TestCase):
    def test_allowlist_parses_positive_unique_user_ids(self):
        parsed = parse_supervisor_reviewer_allowlist("7, 2,7")
        self.assertEqual(parsed.user_ids, frozenset({2, 7}))
        self.assertTrue(parsed.valid)
        self.assertTrue(parsed.configured)

    def test_invalid_allowlist_fails_closed_even_for_admin(self):
        decision = authorize_supervisor_rollout_user(
            user_id=1,
            is_admin=True,
            allowed_user_ids="1,not-a-user",
        )
        self.assertFalse(decision.authorized)
        self.assertEqual(decision.source, "invalid_allowlist")
        self.assertFalse(decision.configuration_valid)

    def test_only_admin_or_explicit_reviewer_is_authorized(self):
        normal = authorize_supervisor_rollout_user(
            user_id=2,
            is_admin=False,
            allowed_user_ids="1",
        )
        reviewer = authorize_supervisor_rollout_user(
            user_id=1,
            is_admin=False,
            allowed_user_ids="1",
        )
        admin = authorize_supervisor_rollout_user(
            user_id=9,
            is_admin=True,
            allowed_user_ids="1",
        )
        self.assertFalse(normal.authorized)
        self.assertTrue(reviewer.authorized)
        self.assertTrue(reviewer.internal_reviewer)
        self.assertEqual(reviewer.source, "internal_reviewer_allowlist")
        self.assertTrue(admin.authorized)
        self.assertEqual(admin.source, "admin")


class SupervisorRolloutAuthorizationApiTests(unittest.TestCase):
    def _orchestration_patches(self, allowed_user_ids="1", enabled=True):
        return [
            patch.object(
                filings.settings,
                "supervisor_orchestration_enabled",
                enabled,
            ),
            patch.object(
                filings.settings,
                "supervisor_orchestration_admin_only",
                True,
            ),
            patch.object(
                filings.settings,
                "supervisor_orchestration_allowed_user_ids",
                allowed_user_ids,
            ),
            patch.object(
                filings.settings,
                "supervisor_orchestration_default_mode",
                "manual",
            ),
            patch.object(
                filings.settings,
                "supervisor_orchestration_auto_review",
                False,
            ),
            patch.object(
                filings.settings,
                "supervisor_orchestration_auto_remap",
                False,
            ),
            patch.object(
                filings.settings,
                "supervisor_orchestration_max_remap_retries",
                1,
            ),
        ]

    def _start(self, patches):
        for active_patch in patches:
            active_patch.start()
            self.addCleanup(active_patch.stop)

    def test_authorized_reviewer_can_plan_owned_job_without_allowlist_disclosure(self):
        app = build_supervisor_review_app(FakeSupervisorSession(), user_id=1)
        self._start(self._orchestration_patches())

        with TestClient(app) as client:
            capabilities = client.get(
                "/api/v1/filings/jobs/101/supervisor-orchestration/capabilities"
            )
            plan = client.get(
                "/api/v1/filings/jobs/101/supervisor-orchestration/plan"
            )

        self.assertEqual(capabilities.status_code, 200)
        body = capabilities.json()
        self.assertTrue(body["available"])
        self.assertTrue(body["authorized"])
        self.assertTrue(body["internal_reviewer"])
        self.assertEqual(
            body["authorization_source"],
            "internal_reviewer_allowlist",
        )
        self.assertEqual(body["reviewer_allowlist_user_count"], 1)
        self.assertNotIn("allowed_user_ids", body)
        self.assertEqual(plan.status_code, 200)
        self.assertEqual(
            plan.json()["authorization_source"],
            "internal_reviewer_allowlist",
        )
        self.assertEqual(plan.json()["safety_summary"]["external_calls"], 0)

    def test_unauthorized_owner_is_denied_and_allowlisted_user_cannot_cross_owner(self):
        owner_two_app = build_supervisor_review_app(
            FakeSupervisorSession(),
            user_id=2,
        )
        self._start(self._orchestration_patches(allowed_user_ids="1"))
        with TestClient(owner_two_app) as client:
            denied = client.get(
                "/api/v1/filings/jobs/202/supervisor-orchestration/plan"
            )
        self.assertEqual(denied.status_code, 403)

        owner_one_app = build_supervisor_review_app(
            FakeSupervisorSession(),
            user_id=1,
        )
        with TestClient(owner_one_app) as client:
            cross_owner = client.get(
                "/api/v1/filings/jobs/202/supervisor-orchestration/plan"
            )
        self.assertEqual(cross_owner.status_code, 404)

    def test_admin_policy_and_disabled_feature_are_preserved(self):
        admin_app = build_supervisor_review_app(
            FakeSupervisorSession(),
            user_id=1,
            is_admin=True,
        )
        self._start(self._orchestration_patches(allowed_user_ids=""))
        with TestClient(admin_app) as client:
            allowed = client.get(
                "/api/v1/filings/jobs/101/supervisor-orchestration/plan"
            )
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.json()["authorization_source"], "admin")

        disabled_app = build_supervisor_review_app(
            FakeSupervisorSession(),
            user_id=1,
            is_admin=True,
        )
        with patch.object(
            filings.settings,
            "supervisor_orchestration_enabled",
            False,
        ), TestClient(disabled_app) as client:
            disabled = client.get(
                "/api/v1/filings/jobs/101/supervisor-orchestration/plan"
            )
        self.assertEqual(disabled.status_code, 403)

    def test_allowlisted_reviewer_must_explicitly_request_live_mode(self):
        session = FakeSupervisorSession()
        app = build_supervisor_review_app(session, user_id=1)
        fake_client = FakeLiveSupervisorClient()
        llm_config = SupervisorLLMConfig(
            enabled=True,
            provider="hf",
            api_token="unit-token",
            model_id="unit-supervisor",
        )
        with patch.object(
            filings.settings,
            "supervisor_production_live_enabled",
            True,
        ), patch.object(
            filings.settings,
            "supervisor_production_live_admin_only",
            True,
        ), patch.object(
            filings.settings,
            "supervisor_orchestration_allowed_user_ids",
            "1",
        ), patch(
            "services.supervisor_production_review.SupervisorLLMClient",
            return_value=fake_client,
        ), patch(
            "services.supervisor_production_review.SupervisorLLMConfig.from_settings",
            return_value=llm_config,
        ), TestClient(app) as client:
            response = client.post(
                "/api/v1/filings/jobs/101/supervisor-reviews/run",
                json={
                    "llm_mapping_suggestion_id": "suggestion-a",
                    "mode": "live",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source"], "live")
        self.assertEqual(len(fake_client.calls), 1)
        self.assertIsNone(session.items["item-a"].confirmed_tag_id)
        self.assertIsNone(session.items["item-a"].template_field_id)


if __name__ == "__main__":
    unittest.main()
