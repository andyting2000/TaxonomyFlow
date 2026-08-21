import json
import unittest
from unittest.mock import patch

from config import settings
from services.document_section_template_classifier import load_template_group_cards
from services.template_group_llm_classifier import (
    TemplateGroupLLMError,
    classify_with_bounded_llm,
    validate_template_group_llm_response,
)
from services.toc_aware_template_classification import analyze_template_classification
from tests.template_classification_test_support import (
    evidence,
    fixtures,
    section,
    structure,
)


class CountingClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def complete(self, prompt, *, model_id):
        self.calls.append((json.loads(prompt), model_id))
        return self.response


def valid_response(template_group_id="740000"):
    return {
        "outcome": "matched",
        "assignments": [
            {
                "template_group_id": template_group_id,
                "confidence": 0.82,
                "evidence": ["Issued capital wording"],
            }
        ],
        "alternative_template_group_ids": [],
        "requires_human_review": False,
        "reason": "One supported canonical role.",
    }


class TemplateGroupLLMClassifierTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.cards, _metadata = load_template_group_cards()
        cls.data = fixtures()

    def validate(self, response):
        return validate_template_group_llm_response(
            response,
            cards=self.cards,
            source_section_id="note-1",
            raw_title="Other information",
            normalized_title="other information",
            canonical_section_type="note_subsection",
            parent_section_id="notes_container",
            section_level=3,
            page_range={"pdf_page_start": 1, "pdf_page_end": 1},
            model="fixture-model",
        )

    async def call(self, client):
        return await classify_with_bounded_llm(
            context={"source_title": "Other information"},
            cards=self.cards,
            source_section_id="note-1",
            raw_title="Other information",
            normalized_title="other information",
            canonical_section_type="note_subsection",
            parent_section_id="notes_container",
            section_level=3,
            page_range={"pdf_page_start": 1, "pdf_page_end": 1},
            client=client,
        )

    async def test_live_flag_false_causes_zero_calls(self):
        client = CountingClient(valid_response())
        with patch.object(
            settings,
            "toc_aware_template_classification_live_llm_enabled",
            False,
        ):
            with self.assertRaises(TemplateGroupLLMError):
                await self.call(client)
        self.assertEqual(client.calls, [])

    async def test_one_unresolved_subsection_makes_exactly_one_call(self):
        client = CountingClient(valid_response())
        with (
            patch.object(
                settings,
                "toc_aware_template_classification_live_llm_enabled",
                True,
            ),
            patch.object(
                settings,
                "toc_aware_template_classification_model_id",
                "fixture-model",
            ),
        ):
            outcome = await self.call(client)
        self.assertEqual(len(client.calls), 1)
        self.assertTrue(outcome.llm_called)
        self.assertEqual(outcome.assignments[0].template_code, "740000")
        self.assertEqual(outcome.assignments[0].assignment_method.value, "bounded_llm")

    def test_unknown_id_and_invalid_json_fail_closed(self):
        with self.assertRaisesRegex(TemplateGroupLLMError, "unknown ID"):
            self.validate(self.data["M"]["response"])
        with self.assertRaisesRegex(TemplateGroupLLMError, "valid JSON"):
            self.validate(self.data["N"]["response"])

    def test_duplicate_ids_are_deduplicated(self):
        response = valid_response()
        response["assignments"].append(dict(response["assignments"][0]))
        outcome = self.validate(response)
        self.assertEqual(len(outcome.assignments), 1)

    def test_outcome_assignment_invariants_fail_closed(self):
        response = valid_response()
        response["outcome"] = "container_only"
        with self.assertRaisesRegex(TemplateGroupLLMError, "cannot carry"):
            self.validate(response)
        response = valid_response()
        response["assignments"] = []
        with self.assertRaisesRegex(TemplateGroupLLMError, "exactly one"):
            self.validate(response)

    async def test_orchestrator_calls_once_and_rejects_invalid_response_without_retry(self):
        heading = evidence(
            "unknown-heading",
            "9. SEGMENT REPORTING",
            page=1,
            top=10,
        )
        source = structure(
            sections=[
                section(
                    canonical_section_type="notes_to_financial_statements",
                    title="Notes to the Financial Statements",
                    references=[heading.content_id],
                    candidate_note_heading_ids=[heading.content_id],
                )
            ],
            content_evidence=[heading],
        )
        with (
            patch.object(
                settings,
                "toc_aware_template_classification_live_llm_enabled",
                True,
            ),
            patch.object(
                settings,
                "toc_aware_template_classification_model_id",
                "fixture-model",
            ),
        ):
            accepted_client = CountingClient(valid_response())
            accepted = await analyze_template_classification(
                job_id=101,
                structure=source,
                llm_client=accepted_client,
            )
            invalid_client = CountingClient("not-json")
            rejected = await analyze_template_classification(
                job_id=101,
                structure=source,
                llm_client=invalid_client,
            )
        self.assertEqual(len(accepted_client.calls), 1)
        self.assertEqual(accepted.llm_count, 1)
        self.assertEqual(
            next(item for item in accepted.outcomes if item.llm_called).outcome.value,
            "matched",
        )
        self.assertEqual(len(invalid_client.calls), 1)
        self.assertEqual(rejected.llm_count, 1)
        self.assertEqual(rejected.failed_count, 1)
        failed = next(item for item in rejected.outcomes if item.llm_called)
        self.assertEqual(failed.outcome.value, "classification_failed")
        self.assertTrue(failed.requires_human_review)


if __name__ == "__main__":
    unittest.main()
