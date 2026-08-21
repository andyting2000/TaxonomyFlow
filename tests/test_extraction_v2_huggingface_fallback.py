import asyncio
import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from services.extraction_v2_pipeline import (
    BenchmarkCase,
    ExtractionV2Pipeline,
    build_huggingface_v2_prompt,
    build_report,
    huggingface_candidate_from_item,
    parse_huggingface_fallback_result,
    parse_vision_fallback_result_detailed,
)


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
    def __init__(self, *, use_vision_fallback):
        super().__init__(
            use_vision_fallback=use_vision_fallback,
            vision_provider="huggingface",
        )
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

    async def _run_vision_fallbacks(self, *_args, **_kwargs):
        self.fallback_called = True
        candidate = huggingface_candidate_from_item(
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
            "vision_fallback": {
                "enabled": True,
                "provider": "huggingface",
                "pages_attempted": 1,
                "pages_succeeded": 1,
                "pages_failed": 0,
                "pages_skipped_max_limit": 0,
                "candidates_returned": 1,
                "candidates_kept": 1,
                "duplicate_candidates_skipped": 0,
                "failures": [],
            },
            "huggingface_fallback": {
                "enabled": True,
                "provider": "huggingface",
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


class ExtractionV2HuggingFaceFallbackTests(unittest.TestCase):
    def test_huggingface_response_converts_to_candidates(self):
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

        candidates, warnings = parse_huggingface_fallback_result(
            result,
            case=benchmark_case(),
            page_number=1,
            fallback_reason="page_1_no_native_text_detected",
        )

        self.assertFalse(warnings)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].row_type, "numeric_fact")
        self.assertEqual(candidates[0].extraction_method, "huggingface_vision_fallback")
        self.assertIn("huggingface_vision_fallback", candidates[0].warnings)

    def test_reference_xml_is_not_passed_to_huggingface_prompt(self):
        async def fake_call(_image_base64, prompt, **_kwargs):
            self.assertNotIn("source.xml", prompt)
            self.assertNotIn("<xbrl", prompt.lower())
            return {
                "ok": True,
                "output_text": json.dumps(
                    {
                        "page_number": 1,
                        "candidates": [
                            {
                                "row_type": "heading",
                                "statement_section": "Statement of Financial Position",
                                "label": "Assets",
                                "value": None,
                                "previous_value": None,
                                "current_year": None,
                                "prior_year": None,
                                "text": None,
                                "source_snippet": "Assets",
                                "confidence": "medium",
                                "warnings": [],
                                "provenance": {},
                            }
                        ],
                    }
                ),
            }

        pipeline = ExtractionV2Pipeline(use_vision_fallback=True, vision_provider="huggingface")
        with patch(
            "services.extraction_v2_pipeline.call_huggingface_vision_json_from_base64",
            new=AsyncMock(side_effect=fake_call),
        ):
            candidates, warnings = asyncio.run(
                pipeline._huggingface_fallback_for_page(
                    FakePage(),
                    case=benchmark_case(),
                    page_number=1,
                    fallback_reason="page_1_no_native_text_detected",
                )
            )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(warnings, [])

    def test_preferred_candidates_schema_detailed_parser(self):
        parsed = parse_vision_fallback_result_detailed(
            {"ok": True, "output_text": '{"page_number":1,"candidates":[{"row_type":"numeric_fact","label":"Revenue","value":"1200"}]}'},
            case=benchmark_case(),
            page_number=1,
            fallback_reason="test",
            provider="huggingface",
        )

        self.assertEqual(len(parsed["candidates"]), 1)
        self.assertEqual(parsed["candidates"][0].row_type, "numeric_fact")
        self.assertEqual(parsed["diagnostics"]["parser_status"], "preferred_candidates_returned")

    def test_qwen_statement_items_convert_to_comparative_candidate(self):
        parsed = parse_vision_fallback_result_detailed(
            {
                "ok": True,
                "output_text": json.dumps(
                    {
                        "statement": "Statement of Financial Position",
                        "items": [
                            {
                                "description": "Cash and bank balances",
                                "current_period": 15000,
                                "previous_period": 12000,
                            }
                        ],
                    }
                ),
            },
            case=benchmark_case(),
            page_number=1,
            fallback_reason="test",
            provider="huggingface",
        )

        candidate = parsed["candidates"][0]
        self.assertEqual(candidate.row_type, "comparative_numeric_fact")
        self.assertEqual(candidate.statement_section, "Statement of Financial Position")
        self.assertEqual(candidate.label, "Cash and bank balances")
        self.assertEqual(candidate.value, "15000")
        self.assertEqual(candidate.previous_value, "12000")
        self.assertEqual(parsed["diagnostics"]["parser_status"], "normalized_candidates_returned")

    def test_rows_alias_is_parsed(self):
        parsed = parse_vision_fallback_result_detailed(
            {"ok": True, "output_text": '{"statement":"Notes","rows":[{"name":"Receivables","amount":"1,234"}]}'},
            case=benchmark_case(),
            page_number=1,
            fallback_reason="test",
            provider="huggingface",
        )

        self.assertEqual(parsed["candidates"][0].label, "Receivables")
        self.assertEqual(parsed["candidates"][0].value, "1234")

    def test_table_alias_is_parsed(self):
        parsed = parse_vision_fallback_result_detailed(
            {"ok": True, "output_text": '{"table":[{"label":"Inventory","current":"450","previous":"300"}]}'},
            case=benchmark_case(),
            page_number=1,
            fallback_reason="test",
            provider="huggingface",
        )

        self.assertEqual(parsed["candidates"][0].row_type, "comparative_numeric_fact")
        self.assertEqual(parsed["candidates"][0].previous_value, "300")

    def test_markdown_fenced_json_is_parsed(self):
        parsed = parse_vision_fallback_result_detailed(
            {"ok": True, "output_text": '```json\n{"candidates":[{"label":"Cash","amount":"99"}]}\n```'},
            case=benchmark_case(),
            page_number=1,
            fallback_reason="test",
            provider="huggingface",
        )

        self.assertEqual(parsed["candidates"][0].label, "Cash")

    def test_embedded_json_object_is_parsed(self):
        parsed = parse_vision_fallback_result_detailed(
            {"ok": True, "output_text": 'Here is the result: {"items":[{"description":"Cash","current_period":"100"}]} done.'},
            case=benchmark_case(),
            page_number=1,
            fallback_reason="test",
            provider="huggingface",
        )

        self.assertEqual(parsed["candidates"][0].row_type, "numeric_fact")

    def test_amount_only_current_value_maps_to_numeric_fact(self):
        parsed = parse_vision_fallback_result_detailed(
            {"ok": True, "output_text": '{"items":[{"account":"Bank","amount":"2,500"}]}'},
            case=benchmark_case(),
            page_number=1,
            fallback_reason="test",
            provider="huggingface",
        )

        self.assertEqual(parsed["candidates"][0].row_type, "numeric_fact")
        self.assertEqual(parsed["candidates"][0].value, "2500")

    def test_long_text_maps_to_text_block(self):
        text = " ".join(["The company continues its principal activities and manages financial risks carefully."] * 4)
        parsed = parse_vision_fallback_result_detailed(
            {"ok": True, "output_text": json.dumps({"rows": [{"description": "Principal activities", "text": text}]})},
            case=benchmark_case(),
            page_number=1,
            fallback_reason="test",
            provider="huggingface",
        )

        self.assertEqual(parsed["candidates"][0].row_type, "text_block")
        self.assertIn("text_block_not_numeric", parsed["candidates"][0].warnings)

    def test_empty_candidates_classified_without_parser_failure_page(self):
        parsed = parse_vision_fallback_result_detailed(
            {"ok": True, "output_text": '{"page_number":1,"candidates":[]}'},
            case=benchmark_case(),
            page_number=1,
            fallback_reason="test",
            provider="huggingface",
        )

        self.assertEqual(parsed["diagnostics"]["parser_failure_reason"], "empty_candidates_returned")
        self.assertTrue(parsed["diagnostics"]["parsed_json_detected"])

    def test_non_json_response_records_capped_raw_preview(self):
        output = "not json " + ("x" * 3000)
        parsed = parse_vision_fallback_result_detailed(
            {"ok": True, "output_text": output},
            case=benchmark_case(),
            page_number=1,
            fallback_reason="test",
            provider="huggingface",
        )

        self.assertEqual(parsed["diagnostics"]["parser_failure_reason"], "output_not_json")
        self.assertLessEqual(len(parsed["diagnostics"]["raw_response_preview"]), 1500)

    def test_huggingface_prompt_excludes_reference_xml_language(self):
        prompt = build_huggingface_v2_prompt(page_number=1, case_id="case-001", fallback_reason="test")

        self.assertNotIn("source.xml", prompt)
        self.assertNotIn("<xbrl", prompt.lower())
        self.assertIn("Return JSON only", prompt)

    def test_huggingface_fallback_is_not_called_when_disabled(self):
        pipeline = StubPipeline(use_vision_fallback=False)

        report = asyncio.run(pipeline.run_case(benchmark_case()))

        self.assertFalse(pipeline.fallback_called)
        self.assertEqual(report["huggingface_candidate_count"], 0)

    def test_huggingface_fallback_is_called_for_no_native_text_when_enabled(self):
        pipeline = StubPipeline(use_vision_fallback=True)

        report = asyncio.run(pipeline.run_case(benchmark_case()))

        self.assertTrue(pipeline.fallback_called)
        self.assertEqual(report["huggingface_candidate_count"], 1)
        self.assertEqual(report["openai_candidate_count"], 0)
        self.assertEqual(report["row_type_counts"]["text_block"], 1)

    def test_report_distinguishes_huggingface_and_openai_counts(self):
        candidate = huggingface_candidate_from_item(
            {
                "row_type": "text_block",
                "statement_section": "Directors Report",
                "label": "Directors Report",
                "value": None,
                "previous_value": None,
                "current_year": None,
                "prior_year": None,
                "text": "The directors present their report.",
                "source_snippet": "The directors present their report",
                "confidence": 0.8,
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
                    "huggingface_fallback": {
                        "pages_attempted": 1,
                        "pages_succeeded": 1,
                        "candidates_returned": 1,
                        "raw_response_preview_count": 1,
                        "parser_recovered_candidates": 1,
                        "parser_failed_pages": 0,
                        "empty_candidate_pages": 0,
                        "no_relevant_content_pages": 0,
                        "parser_failure_reasons": {},
                    },
                }
            ],
            cases_dir="benchmark_cases",
            output_json=Path("reports/extraction_v2_report_test.json"),
            limit_pages=None,
            use_vision_fallback=True,
            vision_provider="huggingface",
        )

        self.assertTrue(report["run_metadata"]["huggingface_used"])
        self.assertFalse(report["run_metadata"]["openai_used"])
        self.assertEqual(report["aggregate_metrics"]["huggingface_candidate_count"], 1)
        self.assertEqual(report["aggregate_metrics"]["openai_candidate_count"], 0)
        self.assertEqual(report["aggregate_metrics"]["hf_raw_response_preview_count"], 1)
        self.assertEqual(report["aggregate_metrics"]["hf_parser_recovered_candidates"], 1)


if __name__ == "__main__":
    unittest.main()
