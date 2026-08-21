import asyncio
import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from scripts.run_extraction_v2 import (
    PRIVATE_PDF_OPENAI_APPROVAL_REQUIRED_MESSAGE,
    validate_private_pdf_openai_approval,
)
from services.extraction_v2_pipeline import (
    BenchmarkCase,
    ExtractionV2Pipeline,
    build_report,
    merge_candidates_dedup,
    openai_candidate_from_item,
    parse_openai_fallback_result,
    select_openai_fallback_pages,
    should_run_openai_fallback,
)
from services.extraction_v2_schema import ExtractionV2Candidate


def benchmark_case() -> BenchmarkCase:
    return BenchmarkCase(
        case_id="case-001",
        case_dir="benchmark_cases/case-001",
        pdf_path="feature_list.json",
        reference_path="benchmark_cases/case-001/source.xml",
        reference_available=True,
        reference_type="xml",
    )


class FakePixmap:
    def tobytes(self, _format):
        return b"\x89PNG\r\n\x1a\n"


class FakePage:
    def get_pixmap(self, **_kwargs):
        return FakePixmap()


class StubPipeline(ExtractionV2Pipeline):
    def __init__(self, *, use_openai):
        super().__init__(use_openai=use_openai)
        self.fallback_called = False

    def _extract_native_pdf(self, *_args, **_kwargs):
        return {
            "status": "ok",
            "pages_analyzed": 1,
            "warnings": ["page_1_no_native_text_detected"],
            "candidates": [],
            "page_reports": [
                {
                    "page_number": 1,
                    "native_text_length": 0,
                    "native_line_count": 0,
                    "native_candidate_count": 0,
                    "native_numeric_or_text_count": 0,
                }
            ],
        }

    async def _run_openai_fallbacks(self, *_args, **_kwargs):
        self.fallback_called = True
        candidate = openai_candidate_from_item(
            {
                "row_type": "text_block",
                "statement_section": "Directors Report",
                "label": "Directors Report",
                "value": None,
                "previous_value": None,
                "current_year": None,
                "prior_year": None,
                "text": "The directors present their report for the financial year.",
                "source_snippet": "The directors present their report",
                "confidence": 0.8,
                "warnings": [],
                "provenance": {"page_number": 1, "text_snippet": "The directors present", "image_source": None, "notes": None},
            },
            case=benchmark_case(),
            page_number=1,
            fallback_reason="page_1_no_native_text_detected",
        )
        return {
            "openai_fallback": {
                "enabled": True,
                "pages_attempted": 1,
                "pages_succeeded": 1,
                "pages_failed": 0,
                "pages_skipped_max_limit": 0,
                "candidates_returned": 1,
                "candidates_kept": 1,
                "duplicate_candidates_skipped": 0,
                "failures": [],
            },
            "warnings": [],
            "candidates": [candidate],
        }


class ExtractionV2OpenAIFallbackTests(unittest.TestCase):
    def test_use_openai_without_private_pdf_approval_is_blocked(self):
        approved, message = validate_private_pdf_openai_approval(use_openai=True, approved=False)

        self.assertFalse(approved)
        self.assertEqual(message, PRIVATE_PDF_OPENAI_APPROVAL_REQUIRED_MESSAGE)

    def test_no_openai_does_not_require_private_pdf_approval(self):
        approved, message = validate_private_pdf_openai_approval(use_openai=False, approved=False)

        self.assertTrue(approved)
        self.assertIsNone(message)

    def test_use_openai_with_private_pdf_approval_is_allowed(self):
        approved, message = validate_private_pdf_openai_approval(use_openai=True, approved=True)

        self.assertTrue(approved)
        self.assertIsNone(message)

    def test_openai_fallback_is_not_called_when_disabled(self):
        pipeline = StubPipeline(use_openai=False)

        report = asyncio.run(pipeline.run_case(benchmark_case()))

        self.assertFalse(pipeline.fallback_called)
        self.assertEqual(report["openai_candidate_count"], 0)

    def test_openai_fallback_is_called_for_no_native_text_when_enabled(self):
        pipeline = StubPipeline(use_openai=True)

        report = asyncio.run(pipeline.run_case(benchmark_case()))

        self.assertTrue(pipeline.fallback_called)
        self.assertEqual(report["openai_candidate_count"], 1)
        self.assertEqual(report["row_type_counts"]["text_block"], 1)

    def test_good_native_page_is_not_selected_by_default(self):
        should_run, reason = should_run_openai_fallback(
            {
                "page_number": 1,
                "native_text_length": 1000,
                "native_line_count": 35,
                "native_candidate_count": 4,
                "native_numeric_or_text_count": 2,
            }
        )

        self.assertFalse(should_run)
        self.assertEqual(reason, "native_extraction_sufficient")

    def test_openai_response_converts_to_candidates(self):
        result = {
            "ok": True,
            "output_text": json.dumps(
                {
                    "page_number": 1,
                    "candidates": [
                        {
                            "row_type": "numeric_fact",
                            "statement_section": "Statement of Profit or Loss",
                            "label": "Revenue",
                            "value": "300000",
                            "previous_value": None,
                            "current_year": 2025,
                            "prior_year": None,
                            "text": None,
                            "source_snippet": "Revenue 300,000",
                            "confidence": 0.82,
                            "warnings": [],
                            "provenance": {"page_number": 1, "text_snippet": "Revenue 300,000", "image_source": "rendered_pdf_page", "notes": None},
                        }
                    ],
                }
            ),
        }

        candidates, warnings = parse_openai_fallback_result(
            result,
            case=benchmark_case(),
            page_number=1,
            fallback_reason="page_1_no_native_text_detected",
        )

        self.assertFalse(warnings)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].row_type, "numeric_fact")
        self.assertEqual(candidates[0].extraction_method, "openai_vision_fallback")
        self.assertIn("openai_vision_fallback", candidates[0].warnings)

    def test_openai_comparative_candidate_is_accepted(self):
        candidate = openai_candidate_from_item(
            {
                "row_type": "comparative_numeric_fact",
                "statement_section": "Statement of Financial Position",
                "label": "Trade receivables",
                "value": "1234567",
                "previous_value": "1000000",
                "current_year": 2025,
                "prior_year": 2024,
                "text": None,
                "source_snippet": "Trade receivables 1,234,567 1,000,000",
                "confidence": 0.76,
                "warnings": [],
                "provenance": {},
            },
            case=benchmark_case(),
            page_number=2,
            fallback_reason="page_2_no_native_text_detected",
        )

        self.assertEqual(candidate.row_type, "comparative_numeric_fact")
        self.assertEqual(candidate.previous_value, "1000000")
        self.assertEqual(candidate.extraction_method, "openai_vision_fallback")

    def test_openai_text_block_candidate_is_accepted(self):
        candidate = openai_candidate_from_item(
            {
                "row_type": "text_block",
                "statement_section": "Notes to the Financial Statements",
                "label": "Basis of Preparation",
                "value": None,
                "previous_value": None,
                "current_year": None,
                "prior_year": None,
                "text": "The financial statements have been prepared in accordance with the applicable framework.",
                "source_snippet": "The financial statements have been prepared",
                "confidence": 0.7,
                "warnings": [],
                "provenance": {},
            },
            case=benchmark_case(),
            page_number=3,
            fallback_reason="page_3_no_native_text_detected",
        )

        self.assertEqual(candidate.row_type, "text_block")
        self.assertIsNone(candidate.value)
        self.assertIn("text_block_not_numeric", candidate.warnings)

    def test_openai_failure_is_recorded_without_crashing(self):
        candidates, warnings = parse_openai_fallback_result(
            {"ok": False, "error_type": "configuration", "error": "OPENAI_API_KEY is not configured"},
            case=benchmark_case(),
            page_number=1,
            fallback_reason="page_1_no_native_text_detected",
        )

        self.assertEqual(candidates, [])
        self.assertIn("configuration", warnings[0])

    def test_duplicate_native_and_openai_candidates_are_skipped_conservatively(self):
        native = ExtractionV2Candidate(
            case_id="case-001",
            source_pdf="source.pdf",
            page_number=1,
            extraction_method="native_table_heuristic",
            row_type="numeric_fact",
            statement_section="Statement of Profit or Loss",
            label="Revenue",
            value="300000",
        )
        fallback = ExtractionV2Candidate(
            case_id="case-001",
            source_pdf="source.pdf",
            page_number=1,
            extraction_method="openai_vision_fallback",
            row_type="numeric_fact",
            statement_section="Statement of Profit or Loss",
            label="Revenue",
            value="300000",
            warnings=["openai_vision_fallback"],
        )

        merged, skipped = merge_candidates_dedup([native], [fallback])

        self.assertEqual(len(merged), 1)
        self.assertEqual(skipped, 1)

    def test_openai_max_pages_limit_is_respected(self):
        selected, skipped = select_openai_fallback_pages(
            [
                {"page_number": 1, "native_text_length": 0},
                {"page_number": 2, "native_text_length": 0},
                {"page_number": 3, "native_text_length": 0},
            ],
            max_pages=2,
        )

        self.assertEqual([page["page_number"] for page in selected], [1, 2])
        self.assertEqual(skipped, 1)

    def test_reference_xml_is_not_passed_to_openai_prompt(self):
        async def fake_call(_image_base64, prompt, **_kwargs):
            self.assertNotIn("source.xml", prompt)
            self.assertNotIn("<xbrl", prompt.lower())
            return {"ok": True, "output_text": '{"page_number":1,"candidates":[]}'}

        pipeline = ExtractionV2Pipeline(use_openai=True)
        with patch(
            "services.extraction_v2_pipeline.call_openai_vision_json_from_base64",
            new=AsyncMock(side_effect=fake_call),
        ):
            candidates, warnings = asyncio.run(
                pipeline._openai_fallback_for_page(
                    FakePage(),
                    case=benchmark_case(),
                    page_number=1,
                    fallback_reason="page_1_no_native_text_detected",
                )
            )

        self.assertEqual(candidates, [])
        self.assertEqual(warnings, [])

    def test_report_records_private_pdf_approval_and_no_reference_xml_transmission(self):
        report = build_report(
            [],
            cases_dir="benchmark_cases",
            output_json=Path("reports/extraction_v2_report_test.json"),
            limit_pages=None,
            use_openai=True,
            openai_page_mode="failed-native-only",
            openai_max_pages=10,
            private_pdf_openai_approved=True,
        )

        self.assertTrue(report["run_metadata"]["openai_used"])
        self.assertTrue(report["run_metadata"]["private_pdf_openai_approved"])
        self.assertFalse(report["run_metadata"]["reference_xml_sent_to_openai"])

    def test_openai_text_block_candidate_increases_report_text_block_count(self):
        candidate = openai_candidate_from_item(
            {
                "row_type": "text_block",
                "statement_section": "Directors Report",
                "label": "Directors Report",
                "value": None,
                "previous_value": None,
                "current_year": None,
                "prior_year": None,
                "text": "The directors present their report and financial statements for the year.",
                "source_snippet": "The directors present their report",
                "confidence": 0.82,
                "warnings": [],
                "provenance": {},
            },
            case=benchmark_case(),
            page_number=1,
            fallback_reason="page_1_no_native_text_detected",
        )
        report = build_report(
            [
                {
                    "case_id": "case-001",
                    "source_pdf": "source.pdf",
                    "candidates": [candidate.to_dict()],
                    "warnings": [],
                    "openai_fallback": {"pages_attempted": 1, "pages_succeeded": 1, "candidates_returned": 1},
                }
            ],
            cases_dir="benchmark_cases",
            output_json=Path("reports/extraction_v2_report_test.json"),
            limit_pages=None,
            use_openai=True,
            private_pdf_openai_approved=True,
        )

        self.assertEqual(report["aggregate_metrics"]["text_block_count"], 1)
        self.assertEqual(report["aggregate_metrics"]["openai_candidate_count"], 1)


if __name__ == "__main__":
    unittest.main()
