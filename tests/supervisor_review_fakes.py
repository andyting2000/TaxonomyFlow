import json
from datetime import datetime

from database import (
    ExtractedDataItem,
    FilingJob,
    FinancialStatementPage,
    LLMMappingSuggestion,
    MappingSupervisorReview,
    SupervisorGuidedMappingRevision,
)


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


def supervisor_test_playbook():
    return {
        "run_metadata": {"feature": "unit-test", "external_llm_called": False},
        "concept_cards": [
            {
                "concept_qname": "ifrs-smes:CashAndCashEquivalents",
                "template_field_id": "ifrs-smes:CashAndCashEquivalents",
                "canonical_label": "Cash and cash equivalents",
                "statement_families_observed": ["Statement of Financial Position"],
                "common_extracted_labels": ["Cash and cash equivalents"],
                "normalized_label_patterns": ["cash and cash equivalents"],
                "accounting_synonyms": ["cash"],
                "semantic_families": ["cash"],
                "typical_value_nature": "positive",
                "common_sections": ["Statement of Financial Position"],
                "example_mappings": [
                    {
                        "extracted_label": "Cash and cash equivalents",
                        "statement_type": "Statement of Financial Position",
                        "mapped_concept_qname": "ifrs-smes:CashAndCashEquivalents",
                        "mapped_template_field_id": "ifrs-smes:CashAndCashEquivalents",
                        "source_case_id": "case_001",
                        "evidence_reason": "unit fixture",
                    }
                ],
                "do_not_confuse_with": [],
                "guardrail_notes": [],
                "source_case_ids": ["case_001"],
                "support_count": 3,
                "quality": "strong",
            },
            {
                "concept_qname": "ifrs-smes:Revenue",
                "template_field_id": "ifrs-smes:Revenue",
                "canonical_label": "Revenue",
                "statement_families_observed": ["Statement of Comprehensive Income"],
                "common_extracted_labels": ["Revenue"],
                "normalized_label_patterns": ["revenue"],
                "accounting_synonyms": [],
                "semantic_families": ["revenue"],
                "typical_value_nature": "positive",
                "common_sections": ["Statement of Comprehensive Income"],
                "example_mappings": [],
                "do_not_confuse_with": [],
                "guardrail_notes": [],
                "source_case_ids": ["case_001"],
                "support_count": 2,
                "quality": "strong",
            },
        ],
    }


def supervisor_template_metadata(template_field_id):
    labels = {
        "ifrs-smes:CashAndCashEquivalents": "Cash and cash equivalents",
        "ifrs-smes:Revenue": "Revenue",
    }
    statements = {
        "ifrs-smes:CashAndCashEquivalents": "Statement of Financial Position",
        "ifrs-smes:Revenue": "Statement of Comprehensive Income",
    }
    if template_field_id not in labels:
        return None
    return {
        "template_field_id": template_field_id,
        "label": labels[template_field_id],
        "statement_type": statements[template_field_id],
        "template_code": "210000",
        "position": 1,
        "required": False,
    }


class FakeSupervisorSession:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0
        self.flushes = 0
        self.added = []
        self.jobs = {
            101: self._job(101, 1, "Owner A"),
            202: self._job(202, 2, "Owner B"),
        }
        self.pages = {
            "page-a": self._page("page-a", 101, 1),
            "page-cashflow": self._page("page-cashflow", 101, 2),
            "page-b": self._page("page-b", 202, 1),
        }
        self.items = {
            "item-a": self._item(
                "item-a",
                "page-a",
                "Cash and cash equivalents",
                "100",
                "Statement of Financial Position",
            ),
            "item-cashflow": self._item(
                "item-cashflow",
                "page-cashflow",
                "Other",
                "55",
                "Statement of Cash Flows",
            ),
            "item-b": self._item("item-b", "page-b", "Revenue", "200", "Statement of Comprehensive Income"),
        }
        self.suggestions = {
            "suggestion-a": self._suggestion(
                "suggestion-a",
                101,
                "item-a",
                "ifrs-smes:CashAndCashEquivalents",
            ),
            "suggestion-cashflow": self._suggestion(
                "suggestion-cashflow",
                101,
                "item-cashflow",
                "ifrs-smes:CashAndCashEquivalents",
            ),
            "suggestion-b": self._suggestion("suggestion-b", 202, "item-b", "ifrs-smes:Revenue"),
        }
        self.reviews = []
        self.mapping_revisions = []
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

    def _suggestion(self, suggestion_id, job_id, item_id, template_field_id):
        return LLMMappingSuggestion(
            id=suggestion_id,
            job_id=job_id,
            extracted_data_item_id=item_id,
            suggested_template_field_id=template_field_id,
            confidence=0.97,
            reason="AI selected this candidate.",
            ranked_candidates_json=json.dumps(
                [
                    {
                        "template_field_id": template_field_id,
                        "concept_qname": template_field_id,
                        "label": supervisor_template_metadata(template_field_id)["label"],
                        "statement_type": supervisor_template_metadata(template_field_id)["statement_type"],
                        "confidence": 0.97,
                        "reason": "candidate fixture",
                    }
                ]
            ),
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
                suggestion for suggestion in self.suggestions.values() if suggestion.job_id == job.id
            ]
            job.supervisor_reviews = [
                review for review in self.reviews if review.job_id == job.id
            ]

    def add(self, value):
        self.added.append(value)
        if isinstance(value, MappingSupervisorReview):
            self.reviews.append(value)
            self._wire_relationships()
            return
        if isinstance(value, SupervisorGuidedMappingRevision):
            self.mapping_revisions.append(value)
            return
        raise AssertionError(f"Unexpected add: {value!r}")

    async def flush(self):
        self.flushes += 1

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def execute(self, statement):
        sql = str(statement)
        params = statement.compile().params
        if "FROM filing_jobs" in sql:
            return self._execute_job_query(params)
        if "FROM llm_mapping_suggestions" in sql:
            return self._execute_suggestion_query(params)
        if "FROM mapping_supervisor_reviews" in sql:
            return self._execute_review_query(params)
        if "FROM supervisor_guided_mapping_revisions" in sql:
            return self._execute_mapping_revision_query(params)
        raise AssertionError(f"Unexpected query: {sql} params={params}")

    def _execute_job_query(self, params):
        job_id = self._param(params, "id")
        user_id = self._param(params, "user_id")
        job = self.jobs.get(job_id)
        if not job or (user_id is not None and job.user_id != user_id):
            return DummyResult(one=None)
        return DummyResult(one=job)

    def _execute_suggestion_query(self, params):
        suggestion_id = self._param(params, "id")
        job_id = self._param(params, "job_id")
        suggestions = list(self.suggestions.values())
        if suggestion_id is not None:
            suggestions = [suggestion for suggestion in suggestions if suggestion.id == suggestion_id]
        if job_id is not None:
            suggestions = [suggestion for suggestion in suggestions if suggestion.job_id == job_id]
        return DummyResult(one=suggestions[0] if suggestions else None, many=suggestions)

    def _execute_review_query(self, params):
        review_id = self._param(params, "id")
        job_id = self._param(params, "job_id")
        suggestion_id = self._param(params, "llm_mapping_suggestion_id")
        source = self._param(params, "source")
        reviews = list(self.reviews)
        if review_id is not None:
            reviews = [review for review in reviews if review.id == review_id]
        if job_id is not None:
            reviews = [review for review in reviews if review.job_id == job_id]
        if suggestion_id is not None:
            reviews = [
                review for review in reviews if review.llm_mapping_suggestion_id == suggestion_id
            ]
        if source is not None:
            reviews = [review for review in reviews if review.source == source]
        reviews.sort(key=lambda review: (review.review_attempt, review.created_at), reverse=True)
        return DummyResult(one=reviews[0] if reviews else None, many=reviews)

    def _execute_mapping_revision_query(self, params):
        job_id = self._param(params, "job_id")
        parent_suggestion_id = self._param(params, "parent_suggestion_id")
        revisions = list(self.mapping_revisions)
        if job_id is not None:
            revisions = [revision for revision in revisions if revision.job_id == job_id]
        if parent_suggestion_id is not None:
            revisions = [
                revision
                for revision in revisions
                if revision.parent_suggestion_id == parent_suggestion_id
            ]
        revisions.sort(key=lambda revision: (revision.created_at, revision.id), reverse=True)
        return DummyResult(one=revisions[0] if revisions else None, many=revisions)

    def _param(self, params, prefix):
        for key, value in params.items():
            if key.startswith(prefix):
                return value
        return None
