import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from database import User, get_db
from routers import filings
from security import get_current_user
from services.supervisor_llm_client import SupervisorLLMConfig
from tests.supervisor_review_fakes import (
    FakeSupervisorSession,
    supervisor_template_metadata,
    supervisor_test_playbook,
)


FORBIDDEN_RESPONSE_FIELDS = {
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
    "supervisor_payload_hash",
    "supervisor_response_hash",
    "raw_payload",
    "raw_prompt",
    "raw_response",
    "confirmed_tag_id",
}


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


def build_supervisor_review_app(session, user_id=1, is_admin=False):
    app = FastAPI()
    app.include_router(filings.router, prefix="/api/v1/filings")

    async def override_db():
        yield session

    async def override_current_user():
        return User(
            id=user_id,
            email=f"user{user_id}@example.com",
            is_admin=is_admin,
            is_active=True,
            is_deleted=False,
        )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_current_user
    return app


class SupervisorReviewApiTests(unittest.TestCase):
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

    def test_authenticated_user_can_run_list_and_get_owned_supervisor_review(self):
        session = FakeSupervisorSession()
        app = build_supervisor_review_app(session, user_id=1)

        with TestClient(app) as client:
            run_response = client.post(
                "/api/v1/filings/jobs/101/supervisor-reviews/run",
                json={"llm_mapping_suggestion_id": "suggestion-a"},
            )
            list_response = client.get("/api/v1/filings/jobs/101/supervisor-reviews")
            review_id = run_response.json()["id"]
            get_response = client.get(
                f"/api/v1/filings/jobs/101/supervisor-reviews/{review_id}"
            )

        self.assertEqual(run_response.status_code, 200)
        run_body = run_response.json()
        self.assertEqual(run_body["job_id"], 101)
        self.assertEqual(run_body["llm_mapping_suggestion_id"], "suggestion-a")
        self.assertEqual(run_body["review_status"], "completed")
        self.assertEqual(run_body["source"], "mock")
        self.assertEqual(run_body["supervisor_model_provider"], "mock")

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()), 1)
        self.assertEqual(list_response.json()[0]["id"], review_id)
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.json()["id"], review_id)

    def test_omitted_mode_remains_safe_mock_when_legacy_default_setting_changes(self):
        session = FakeSupervisorSession()
        app = build_supervisor_review_app(session, user_id=1)

        with patch.object(
            filings.settings,
            "supervisor_production_live_default_mode",
            "live",
        ), TestClient(app) as client:
            response = client.post(
                "/api/v1/filings/jobs/101/supervisor-reviews/run",
                json={"llm_mapping_suggestion_id": "suggestion-a"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source"], "mock")
        self.assertEqual(response.json()["supervisor_model_provider"], "mock")

    def test_user_cannot_access_another_users_job_reviews(self):
        session = FakeSupervisorSession()
        app = build_supervisor_review_app(session, user_id=1)

        with TestClient(app) as client:
            run_response = client.post(
                "/api/v1/filings/jobs/202/supervisor-reviews/run",
                json={"llm_mapping_suggestion_id": "suggestion-b"},
            )
            list_response = client.get("/api/v1/filings/jobs/202/supervisor-reviews")
            batch_response = client.post("/api/v1/filings/jobs/202/supervisor-reviews/run-batch")

        self.assertEqual(run_response.status_code, 404)
        self.assertEqual(list_response.status_code, 404)
        self.assertEqual(batch_response.status_code, 404)
        self.assertEqual(session.reviews, [])

    def test_live_mode_rejected_when_feature_flag_disabled(self):
        session = FakeSupervisorSession()
        app = build_supervisor_review_app(session, user_id=1)

        with patch.object(filings.settings, "supervisor_production_live_enabled", False), TestClient(app) as client:
            single_response = client.post(
                "/api/v1/filings/jobs/101/supervisor-reviews/run",
                json={"llm_mapping_suggestion_id": "suggestion-a", "mode": "live"},
            )
            batch_response = client.post(
                "/api/v1/filings/jobs/101/supervisor-reviews/run-batch",
                json={"mode": "live"},
            )

        self.assertEqual(single_response.status_code, 403)
        self.assertEqual(batch_response.status_code, 403)
        self.assertIn("Live Supervisor execution is disabled", single_response.json()["detail"])
        self.assertIn("SUPERVISOR_PRODUCTION_LIVE_ENABLED=true", single_response.json()["detail"])
        self.assertEqual(session.reviews, [])

    def test_live_mode_rejected_for_non_admin_when_admin_only_enabled(self):
        session = FakeSupervisorSession()
        app = build_supervisor_review_app(session, user_id=1, is_admin=False)

        with patch.object(filings.settings, "supervisor_production_live_enabled", True), patch.object(
            filings.settings,
            "supervisor_production_live_admin_only",
            True,
        ), TestClient(app) as client:
            response = client.post(
                "/api/v1/filings/jobs/101/supervisor-reviews/run",
                json={"llm_mapping_suggestion_id": "suggestion-a", "mode": "live"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["detail"],
            "Explicit internal reviewer authorization is required.",
        )
        self.assertEqual(session.reviews, [])

    def test_live_mode_allowed_for_admin_when_feature_flag_enabled(self):
        session = FakeSupervisorSession()
        app = build_supervisor_review_app(session, user_id=1, is_admin=True)
        fake_client = FakeLiveSupervisorClient()
        config = SupervisorLLMConfig(
            enabled=True,
            provider="hf",
            api_token="supervisor-token",
            model_id="supervisor-model",
        )

        with patch.object(filings.settings, "supervisor_production_live_enabled", True), patch.object(
            filings.settings,
            "supervisor_production_live_admin_only",
            True,
        ), patch(
            "services.supervisor_production_review.SupervisorLLMClient",
            return_value=fake_client,
        ), patch(
            "services.supervisor_production_review.SupervisorLLMConfig.from_settings",
            return_value=config,
        ), TestClient(app) as client:
            response = client.post(
                "/api/v1/filings/jobs/101/supervisor-reviews/run",
                json={"llm_mapping_suggestion_id": "suggestion-a", "mode": "live"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["source"], "live")
        self.assertEqual(body["review_status"], "completed")
        self.assertEqual(body["supervisor_model_provider"], "hf")
        self.assertEqual(body["supervisor_model_id"], "supervisor-model")
        self.assertTrue(body["supervisor_safe_to_accept"])
        self.assertEqual(len(fake_client.calls), 1)
        self.assertEqual(len(session.reviews), 1)
        self.assertNotIn("supervisor_payload_hash", body)
        self.assertNotIn("supervisor_response_hash", body)

    def test_live_mode_preserves_owned_job_isolation_for_admin(self):
        session = FakeSupervisorSession()
        app = build_supervisor_review_app(session, user_id=1, is_admin=True)
        fake_client = FakeLiveSupervisorClient()

        with patch.object(filings.settings, "supervisor_production_live_enabled", True), patch.object(
            filings.settings,
            "supervisor_production_live_admin_only",
            True,
        ), patch(
            "services.supervisor_production_review.SupervisorLLMClient",
            return_value=fake_client,
        ), TestClient(app) as client:
            response = client.post(
                "/api/v1/filings/jobs/202/supervisor-reviews/run",
                json={"llm_mapping_suggestion_id": "suggestion-b", "mode": "live"},
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(len(fake_client.calls), 0)
        self.assertEqual(session.reviews, [])

    def test_live_batch_enforces_configured_max_batch_size(self):
        session = FakeSupervisorSession()
        app = build_supervisor_review_app(session, user_id=1, is_admin=True)
        fake_client = FakeLiveSupervisorClient()

        with patch.object(filings.settings, "supervisor_production_live_enabled", True), patch.object(
            filings.settings,
            "supervisor_production_live_admin_only",
            True,
        ), patch.object(
            filings.settings,
            "supervisor_production_live_max_batch_size",
            1,
        ), patch(
            "services.supervisor_production_review.SupervisorLLMClient",
            return_value=fake_client,
        ), TestClient(app) as client:
            response = client.post(
                "/api/v1/filings/jobs/101/supervisor-reviews/run-batch",
                json={"mode": "live"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Live Supervisor batch size 2 exceeds maximum 1", response.json()["detail"])
        self.assertEqual(len(fake_client.calls), 0)
        self.assertEqual(session.reviews, [])

    def test_single_run_creates_only_supervisor_review_and_no_mapping_mutation(self):
        session = FakeSupervisorSession()
        app = build_supervisor_review_app(session, user_id=1)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/filings/jobs/101/supervisor-reviews/run",
                json={"llm_mapping_suggestion_id": "suggestion-a"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(session.reviews), 1)
        item = session.items["item-a"]
        suggestion = session.suggestions["suggestion-a"]
        self.assertIsNone(item.template_field_id)
        self.assertIsNone(item.confirmed_tag_id)
        self.assertFalse(item.is_reviewed)
        self.assertEqual(suggestion.status, "suggested")

    def test_mapper_rejection_remains_reviewable(self):
        session = FakeSupervisorSession()
        session.suggestions["suggestion-a"].status = "rejected"
        app = build_supervisor_review_app(session, user_id=1)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/filings/jobs/101/supervisor-reviews/run",
                json={"llm_mapping_suggestion_id": "suggestion-a"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(session.reviews), 1)
        self.assertEqual(session.suggestions["suggestion-a"].status, "rejected")

    def test_human_terminal_suggestions_cannot_be_reviewed(self):
        for terminal_status in ("accepted", "ignored"):
            with self.subTest(status=terminal_status):
                session = FakeSupervisorSession()
                session.suggestions["suggestion-a"].status = terminal_status
                app = build_supervisor_review_app(session, user_id=1)

                with TestClient(app) as client:
                    response = client.post(
                        "/api/v1/filings/jobs/101/supervisor-reviews/run",
                        json={"llm_mapping_suggestion_id": "suggestion-a"},
                    )

                self.assertEqual(response.status_code, 409)
                self.assertIn("terminal", response.json()["detail"].lower())
                self.assertEqual(session.reviews, [])

    def test_batch_run_creates_mock_reviews_for_all_owned_job_suggestions(self):
        session = FakeSupervisorSession()
        app = build_supervisor_review_app(session, user_id=1)

        with TestClient(app) as client:
            response = client.post("/api/v1/filings/jobs/101/supervisor-reviews/run-batch")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["job_id"], 101)
        self.assertEqual(body["mode"], "mock")
        self.assertFalse(body["force_refresh"])
        self.assertEqual(body["reviews_created"], 2)
        self.assertEqual(body["reviews_reused"], 0)
        self.assertEqual(len(body["reviews"]), 2)
        self.assertEqual({review["job_id"] for review in body["reviews"]}, {101})
        self.assertEqual(len(session.reviews), 2)

    def test_batch_run_can_be_bounded_to_selected_owned_suggestions(self):
        session = FakeSupervisorSession()
        app = build_supervisor_review_app(session, user_id=1)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/filings/jobs/101/supervisor-reviews/run-batch",
                json={
                    "mode": "mock",
                    "suggestion_ids": ["suggestion-cashflow"],
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["reviews_created"], 1)
        self.assertEqual(body["reviews_reused"], 0)
        self.assertEqual(
            [review["llm_mapping_suggestion_id"] for review in body["reviews"]],
            ["suggestion-cashflow"],
        )
        self.assertEqual(
            [review.llm_mapping_suggestion_id for review in session.reviews],
            ["suggestion-cashflow"],
        )

    def test_existing_review_reused_and_force_refresh_creates_new_attempt(self):
        session = FakeSupervisorSession()
        app = build_supervisor_review_app(session, user_id=1)

        with TestClient(app) as client:
            first = client.post(
                "/api/v1/filings/jobs/101/supervisor-reviews/run",
                json={"llm_mapping_suggestion_id": "suggestion-a"},
            )
            second = client.post(
                "/api/v1/filings/jobs/101/supervisor-reviews/run",
                json={"llm_mapping_suggestion_id": "suggestion-a"},
            )
            third = client.post(
                "/api/v1/filings/jobs/101/supervisor-reviews/run",
                json={"llm_mapping_suggestion_id": "suggestion-a", "force_refresh": True},
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(third.status_code, 200)
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertNotEqual(first.json()["id"], third.json()["id"])
        self.assertEqual(len(session.reviews), 2)
        self.assertFalse(session.reviews[0].is_latest)
        self.assertTrue(session.reviews[1].is_latest)
        self.assertEqual(session.reviews[1].review_attempt, 2)

    def test_response_serializer_excludes_sensitive_fields(self):
        session = FakeSupervisorSession()
        app = build_supervisor_review_app(session, user_id=1)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/filings/jobs/101/supervisor-reviews/run",
                json={"ai_suggestion_id": "suggestion-a"},
            )

        self.assertEqual(response.status_code, 200)
        text = str(response.json()).lower()
        self.assertFalse(FORBIDDEN_RESPONSE_FIELDS & set(response.json().keys()))
        for forbidden in FORBIDDEN_RESPONSE_FIELDS:
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
