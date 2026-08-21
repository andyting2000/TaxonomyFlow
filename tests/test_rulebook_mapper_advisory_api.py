import json
import unittest
from datetime import datetime
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


FORBIDDEN_RESPONSE_FIELDS = {
    "auditor_xml",
    "raw_xml",
    "parsed_xml_fact",
    "parsed_xml_facts",
    "xml_facts",
    "gold_answer",
    "target_correct_qname",
    "target_correct_template_field_id",
    "evaluation_label",
    "benchmark_label",
    "confirmed_tag_id",
    "raw_prompt",
    "raw_response",
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


class FakeRulebookMapperSession:
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
            "item-unmatched": self._item(
                "item-unmatched",
                "page-a",
                "Unmatched label",
                "17",
                "Statement of Financial Position",
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


def build_rulebook_mapper_app(session, *, user_id=1, override_auth=True):
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


class RulebookMapperAdvisoryApiTests(unittest.TestCase):
    def test_disabled_flag_rejects_owned_run(self):
        session = FakeRulebookMapperSession()
        app = build_rulebook_mapper_app(session)

        with patch.object(
            filings.settings,
            "rulebook_mapper_advisory_enabled",
            False,
        ), TestClient(app) as client:
            response = client.post("/api/v1/filings/jobs/101/rulebook-mapper/run")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], filings.RULEBOOK_MAPPER_DISABLED_MESSAGE)
        session.commit.assert_not_awaited()
        session.flush.assert_not_awaited()
        self.assertEqual(session.added, [])

    def test_run_requires_authentication(self):
        session = FakeRulebookMapperSession()
        app = build_rulebook_mapper_app(session, override_auth=False)

        with patch.object(
            filings.settings,
            "rulebook_mapper_advisory_enabled",
            True,
        ), TestClient(app) as client:
            response = client.post("/api/v1/filings/jobs/101/rulebook-mapper/run")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Bearer token required")

    def test_user_cannot_run_or_read_capabilities_for_another_users_job(self):
        session = FakeRulebookMapperSession()
        app = build_rulebook_mapper_app(session, user_id=1)
        run_mock = AsyncMock()

        with patch.object(
            filings.settings,
            "rulebook_mapper_advisory_enabled",
            True,
        ), patch(
            "routers.filings.run_rulebook_mapper_advisory_for_job",
            new=run_mock,
        ), TestClient(app) as client:
            run_response = client.post("/api/v1/filings/jobs/202/rulebook-mapper/run")
            capabilities_response = client.get(
                "/api/v1/filings/jobs/202/rulebook-mapper/capabilities"
            )

        self.assertEqual(run_response.status_code, 404)
        self.assertEqual(capabilities_response.status_code, 404)
        run_mock.assert_not_awaited()

    def test_capabilities_are_read_only_and_dry_run_only(self):
        session = FakeRulebookMapperSession()
        app = build_rulebook_mapper_app(session)

        with patch.object(
            filings.settings,
            "rulebook_mapper_advisory_enabled",
            False,
        ), patch.object(
            filings.settings,
            "rulebook_mapper_advisory_allow_persistence",
            True,
        ), TestClient(app) as client:
            response = client.get("/api/v1/filings/jobs/101/rulebook-mapper/capabilities")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["enabled"])
        self.assertEqual(body["default_mode"], "dry_run")
        self.assertFalse(body["allow_persistence"])
        self.assertEqual(body["supported_modes"], ["dry_run"])
        self.assertFalse(body["safety"]["auto_apply_enabled"])
        self.assertFalse(body["safety"]["confirmed_mapping_mutation_allowed"])
        session.commit.assert_not_awaited()
        session.flush.assert_not_awaited()

    def test_enabled_run_returns_advisory_suggestions_and_summary(self):
        session = FakeRulebookMapperSession()
        app = build_rulebook_mapper_app(session)

        with patch.object(
            filings.settings,
            "rulebook_mapper_advisory_enabled",
            True,
        ), TestClient(app) as client:
            response = client.post("/api/v1/filings/jobs/101/rulebook-mapper/run")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["job_id"], 101)
        self.assertEqual(body["mode"], "dry_run")
        self.assertTrue(body["feature_enabled"])
        self.assertFalse(body["persistence_enabled"])
        self.assertEqual(body["summary"]["total_pdf_row_value_observations"], 2)
        self.assertEqual(body["summary"]["advisory_suggestions_count"], 1)
        self.assertEqual(body["summary"]["no_match_count"], 1)
        self.assertEqual(body["summary"]["safe_for_auto_apply_count"], 0)
        self.assertTrue(body["summary"]["no_suggestion_safe_for_auto_apply"])

        advisory = [
            item for item in body["suggestions"]
            if item["confidence_bucket"].startswith("advisory")
        ]
        self.assertEqual(len(advisory), 1)
        suggestion = advisory[0]
        self.assertEqual(suggestion["row_id"], "item-bank:current")
        self.assertEqual(suggestion["pdf_label"], "Bank balances")
        self.assertEqual(suggestion["normalized_label"], "bank balances")
        self.assertEqual(suggestion["suggestion_source"], "pdf_xbrl_rulebook")
        self.assertEqual(suggestion["matched_rule_id"], "18B-R0038-bank-balances-ssmt-cashandbankbalances")
        self.assertEqual(suggestion["predicted_qname"], "ssmt:CashAndBankBalances")
        self.assertTrue(suggestion["requires_human_review"])
        self.assertFalse(suggestion["safe_for_auto_apply"])

        for suggestion in body["suggestions"]:
            self.assertTrue(suggestion["requires_human_review"])
            self.assertFalse(suggestion["safe_for_auto_apply"])

    def test_response_excludes_forbidden_leakage_fields(self):
        session = FakeRulebookMapperSession()
        app = build_rulebook_mapper_app(session)

        with patch.object(
            filings.settings,
            "rulebook_mapper_advisory_enabled",
            True,
        ), TestClient(app) as client:
            response = client.post("/api/v1/filings/jobs/101/rulebook-mapper/run")

        self.assertEqual(response.status_code, 200)
        encoded = json.dumps(response.json(), sort_keys=True)
        for field in FORBIDDEN_RESPONSE_FIELDS:
            self.assertNotIn(field, encoded)

    def test_run_does_not_mutate_extracted_rows_ai_suggestions_or_confirmed_mapping(self):
        session = FakeRulebookMapperSession()
        before_item = item_state(session.items["item-bank"])
        before_suggestion_statuses = {
            key: suggestion.status for key, suggestion in session.suggestions.items()
        }
        app = build_rulebook_mapper_app(session)

        with patch.object(
            filings.settings,
            "rulebook_mapper_advisory_enabled",
            True,
        ), TestClient(app) as client:
            response = client.post("/api/v1/filings/jobs/101/rulebook-mapper/run")

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

    def test_no_match_cases_return_safe_summary(self):
        session = FakeRulebookMapperSession()
        session.items = {
            "item-unmatched": session.items["item-unmatched"],
            "item-other-user": session.items["item-other-user"],
        }
        session.suggestions = {}
        session._wire_relationships()
        app = build_rulebook_mapper_app(session)

        with patch.object(
            filings.settings,
            "rulebook_mapper_advisory_enabled",
            True,
        ), TestClient(app) as client:
            response = client.post("/api/v1/filings/jobs/101/rulebook-mapper/run")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["summary"]["total_pdf_row_value_observations"], 1)
        self.assertEqual(body["summary"]["advisory_suggestions_count"], 0)
        self.assertEqual(body["summary"]["review_required_suggestions_count"], 0)
        self.assertEqual(body["summary"]["no_match_count"], 1)
        self.assertEqual(body["summary"]["safe_for_auto_apply_count"], 0)
        self.assertEqual(body["suggestions"][0]["confidence_bucket"], "no_match")
        self.assertIsNone(body["suggestions"][0]["predicted_qname"])
        self.assertFalse(body["suggestions"][0]["safe_for_auto_apply"])

    def test_no_llm_supervisor_or_qwen_call_occurs(self):
        session = FakeRulebookMapperSession()
        app = build_rulebook_mapper_app(session)

        with patch.object(
            filings.settings,
            "rulebook_mapper_advisory_enabled",
            True,
        ), patch(
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
            response = client.post("/api/v1/filings/jobs/101/rulebook-mapper/run")

        self.assertEqual(response.status_code, 200)
        llm_mock.assert_not_awaited()
        supervisor_single_mock.assert_not_awaited()
        supervisor_batch_mock.assert_not_awaited()

    def test_service_error_is_safe_when_hardened_report_is_unavailable(self):
        session = FakeRulebookMapperSession()
        app = build_rulebook_mapper_app(session)

        async def unavailable(*_args, **_kwargs):
            from services.rulebook_mapper_advisory_service import RulebookMapperAdvisoryError

            raise RulebookMapperAdvisoryError(
                "Deterministic rulebook advisory report is unavailable."
            )

        with patch.object(
            filings.settings,
            "rulebook_mapper_advisory_enabled",
            True,
        ), patch(
            "routers.filings.run_rulebook_mapper_advisory_for_job",
            new=AsyncMock(side_effect=unavailable),
        ), TestClient(app) as client:
            response = client.post("/api/v1/filings/jobs/101/rulebook-mapper/run")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"],
            "Deterministic rulebook advisory report is unavailable.",
        )
        session.commit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
