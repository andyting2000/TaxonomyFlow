import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
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


class DummyScalars:
    def __init__(self, values):
        self._values = values

    def unique(self):
        return self

    def all(self):
        return self._values


class DummyResult:
    def __init__(self, *, one=None, many=None, scalar_value=None, first_value=None):
        self._one = one
        self._many = many or []
        self._scalar_value = scalar_value
        self._first_value = first_value

    def scalar_one_or_none(self):
        return self._one

    def scalar(self):
        return self._scalar_value

    def scalars(self):
        return DummyScalars(self._many)

    def first(self):
        return self._first_value


class FakeIsolationSession:
    def __init__(self):
        self.deleted = []
        self.flush = AsyncMock()
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

        self.jobs = {
            101: self._job(101, 1, "Owner A"),
            202: self._job(202, 2, "Owner B"),
            303: self._job(303, None, "Legacy Null Owner"),
        }
        self.pages = {
            "page-a": self._page("page-a", 101, 1, "uploads/pages/a.png"),
            "page-b": self._page("page-b", 202, 1, "uploads/pages/b.png"),
            "page-legacy": self._page("page-legacy", 303, 1, "uploads/pages/legacy.png"),
        }
        self.items = {
            "item-a": self._item("item-a", "page-a", "Cash", "100"),
            "item-b": self._item("item-b", "page-b", "Revenue", "200"),
            "item-legacy": self._item("item-legacy", "page-legacy", "Assets", "300"),
        }
        self.suggestions = {
            "suggestion-a": self._suggestion(
                "suggestion-a",
                101,
                "item-a",
                "ifrs-smes:CashAndCashEquivalents",
                "suggested",
            ),
            "suggestion-b": self._suggestion(
                "suggestion-b",
                202,
                "item-b",
                "ifrs-smes:Revenue",
                "suggested",
            ),
        }
        for page in self.pages.values():
            page.extracted_items = [
                item for item in self.items.values() if item.page_id == page.id
            ]
            page.job = self.jobs[page.job_id]
        for item in self.items.values():
            item.page = self.pages[item.page_id]
            item.llm_mapping_suggestions = [
                suggestion
                for suggestion in self.suggestions.values()
                if suggestion.extracted_data_item_id == item.id
            ]
        for suggestion in self.suggestions.values():
            suggestion.extracted_data_item = self.items[suggestion.extracted_data_item_id]
            suggestion.job = self.jobs[suggestion.job_id]
        for job in self.jobs.values():
            job.pages = [page for page in self.pages.values() if page.job_id == job.id]
            job.llm_mapping_suggestions = [
                suggestion
                for suggestion in self.suggestions.values()
                if suggestion.job_id == job.id
            ]

    def _job(self, job_id, user_id, company_name):
        return FilingJob(
            id=job_id,
            user_id=user_id,
            company_name=company_name,
            registration_number=f"REG-{job_id}",
            financial_year_end=datetime(2026, 12, 31),
            source_pdf_path=f"uploads/pdfs/{job_id}.pdf",
            status="REVIEW",
            ai_mapping_status="not_started",
            ai_mapping_last_error_message=None,
            uploaded_at=datetime(2026, 1, 1),
        )

    def _page(self, page_id, job_id, page_number, image_path):
        return FinancialStatementPage(
            id=page_id,
            job_id=job_id,
            page_number=page_number,
            image_path=image_path,
        )

    def _item(self, item_id, page_id, label, value):
        return ExtractedDataItem(
            id=item_id,
            page_id=page_id,
            extracted_label=label,
            extracted_value=value,
            financial_year=2026,
            is_reviewed=False,
            confirmed_tag_id=None,
        )

    def _suggestion(self, suggestion_id, job_id, item_id, template_field_id, status):
        return LLMMappingSuggestion(
            id=suggestion_id,
            job_id=job_id,
            extracted_data_item_id=item_id,
            suggested_template_field_id=template_field_id,
            confidence=0.97,
            reason="AI selected this provided candidate.",
            ranked_candidates_json=(
                f'[{{"template_field_id": "{template_field_id}", '
                '"confidence": 0.97, "reason": "Provided candidate."}]'
            ),
            status=status,
            model_id="unit-qwen",
            created_at=datetime(2026, 1, 2),
            diagnostic_json=(
                '{"prompt_mode": "fewshot_guarded", "fewshot_examples_count": 2, '
                '"fewshot_example_ids": ["case_001:row"], '
                '"fewshot_source_case_ids": ["case_001"], "candidate_count": 3, '
                '"suggestion": {"requires_human_confirmation": true}}'
            ),
        )

    def add(self, value):
        if isinstance(value, ExtractedDataItem):
            self.items[value.id] = value
        elif isinstance(value, FilingJob):
            self.jobs[value.id] = value
        elif isinstance(value, LLMMappingSuggestion):
            self.suggestions[value.id] = value

    async def delete(self, value):
        self.deleted.append(value)

    async def execute(self, statement):
        sql = str(statement)
        params = statement.compile().params

        if "FROM filing_jobs" in sql and "count(" not in sql:
            return self._execute_filing_job_query(sql, params)
        if "FROM llm_mapping_suggestions" in sql:
            return self._execute_suggestion_query(sql, params)
        if "FROM financial_statement_pages" in sql:
            return self._execute_page_query(sql, params)
        if "FROM extracted_data_items" in sql:
            return self._execute_item_query(sql, params)

        return DummyResult(many=[], scalar_value=0, first_value=SimpleNamespace(total=0, reviewed=0))

    def _execute_filing_job_query(self, sql, params):
        user_id = self._param(params, "user_id")
        job_id = self._param(params, "id")
        status = self._param(params, "status")

        if job_id is not None:
            job = self.jobs.get(job_id)
            if not job:
                return DummyResult(one=None)
            if user_id is not None and job.user_id != user_id:
                return DummyResult(one=None)
            return DummyResult(one=job)

        jobs = list(self.jobs.values())
        if user_id is not None:
            jobs = [job for job in jobs if job.user_id == user_id]
        if status is not None:
            jobs = [job for job in jobs if job.status == status]
        return DummyResult(many=jobs)

    def _execute_page_query(self, sql, params):
        user_id = self._param(params, "user_id")
        page_id = self._param(params, "id")
        job_id = self._param(params, "job_id")
        page_number = self._param(params, "page_number")

        pages = list(self.pages.values())
        if page_id is not None:
            pages = [page for page in pages if page.id == page_id]
        if job_id is not None:
            pages = [page for page in pages if page.job_id == job_id]
        if page_number is not None:
            pages = [page for page in pages if page.page_number == page_number]
        if user_id is not None:
            pages = [page for page in pages if self.jobs[page.job_id].user_id == user_id]

        return DummyResult(one=pages[0] if pages else None, many=pages)

    def _execute_item_query(self, sql, params):
        user_id = self._param(params, "user_id")
        item_id = self._param(params, "id")
        job_id = self._param(params, "job_id")

        items = list(self.items.values())
        if item_id is not None:
            items = [item for item in items if item.id == item_id]
        if job_id is not None:
            items = [item for item in items if self.pages[item.page_id].job_id == job_id]
        if user_id is not None:
            items = [
                item for item in items
                if self.jobs[self.pages[item.page_id].job_id].user_id == user_id
            ]

        if "count(" in sql:
            return DummyResult(scalar_value=len(items))
        return DummyResult(one=items[0] if items else None, many=items)

    def _execute_suggestion_query(self, sql, params):
        suggestion_id = self._param(params, "id")
        item_id = self._param(params, "extracted_data_item_id")
        job_id = self._param(params, "job_id")

        suggestions = list(self.suggestions.values())
        if suggestion_id is not None:
            suggestions = [suggestion for suggestion in suggestions if suggestion.id == suggestion_id]
        if item_id is not None:
            suggestions = [
                suggestion
                for suggestion in suggestions
                if suggestion.extracted_data_item_id == item_id
            ]
        if job_id is not None:
            suggestions = [suggestion for suggestion in suggestions if suggestion.job_id == job_id]

        for suggestion in suggestions:
            suggestion.extracted_data_item = self.items[suggestion.extracted_data_item_id]
            suggestion.job = self.jobs[suggestion.job_id]

        return DummyResult(one=suggestions[0] if suggestions else None, many=suggestions)

    def _param(self, params, prefix):
        for key, value in params.items():
            if key.startswith(prefix):
                return value
        return None


def build_isolation_app(session, user_id=1, *, is_admin=False):
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
        )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_current_user
    return app


class FilingUserIsolationTests(unittest.TestCase):
    def test_admin_user_is_blocked_from_filing_workspace(self):
        session = FakeIsolationSession()
        app = build_isolation_app(session, user_id=1, is_admin=True)

        with TestClient(app) as client:
            list_response = client.get("/api/v1/filings/jobs")
            detail_response = client.get("/api/v1/filings/jobs/101")

        self.assertEqual(list_response.status_code, 403)
        self.assertEqual(detail_response.status_code, 403)
        self.assertEqual(
            list_response.json()["detail"],
            "Admin accounts cannot access the filing workspace.",
        )

    def test_job_listing_excludes_other_users_and_legacy_null_owner_jobs(self):
        session = FakeIsolationSession()
        app = build_isolation_app(session, user_id=1)

        with TestClient(app) as client:
            response = client.get("/api/v1/filings/jobs")

        self.assertEqual(response.status_code, 200)
        job_ids = [item["id"] for item in response.json()]
        self.assertEqual(job_ids, [101])

    def test_cross_user_and_legacy_job_detail_are_hidden(self):
        session = FakeIsolationSession()
        app = build_isolation_app(session, user_id=1)

        with TestClient(app) as client:
            owner_response = client.get("/api/v1/filings/jobs/101")
            cross_user_response = client.get("/api/v1/filings/jobs/202")
            legacy_response = client.get("/api/v1/filings/jobs/303")

        self.assertEqual(owner_response.status_code, 200)
        self.assertEqual(cross_user_response.status_code, 404)
        self.assertEqual(legacy_response.status_code, 404)

    def test_cross_user_pages_and_page_image_are_hidden(self):
        session = FakeIsolationSession()
        app = build_isolation_app(session, user_id=1)

        with TestClient(app) as client:
            pages_response = client.get("/api/v1/filings/jobs/202/pages")
            image_response = client.get("/api/v1/filings/jobs/202/pages/1/image")

        self.assertEqual(pages_response.status_code, 404)
        self.assertEqual(image_response.status_code, 404)

    def test_cross_user_extracted_data_read_create_and_update_are_hidden(self):
        session = FakeIsolationSession()
        app = build_isolation_app(session, user_id=1)

        with TestClient(app) as client:
            read_response = client.get("/api/v1/filings/jobs/202/extracted-data")
            create_response = client.post(
                "/api/v1/filings/extracted-data/create?page_id=page-b",
                json={
                    "extracted_label": "Blocked",
                    "extracted_value": "1",
                    "financial_year": 2026,
                },
            )
            update_response = client.put(
                "/api/v1/filings/extracted-data/bulk-update",
                json={"items": [{"id": "item-b", "extracted_value": "999"}]},
            )

        self.assertEqual(read_response.status_code, 404)
        self.assertEqual(create_response.status_code, 404)
        self.assertEqual(update_response.status_code, 404)

    def test_cross_user_validation_download_and_delete_are_blocked_before_side_effects(self):
        session = FakeIsolationSession()
        app = build_isolation_app(session, user_id=1)

        with (
            patch(
                "services.xbrl_validator.xbrl_validator.validate_job_for_xbrl",
                new=AsyncMock(return_value={"is_valid": True}),
            ) as validate_mock,
            patch(
                "routers.filings.generate_xbrl_for_job",
                new=AsyncMock(return_value=SimpleNamespace(success=True, content="<xbrl/>")),
            ) as generate_mock,
            TestClient(app) as client,
        ):
            validate_response = client.get("/api/v1/filings/jobs/202/validate-xbrl")
            download_response = client.get("/api/v1/filings/jobs/202/download-xbrl")
            delete_response = client.delete("/api/v1/filings/jobs/202")

        self.assertEqual(validate_response.status_code, 404)
        self.assertEqual(download_response.status_code, 404)
        self.assertEqual(delete_response.status_code, 404)
        validate_mock.assert_not_awaited()
        generate_mock.assert_not_awaited()
        self.assertEqual(session.deleted, [])

    def test_ai_mapping_suggestions_are_visible_only_for_owned_jobs(self):
        session = FakeIsolationSession()
        app = build_isolation_app(session, user_id=1)

        with TestClient(app) as client:
            owner_response = client.get("/api/v1/filings/jobs/101/ai-mapping-suggestions")
            cross_user_response = client.get("/api/v1/filings/jobs/202/ai-mapping-suggestions")

        self.assertEqual(owner_response.status_code, 200)
        body = owner_response.json()
        self.assertEqual(body["job_id"], 101)
        self.assertEqual(len(body["suggestions"]), 1)
        self.assertEqual(body["suggestions"][0]["extracted_data_item_id"], "item-a")
        self.assertEqual(body["suggestions"][0]["prompt_mode"], "fewshot_guarded")
        self.assertEqual(body["suggestions"][0]["fewshot_examples_count"], 2)
        self.assertEqual(body["suggestions"][0]["fewshot_source_case_ids"], ["case_001"])
        self.assertEqual(body["suggestions"][0]["candidate_count"], 3)
        self.assertEqual(cross_user_response.status_code, 404)

    def test_ai_mapping_suggestion_status_reports_job_state_and_counts(self):
        session = FakeIsolationSession()
        session.jobs[101].ai_mapping_status = "running"
        session.suggestions["suggestion-a"].status = "suggested"
        app = build_isolation_app(session, user_id=1)

        with TestClient(app) as client:
            response = client.get("/api/v1/filings/jobs/101/ai-mapping-suggestions/status")
            cross_user_response = client.get("/api/v1/filings/jobs/202/ai-mapping-suggestions/status")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["job_id"], 101)
        self.assertEqual(body["ai_mapping_status"], "running")
        self.assertEqual(body["suggestions_count"], 1)
        self.assertEqual(body["pending_suggestions_count"], 1)
        self.assertEqual(body["accepted_suggestions_count"], 0)
        self.assertEqual(body["rejected_suggestions_count"], 0)
        self.assertEqual(body["no_safe_mapping_count"], 0)
        self.assertEqual(body["rate_limited_rows_count"], 0)
        self.assertIsNone(body["started_at"])
        self.assertIsNone(body["finished_at"])
        self.assertEqual(cross_user_response.status_code, 404)

    def test_ai_mapping_suggestion_status_infers_completed_for_existing_suggestions(self):
        session = FakeIsolationSession()
        session.jobs[101].ai_mapping_status = "not_started"
        session.suggestions["suggestion-a"].status = "accepted"
        app = build_isolation_app(session, user_id=1)

        with TestClient(app) as client:
            response = client.get("/api/v1/filings/jobs/101/ai-mapping-suggestions/status")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["ai_mapping_status"], "completed")
        self.assertEqual(body["suggestions_count"], 1)
        self.assertEqual(body["accepted_suggestions_count"], 1)

    def test_ai_mapping_run_is_noop_while_generation_running(self):
        session = FakeIsolationSession()
        session.jobs[101].ai_mapping_status = "running"
        app = build_isolation_app(session, user_id=1)

        run_mock = AsyncMock()
        with (
            patch("routers.filings.run_llm_mapping_for_job", new=run_mock),
            patch("routers.filings.settings.llm_mapping_enabled", True),
            TestClient(app) as client,
        ):
            response = client.post("/api/v1/filings/jobs/101/ai-mapping-suggestions/run")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["run_skipped"])
        self.assertTrue(body["already_running"])
        self.assertEqual(body["status"]["ai_mapping_status"], "running")
        run_mock.assert_not_awaited()

    def test_ai_mapping_run_is_noop_when_suggestions_already_exist(self):
        session = FakeIsolationSession()
        session.jobs[101].ai_mapping_status = "completed"
        app = build_isolation_app(session, user_id=1)

        run_mock = AsyncMock()
        with (
            patch("routers.filings.run_llm_mapping_for_job", new=run_mock),
            patch("routers.filings.settings.llm_mapping_enabled", True),
            TestClient(app) as client,
        ):
            response = client.post("/api/v1/filings/jobs/101/ai-mapping-suggestions/run")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["run_skipped"])
        self.assertTrue(body["already_has_suggestions"])
        self.assertEqual(body["status"]["ai_mapping_status"], "completed")
        run_mock.assert_not_awaited()

    def test_ai_mapping_run_creates_suggestions_without_auto_applying(self):
        session = FakeIsolationSession()
        session.suggestions = {}
        for job in session.jobs.values():
            job.llm_mapping_suggestions = []
        app = build_isolation_app(session, user_id=1)

        async def fake_run(db, job_id, **_kwargs):
            db.add(
                session._suggestion(
                    "suggestion-new",
                    job_id,
                    "item-a",
                    "ifrs-smes:CashAndCashEquivalents",
                    "suggested",
                )
            )
            return {
                "summary": {
                    "suggestions_generated": 1,
                    "db_mutated_extracted_data_items": False,
                }
            }

        with (
            patch("routers.filings.run_llm_mapping_for_job", new=AsyncMock(side_effect=fake_run)),
            patch("routers.filings.settings.llm_mapping_enabled", True),
            TestClient(app) as client,
        ):
            response = client.post("/api/v1/filings/jobs/101/ai-mapping-suggestions/run")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["run_skipped"])
        self.assertEqual(body["summary"]["suggestions_generated"], 1)
        self.assertEqual(len(body["suggestions"]), 1)
        self.assertIsNone(session.items["item-a"].template_field_id)
        self.assertFalse(session.items["item-a"].is_reviewed)
        self.assertIsNone(session.items["item-a"].confirmed_tag_id)

    def test_ai_mapping_run_preserves_partial_suggestions_on_rate_limit(self):
        session = FakeIsolationSession()
        session.suggestions = {}
        for job in session.jobs.values():
            job.llm_mapping_suggestions = []
        app = build_isolation_app(session, user_id=1)

        async def fake_run(db, job_id, **_kwargs):
            db.add(
                session._suggestion(
                    "suggestion-partial",
                    job_id,
                    "item-a",
                    "ifrs-smes:CashAndCashEquivalents",
                    "suggested",
                )
            )
            raise filings.LLMMappingRateLimitError(
                rows_sent_to_llm=2,
                processed_rows=1,
                saved_suggestions=1,
                pending_rows=1,
                failed_row_id="item-b",
            )

        with (
            patch("routers.filings.run_llm_mapping_for_job", new=AsyncMock(side_effect=fake_run)),
            patch("routers.filings.settings.llm_mapping_enabled", True),
            TestClient(app) as client,
        ):
            response = client.post("/api/v1/filings/jobs/101/ai-mapping-suggestions/run")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["run_skipped"])
        self.assertTrue(body["rate_limited"])
        self.assertEqual(body["message"], filings.AI_PROVIDER_RATE_LIMIT_MESSAGE)
        self.assertEqual(body["status"]["ai_mapping_status"], "rate_limited")
        self.assertEqual(body["status"]["last_error_message"], filings.AI_PROVIDER_RATE_LIMIT_MESSAGE)
        self.assertEqual(body["status"]["rate_limited_rows_count"], 1)
        self.assertEqual(body["summary"]["provider_error_type"], "provider_rate_limited")
        self.assertEqual(body["summary"]["saved_suggestions_before_rate_limit"], 1)
        self.assertEqual(body["summary"]["pending_rows"], 1)
        self.assertEqual(len(body["suggestions"]), 1)
        self.assertEqual(body["suggestions"][0]["id"], "suggestion-partial")
        self.assertEqual(session.jobs[101].ai_mapping_status, "rate_limited")
        self.assertIn("suggestion-partial", session.suggestions)
        self.assertNotIn(101, filings.AI_MAPPING_RUNS_IN_PROGRESS)

    def test_accept_ai_mapping_suggestion_updates_only_target_row_mapping(self):
        session = FakeIsolationSession()
        app = build_isolation_app(session, user_id=1)

        with (
            patch(
                "routers.filings.suggestion_template_metadata",
                return_value={
                    "template_field_id": "ifrs-smes:CashAndCashEquivalents",
                    "label": "Cash and cash equivalents",
                    "statement_type": "Statement of Financial Position",
                    "template_code": "210000",
                    "position": 12,
                    "required": False,
                },
            ),
            TestClient(app) as client,
        ):
            response = client.post(
                "/api/v1/filings/extracted-data/item-a/ai-mapping-suggestions/suggestion-a/accept"
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        item = session.items["item-a"]
        self.assertEqual(item.template_field_id, "ifrs-smes:CashAndCashEquivalents")
        self.assertEqual(item.statement_type, "Statement of Financial Position")
        self.assertTrue(item.is_reviewed)
        self.assertIsNone(item.confirmed_tag_id)
        self.assertEqual(session.suggestions["suggestion-a"].status, "accepted")
        self.assertIsNone(session.items["item-b"].template_field_id)

    def test_accept_low_confidence_ai_mapping_suggestion_is_allowed(self):
        session = FakeIsolationSession()
        session.suggestions["suggestion-a"].confidence = 0.18
        session.suggestions["suggestion-a"].diagnostic_json = (
            '{"suggestion": {"requires_human_confirmation": true, '
            '"warning_level": "low_confidence", "confidence_category": "low"}}'
        )
        app = build_isolation_app(session, user_id=1)

        with (
            patch(
                "routers.filings.suggestion_template_metadata",
                return_value={
                    "template_field_id": "ifrs-smes:CashAndCashEquivalents",
                    "label": "Cash and cash equivalents",
                    "statement_type": "Statement of Financial Position",
                    "template_code": "210000",
                    "position": 12,
                    "required": False,
                },
            ),
            TestClient(app) as client,
        ):
            response = client.post(
                "/api/v1/filings/extracted-data/item-a/ai-mapping-suggestions/suggestion-a/accept"
            )

        self.assertEqual(response.status_code, 200)
        item = session.items["item-a"]
        self.assertEqual(item.template_field_id, "ifrs-smes:CashAndCashEquivalents")
        self.assertTrue(item.is_reviewed)
        self.assertIsNone(item.confirmed_tag_id)
        self.assertEqual(session.suggestions["suggestion-a"].status, "accepted")

    def test_ignore_ai_mapping_suggestion_does_not_update_item_mapping(self):
        session = FakeIsolationSession()
        app = build_isolation_app(session, user_id=1)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/filings/extracted-data/item-a/ai-mapping-suggestions/suggestion-a/ignore"
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        item = session.items["item-a"]
        self.assertIsNone(item.template_field_id)
        self.assertFalse(item.is_reviewed)
        self.assertIsNone(item.confirmed_tag_id)
        self.assertEqual(session.suggestions["suggestion-a"].status, "ignored")

    def test_owned_validation_and_download_reach_existing_behavior_after_ownership_check(self):
        session = FakeIsolationSession()
        app = build_isolation_app(session, user_id=1)

        with (
            patch(
                "services.xbrl_validator.xbrl_validator.validate_job_for_xbrl",
                new=AsyncMock(return_value={"is_valid": True, "errors": [], "warnings": []}),
            ) as validate_mock,
            patch(
                "routers.filings.generate_xbrl_for_job",
                new=AsyncMock(return_value=SimpleNamespace(success=True, content="<xbrl/>")),
            ) as generate_mock,
            TestClient(app) as client,
        ):
            validate_response = client.get("/api/v1/filings/jobs/101/validate-xbrl")
            download_response = client.get("/api/v1/filings/jobs/101/download-xbrl")

        self.assertEqual(validate_response.status_code, 200)
        self.assertEqual(download_response.status_code, 200)
        validate_mock.assert_awaited_once()
        generate_mock.assert_awaited_once()


class FilingOwnerMigrationTests(unittest.TestCase):
    def test_filing_job_owner_migration_and_db_init_tracking_exist(self):
        migration = Path("migrations/005_add_filing_job_owner.sql").read_text(
            encoding="utf-8"
        )
        db_init_source = Path("db_init.py").read_text(encoding="utf-8")

        self.assertIn("ADD COLUMN IF NOT EXISTS user_id", migration)
        self.assertIn("REFERENCES users(id)", migration)
        self.assertIn("idx_filing_jobs_user_uploaded", migration)
        self.assertIn('"user_id"', db_init_source)


if __name__ == "__main__":
    unittest.main()
