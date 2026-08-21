import asyncio
import json
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from database import (
    ExtractedDataItem,
    FilingJob,
    FinancialStatementPage,
    LLMMappingSuggestion,
    User,
    get_db,
)
from routers import filings
from security import get_current_user
from services.ranked_candidate_advisory_service import (
    RankedCandidateAdvisoryConfig,
    RankedCandidateAdvisoryError,
    run_ranked_candidate_advisory_for_job,
)


UNSAFE_ACTIONS = {
    "accept",
    "apply",
    "confirm",
    "auto_apply",
    "auto_accept",
    "set_confirmed_tag_id",
}


class DummyScalars:
    def __init__(self, values):
        self._values = values

    def unique(self):
        return self

    def all(self):
        return self._values


class DummyResult:
    def __init__(self, *, one=None, many=None):
        self._one = one
        self._many = many or []

    def scalar_one_or_none(self):
        return self._one

    def scalars(self):
        return DummyScalars(self._many)


class FakeRankedCandidateSession:
    def __init__(self):
        self.commit = AsyncMock()
        self.flush = AsyncMock()
        self.rollback = AsyncMock()
        self.added = []
        self.deleted = []
        self.jobs = {
            101: self._job(101, 1, "Owner A"),
            202: self._job(202, 2, "Owner B"),
        }
        self.pages = {
            "page-a": self._page("page-a", 101, 1),
            "page-b": self._page("page-b", 202, 1),
        }
        self.items = {
            "item-bank": self._item(
                "item-bank",
                "page-a",
                "Bank balances",
                "100",
                "Statement of Financial Position",
            ),
            "item-revenue": self._item(
                "item-revenue",
                "page-a",
                "Revenue",
                "250",
                "Statement of Comprehensive Income",
            ),
            "item-other-user": self._item(
                "item-other-user",
                "page-b",
                "Bank balances",
                "200",
                "Statement of Financial Position",
            ),
        }
        self.suggestions = {
            "suggestion-existing": self._suggestion(
                "suggestion-existing",
                101,
                "item-bank",
            )
        }
        self._wire_relationships()

    def _job(self, job_id, user_id, company_name):
        return FilingJob(
            id=job_id,
            user_id=user_id,
            company_name=company_name,
            registration_number=f"REG-{job_id}",
            financial_year_end=datetime(2026, 12, 31),
            source_pdf_path=f"uploads/pdfs/{job_id}.pdf",
            status="REVIEW",
            ai_mapping_status="completed",
            ai_mapping_last_error_message=None,
            uploaded_at=datetime(2026, 1, 1),
        )

    def _page(self, page_id, job_id, page_number):
        return FinancialStatementPage(
            id=page_id,
            job_id=job_id,
            page_number=page_number,
            image_path=f"uploads/pages/{page_id}.png",
        )

    def _item(self, item_id, page_id, label, value, statement_type):
        return ExtractedDataItem(
            id=item_id,
            page_id=page_id,
            extracted_label=label,
            extracted_value=value,
            financial_year=2026,
            value_previous_year=None,
            financial_year_previous=None,
            statement_type=statement_type,
            template_field_id=None,
            template_position=None,
            is_required_field=False,
            is_reviewed=False,
            confirmed_tag_id=None,
        )

    def _suggestion(self, suggestion_id, job_id, item_id):
        return LLMMappingSuggestion(
            id=suggestion_id,
            job_id=job_id,
            extracted_data_item_id=item_id,
            suggested_template_field_id="ifrs-smes:CashAndCashEquivalents",
            confidence=0.91,
            reason="Existing AI suggestion.",
            ranked_candidates_json="[]",
            status="suggested",
            model_id="unit-qwen",
            created_at=datetime(2026, 1, 2),
            diagnostic_json="{}",
        )

    def _wire_relationships(self):
        for page in self.pages.values():
            page.job = self.jobs[page.job_id]
            page.extracted_items = [
                item for item in self.items.values() if item.page_id == page.id
            ]
        for item in self.items.values():
            item.page = self.pages[item.page_id]
            item.llm_mapping_suggestions = [
                suggestion
                for suggestion in self.suggestions.values()
                if suggestion.extracted_data_item_id == item.id
            ]
        for suggestion in self.suggestions.values():
            suggestion.job = self.jobs[suggestion.job_id]
            suggestion.extracted_data_item = self.items[suggestion.extracted_data_item_id]
        for job in self.jobs.values():
            job.pages = [page for page in self.pages.values() if page.job_id == job.id]
            job.llm_mapping_suggestions = [
                suggestion
                for suggestion in self.suggestions.values()
                if suggestion.job_id == job.id
            ]

    def add(self, value):
        self.added.append(value)

    async def delete(self, value):
        self.deleted.append(value)

    async def execute(self, statement):
        sql = str(statement)
        params = statement.compile().params
        if "FROM filing_jobs" in sql:
            return self._execute_job_query(params)
        if "FROM extracted_data_items" in sql:
            return self._execute_item_query(params)
        if "FROM llm_mapping_suggestions" in sql:
            return self._execute_suggestion_query(params)
        return DummyResult(many=[])

    def _execute_job_query(self, params):
        job_id = self._param(params, "id")
        user_id = self._param(params, "user_id")
        job = self.jobs.get(job_id)
        if not job or (user_id is not None and job.user_id != user_id):
            return DummyResult(one=None)
        return DummyResult(one=job)

    def _execute_item_query(self, params):
        item_id = self._param(params, "id")
        job_id = self._param(params, "job_id")
        items = list(self.items.values())
        if item_id is not None:
            items = [item for item in items if item.id == item_id]
        if job_id is not None:
            items = [item for item in items if self.pages[item.page_id].job_id == job_id]
        return DummyResult(one=items[0] if items else None, many=items)

    def _execute_suggestion_query(self, params):
        job_id = self._param(params, "job_id")
        suggestions = list(self.suggestions.values())
        if job_id is not None:
            suggestions = [
                suggestion for suggestion in suggestions if suggestion.job_id == job_id
            ]
        return DummyResult(one=suggestions[0] if suggestions else None, many=suggestions)

    def _param(self, params, prefix):
        for key, value in params.items():
            if key.startswith(prefix):
                return value
        return None


def build_ranked_candidate_app(session, *, user_id=1, override_auth=True):
    app = FastAPI()
    app.include_router(filings.router, prefix="/api/v1/filings")

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    if override_auth:
        async def override_current_user():
            return User(
                id=user_id,
                email=f"user{user_id}@example.com",
                is_admin=False,
                is_active=True,
                is_deleted=False,
            )

        app.dependency_overrides[get_current_user] = override_current_user

    return app


def item_state(item):
    return {
        "template_field_id": item.template_field_id,
        "statement_type": item.statement_type,
        "template_position": item.template_position,
        "is_required_field": item.is_required_field,
        "is_reviewed": item.is_reviewed,
        "confirmed_tag_id": item.confirmed_tag_id,
    }


class RankedCandidateAdvisoryApiTests(unittest.TestCase):
    def _enabled_patches(self):
        return (
            patch.object(filings.settings, "ranked_candidates_advisory_enabled", True),
            patch.object(filings.settings, "ranked_candidates_advisory_admin_only", False),
            patch.object(filings.settings, "ranked_candidates_advisory_default_mode", "dry_run"),
            patch.object(filings.settings, "ranked_candidates_advisory_allow_persistence", False),
            patch.object(filings.settings, "ranked_candidates_advisory_default_profile", "balanced"),
            patch.object(filings.settings, "ranked_candidates_advisory_max_rows", 1000),
            patch.object(filings.settings, "ranked_candidates_advisory_max_candidates_per_row", 5),
        )

    def test_capabilities_endpoint_returns_disabled_by_default_status(self):
        session = FakeRankedCandidateSession()
        app = build_ranked_candidate_app(session)

        with patch.object(
            filings.settings,
            "ranked_candidates_advisory_enabled",
            False,
        ), patch.object(
            filings.settings,
            "ranked_candidates_advisory_default_mode",
            "persisted_later",
        ), patch.object(
            filings.settings,
            "ranked_candidates_advisory_allow_persistence",
            True,
        ), TestClient(app) as client:
            response = client.get(
                "/api/v1/filings/jobs/101/ranked-candidates/capabilities"
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["enabled"])
        self.assertEqual(body["default_mode"], "dry_run")
        self.assertFalse(body["allow_persistence"])
        self.assertEqual(body["default_profile"], "balanced")
        self.assertIn("balanced", body["supported_profiles"])
        self.assertEqual(body["supported_modes"], ["dry_run"])
        self.assertEqual(
            set(body["supported_actions"]),
            {"review_candidate", "keep_for_human_review", "no_candidate", "blocked"},
        )
        self.assertFalse(body["safety"]["auto_apply_enabled"])
        self.assertFalse(body["safety"]["persistence_enabled"])
        self.assertFalse(body["safety"]["confirmed_tag_id_mutation_allowed"])
        session.commit.assert_not_awaited()
        session.flush.assert_not_awaited()

    def test_run_endpoint_fails_closed_when_feature_disabled(self):
        session = FakeRankedCandidateSession()
        app = build_ranked_candidate_app(session)

        with patch.object(
            filings.settings,
            "ranked_candidates_advisory_enabled",
            False,
        ), TestClient(app) as client:
            response = client.post("/api/v1/filings/jobs/101/ranked-candidates/run")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["detail"],
            filings.RANKED_CANDIDATE_ADVISORY_DISABLED_MESSAGE,
        )
        session.commit.assert_not_awaited()
        session.flush.assert_not_awaited()
        self.assertEqual(session.added, [])

    def test_run_requires_authentication(self):
        session = FakeRankedCandidateSession()
        app = build_ranked_candidate_app(session, override_auth=False)

        with patch.object(
            filings.settings,
            "ranked_candidates_advisory_enabled",
            True,
        ), TestClient(app) as client:
            response = client.post("/api/v1/filings/jobs/101/ranked-candidates/run")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Bearer token required")

    def test_user_cannot_run_or_read_capabilities_for_another_users_job(self):
        session = FakeRankedCandidateSession()
        app = build_ranked_candidate_app(session, user_id=1)
        run_mock = AsyncMock()

        with patch.object(
            filings.settings,
            "ranked_candidates_advisory_enabled",
            True,
        ), patch(
            "routers.filings.run_ranked_candidate_advisory_for_job",
            new=run_mock,
        ), TestClient(app) as client:
            run_response = client.post("/api/v1/filings/jobs/202/ranked-candidates/run")
            capabilities_response = client.get(
                "/api/v1/filings/jobs/202/ranked-candidates/capabilities"
            )

        self.assertEqual(run_response.status_code, 404)
        self.assertEqual(capabilities_response.status_code, 404)
        run_mock.assert_not_awaited()

    def test_admin_only_gate_is_enforced_when_feature_is_enabled(self):
        session = FakeRankedCandidateSession()
        app = build_ranked_candidate_app(session)
        run_mock = AsyncMock()

        with patch.object(
            filings.settings,
            "ranked_candidates_advisory_enabled",
            True,
        ), patch.object(
            filings.settings,
            "ranked_candidates_advisory_admin_only",
            True,
        ), patch(
            "routers.filings.run_ranked_candidate_advisory_for_job",
            new=run_mock,
        ), TestClient(app) as client:
            response = client.post("/api/v1/filings/jobs/101/ranked-candidates/run")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["detail"],
            "Admin access required for ranked candidate advisory generation.",
        )
        run_mock.assert_not_awaited()

    def test_enabled_run_returns_dry_run_ranked_candidates_and_safety_counters(self):
        session = FakeRankedCandidateSession()
        app = build_ranked_candidate_app(session)

        patches = self._enabled_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], TestClient(app) as client:
            response = client.post(
                "/api/v1/filings/jobs/101/ranked-candidates/run",
                json={"max_candidates_per_row": 1},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["job_id"], 101)
        self.assertEqual(body["mode"], "dry_run")
        self.assertEqual(body["profile"], "balanced")
        self.assertEqual(body["candidate_generation_status"], "completed")
        self.assertEqual(body["total_rows"], 2)
        self.assertLessEqual(body["rows_with_candidates"], body["total_rows"])
        self.assertGreater(sum(len(row["candidates"]) for row in body["rows"]), 0)
        self.assertEqual(body["safety"]["safe_for_auto_apply_count"], 0)
        self.assertEqual(body["safety"]["confirmed_tag_id_mutations"], 0)
        self.assertEqual(body["safety"]["final_mapping_mutations"], 0)
        self.assertEqual(body["safety"]["persistence_writes"], 0)
        self.assertEqual(body["safety"]["ai_suggestion_table_writes"], 0)
        self.assertEqual(body["safety"]["external_calls"], 0)
        self.assertEqual(body["safety"]["xbrl_generation_count"], 0)
        self.assertEqual(body["safety"]["arelle_runs"], 0)
        self.assertTrue(body["safety"]["no_auto_apply_guarantee"])

        for row in body["rows"]:
            self.assertLessEqual(len(row["candidates"]), 1)
            for candidate in row["candidates"]:
                self.assertTrue(candidate["requires_human_review"])
                self.assertFalse(candidate["safe_for_auto_apply"])
                self.assertNotIn(candidate["recommended_action"], UNSAFE_ACTIONS)
                self.assertEqual(candidate["profile"], "balanced")
                self.assertEqual(candidate["calibration_version"], "18F-B-balanced")

        rows_json = json.dumps(body["rows"], sort_keys=True)
        self.assertNotIn("confirmed_tag_id", rows_json)
        self.assertNotIn("final_mapping_update", rows_json)
        self.assertNotIn("target_correct", rows_json)
        session.commit.assert_not_awaited()
        session.flush.assert_not_awaited()

    def test_enabled_capabilities_to_dry_run_smoke_flow_is_read_only(self):
        """Exercise the test-only capability -> dry-run loop without persistence."""

        session = FakeRankedCandidateSession()
        app = build_ranked_candidate_app(session)
        patches = self._enabled_patches()

        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], TestClient(app) as client:
            capabilities_response = client.get(
                "/api/v1/filings/jobs/101/ranked-candidates/capabilities"
            )
            run_response = client.post(
                "/api/v1/filings/jobs/101/ranked-candidates/run",
                json={
                    "mode": "dry_run",
                    "profile": "balanced",
                    "max_candidates_per_row": 1,
                },
            )

        self.assertEqual(capabilities_response.status_code, 200)
        capabilities = capabilities_response.json()
        self.assertTrue(capabilities["enabled"])
        self.assertEqual(capabilities["default_mode"], "dry_run")
        self.assertFalse(capabilities["allow_persistence"])
        self.assertEqual(capabilities["default_profile"], "balanced")
        self.assertEqual(capabilities["max_candidates_per_row"], 5)

        self.assertEqual(run_response.status_code, 200)
        body = run_response.json()
        self.assertEqual(body["mode"], "dry_run")
        self.assertEqual(body["profile"], "balanced")
        self.assertEqual(body["candidate_generation_status"], "completed")
        self.assertEqual(body["safety"]["safe_for_auto_apply_count"], 0)
        self.assertEqual(body["safety"]["confirmed_tag_id_mutations"], 0)
        self.assertEqual(body["safety"]["final_mapping_mutations"], 0)
        self.assertEqual(body["safety"]["persistence_writes"], 0)
        self.assertTrue(all(
            candidate["requires_human_review"] and not candidate["safe_for_auto_apply"]
            for row in body["rows"]
            for candidate in row["candidates"]
        ))
        session.commit.assert_not_awaited()
        session.flush.assert_not_awaited()
        self.assertEqual(session.added, [])

    def test_run_rejects_persistence_mode(self):
        session = FakeRankedCandidateSession()
        app = build_ranked_candidate_app(session)

        patches = self._enabled_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], TestClient(app) as client:
            response = client.post(
                "/api/v1/filings/jobs/101/ranked-candidates/run",
                json={"mode": "persisted_later"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("only supports dry_run mode", response.json()["detail"])

    def test_run_rejects_invalid_profile(self):
        session = FakeRankedCandidateSession()
        app = build_ranked_candidate_app(session)

        patches = self._enabled_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], TestClient(app) as client:
            response = client.post(
                "/api/v1/filings/jobs/101/ranked-candidates/run",
                json={"profile": "unsafe"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Unknown ranked candidate profile: unsafe", response.json()["detail"])

    def test_run_rejects_requested_caps_above_configured_limits(self):
        session = FakeRankedCandidateSession()
        app = build_ranked_candidate_app(session)

        with patch.object(
            filings.settings,
            "ranked_candidates_advisory_enabled",
            True,
        ), patch.object(
            filings.settings,
            "ranked_candidates_advisory_admin_only",
            False,
        ), patch.object(
            filings.settings,
            "ranked_candidates_advisory_max_rows",
            1,
        ), patch.object(
            filings.settings,
            "ranked_candidates_advisory_max_candidates_per_row",
            1,
        ), TestClient(app) as client:
            response = client.post(
                "/api/v1/filings/jobs/101/ranked-candidates/run",
                json={"max_rows": 2, "max_candidates_per_row": 1},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("max_rows exceeds configured limit", response.json()["detail"])

    def test_run_does_not_mutate_extracted_rows_ai_suggestions_or_final_mapping(self):
        session = FakeRankedCandidateSession()
        before_item = item_state(session.items["item-bank"])
        before_suggestion_statuses = {
            key: suggestion.status for key, suggestion in session.suggestions.items()
        }
        app = build_ranked_candidate_app(session)

        patches = self._enabled_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], TestClient(app) as client:
            response = client.post("/api/v1/filings/jobs/101/ranked-candidates/run")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(item_state(session.items["item-bank"]), before_item)
        self.assertEqual(
            {
                key: suggestion.status
                for key, suggestion in session.suggestions.items()
            },
            before_suggestion_statuses,
        )
        self.assertIsNone(session.items["item-bank"].confirmed_tag_id)
        self.assertEqual(session.added, [])
        self.assertEqual(session.deleted, [])
        session.commit.assert_not_awaited()
        session.flush.assert_not_awaited()
        session.rollback.assert_not_awaited()

    def test_missing_local_artifacts_fail_safely(self):
        session = FakeRankedCandidateSession()
        config = RankedCandidateAdvisoryConfig(enabled=True, admin_only=False)

        with self.assertRaisesRegex(
            RankedCandidateAdvisoryError,
            "taxonomy metadata is unavailable",
        ):
            asyncio.run(
                run_ranked_candidate_advisory_for_job(
                    session,
                    job=session.jobs[101],
                    config=config,
                    taxonomy_metadata_path=Path("reports/does_not_exist_18f_d.json"),
                )
            )

        session.commit.assert_not_awaited()
        session.flush.assert_not_awaited()

    def test_no_llm_supervisor_qwen_or_external_route_call_occurs(self):
        session = FakeRankedCandidateSession()
        app = build_ranked_candidate_app(session)

        patches = self._enabled_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patch(
            "routers.filings.run_llm_mapping_for_job",
            new=AsyncMock(side_effect=AssertionError("LLM mapper called")),
        ) as llm_mock, patch(
            "routers.filings.run_supervisor_review_for_suggestion",
            new=AsyncMock(side_effect=AssertionError("Supervisor single called")),
        ) as supervisor_single_mock, patch(
            "routers.filings.run_supervisor_reviews_for_job",
            new=AsyncMock(side_effect=AssertionError("Supervisor batch called")),
        ) as supervisor_batch_mock, patch(
            "routers.filings.HuggingFaceQwenMappingClient",
            side_effect=AssertionError("Qwen client constructed"),
        ), TestClient(app) as client:
            response = client.post("/api/v1/filings/jobs/101/ranked-candidates/run")

        self.assertEqual(response.status_code, 200)
        llm_mock.assert_not_awaited()
        supervisor_single_mock.assert_not_awaited()
        supervisor_batch_mock.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
