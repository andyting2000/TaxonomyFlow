import unittest
from pathlib import Path

from scripts.compare_v2_to_reference import (
    build_huggingface_qwen_closeout_report,
    compare_reports,
    render_closeout_markdown,
    render_markdown,
)


def reference_report():
    return {
        "case_reports": [
            {
                "case_id": "case-a",
                "facts": [
                    {
                        "qname": "ifrs-smes:Revenue",
                        "local_name": "Revenue",
                        "is_numeric": True,
                        "is_text_block": False,
                        "is_nil": False,
                    },
                    {
                        "qname": "ssmt:DisclosureOfDirectorsReportExplanatory",
                        "local_name": "DisclosureOfDirectorsReportExplanatory",
                        "is_numeric": False,
                        "is_text_block": True,
                        "is_nil": False,
                    },
                ],
            }
        ]
    }


def v2_headings_only_report():
    return {
        "case_reports": [
            {
                "case_id": "case-a",
                "candidates": [
                    {"row_type": "heading", "label": "Revenue"},
                    {"row_type": "heading", "label": "Directors report"},
                ],
            }
        ]
    }


def v2_mixed_provider_report(include_hf_metrics: bool = True, include_openai: bool = True):
    candidates = [
        {"row_type": "numeric_fact", "label": "Revenue", "extraction_method": "native_text"},
        {
            "row_type": "text_block",
            "label": "Directors report",
            "extraction_method": "huggingface_vision_fallback",
        },
        {
            "row_type": "subtotal_or_total",
            "label": "Total assets",
            "extraction_method": "huggingface_vision_fallback",
        },
    ]
    if include_openai:
        candidates.append(
            {
                "row_type": "heading",
                "label": "Legacy heading",
                "extraction_method": "openai_vision_fallback",
            }
        )
    aggregate_metrics = {
        "huggingface_candidate_count": 2,
        "openai_candidate_count": 1 if include_openai else 0,
        "native_candidate_count": 1,
    }
    if include_hf_metrics:
        aggregate_metrics.update(
            {
                "huggingface_fallback_pages_attempted": 3,
                "huggingface_fallback_pages_succeeded": 2,
                "huggingface_fallback_pages_failed": 1,
                "hf_empty_candidate_pages": 1,
                "hf_parser_recovered_candidates": 2,
                "hf_parser_failed_pages": 0,
                "hf_raw_response_preview_count": 3,
            }
        )
    return {
        "run_metadata": {
            "database_mutated": False,
            "xbrl_generated": False,
            "arelle_validation_run": False,
            "openai_used": False,
            "huggingface_used": True,
            "vision_provider": "huggingface",
            "vision_model_id": "Qwen/Qwen2.5-VL-72B-Instruct:fastest",
            "text_model_id": "Qwen/Qwen3-30B-A3B-Instruct-2507:featherless-ai",
            "embedding_model_id": "Qwen/Qwen3-Embedding-8B",
        },
        "aggregate_metrics": aggregate_metrics,
        "case_reports": [
            {
                "case_id": "case-a",
                "candidates": candidates,
            }
        ],
    }


class CompareV2ToReferenceTests(unittest.TestCase):
    def test_reference_numeric_facts_but_v2_none_reports_missing_signal(self):
        comparison = compare_reports(reference_report(), v2_headings_only_report())
        self.assertTrue(comparison["aggregate_metrics"]["missing_numeric_extraction_signal"])
        self.assertEqual(comparison["aggregate_metrics"]["v2_numeric_fact_candidates"], 0)

    def test_reference_text_blocks_but_v2_none_reports_missing_signal(self):
        comparison = compare_reports(reference_report(), v2_headings_only_report())
        self.assertTrue(comparison["aggregate_metrics"]["missing_text_block_extraction_signal"])
        self.assertEqual(comparison["aggregate_metrics"]["v2_text_block_candidates"], 0)

    def test_v2_headings_only_does_not_crash_comparison(self):
        comparison = compare_reports(reference_report(), v2_headings_only_report())
        self.assertEqual(comparison["aggregate_metrics"]["cases_compared"], 1)
        self.assertEqual(comparison["aggregate_metrics"]["v2_total_candidates"], 2)

    def test_per_case_summary_is_stable(self):
        comparison = compare_reports(reference_report(), v2_headings_only_report())
        per_case = comparison["per_case"][0]
        self.assertEqual(per_case["case_id"], "case-a")
        self.assertEqual(per_case["reference_numeric_facts"], 1)
        self.assertEqual(per_case["reference_text_blocks"], 1)
        self.assertTrue(per_case["missing_numeric_extraction_signal"])
        self.assertTrue(per_case["missing_text_block_extraction_signal"])

    def test_markdown_report_renders_key_metrics(self):
        comparison = compare_reports(reference_report(), v2_headings_only_report())
        markdown = render_markdown(comparison)
        self.assertIn("Reference numeric facts: 1", markdown)
        self.assertIn("V2 numeric candidates: 0", markdown)
        self.assertIn("Missing text-block extraction signal: True", markdown)

    def test_comparison_distinguishes_total_from_native_only_candidates(self):
        comparison = compare_reports(reference_report(), v2_mixed_provider_report())
        aggregate = comparison["aggregate_metrics"]
        self.assertEqual(aggregate["v2_total_candidates"], 4)
        self.assertEqual(aggregate["v2_native_only_candidates"], 1)
        self.assertEqual(aggregate["v2_native_candidates"], 1)
        self.assertIn("Legacy field", aggregate["v2_native_candidates_legacy_note"])

    def test_huggingface_and_openai_candidates_are_counted_separately(self):
        comparison = compare_reports(reference_report(), v2_mixed_provider_report())
        aggregate = comparison["aggregate_metrics"]
        self.assertEqual(aggregate["v2_huggingface_candidates"], 2)
        self.assertEqual(aggregate["v2_openai_candidates"], 1)
        self.assertEqual(aggregate["v2_live_model_candidates"], 3)
        self.assertEqual(aggregate["v2_non_native_candidates"], 3)

    def test_huggingface_page_metrics_are_included_when_present(self):
        comparison = compare_reports(reference_report(), v2_mixed_provider_report())
        aggregate = comparison["aggregate_metrics"]
        self.assertEqual(aggregate["v2_huggingface_fallback_pages_attempted"], 3)
        self.assertEqual(aggregate["v2_huggingface_fallback_pages_succeeded"], 2)
        self.assertEqual(aggregate["v2_huggingface_fallback_pages_failed"], 1)
        self.assertEqual(aggregate["v2_huggingface_empty_candidate_pages"], 1)
        self.assertEqual(aggregate["v2_huggingface_parser_recovered_candidates"], 2)
        self.assertEqual(aggregate["v2_huggingface_raw_response_preview_count"], 3)

    def test_missing_huggingface_page_metrics_default_safely(self):
        comparison = compare_reports(reference_report(), v2_mixed_provider_report(include_hf_metrics=False))
        aggregate = comparison["aggregate_metrics"]
        self.assertEqual(aggregate["v2_huggingface_fallback_pages_attempted"], 0)
        self.assertEqual(aggregate["v2_huggingface_empty_candidate_pages"], 0)
        self.assertEqual(aggregate["v2_huggingface_parser_failed_pages"], 0)

    def test_benchmark_completion_assessment_reports_signal_coverage(self):
        comparison = compare_reports(reference_report(), v2_mixed_provider_report(include_openai=False))
        assessment = comparison["benchmark_completion_assessment"]
        self.assertTrue(assessment["benchmark_complete"])
        self.assertEqual(assessment["cases_with_numeric_signal"], 1)
        self.assertEqual(assessment["cases_with_text_block_signal"], 1)
        self.assertEqual(assessment["cases_missing_numeric_signal"], [])
        self.assertEqual(assessment["cases_missing_text_block_signal"], [])
        self.assertTrue(assessment["full_hf_benchmark_successful"])

    def test_missing_signal_case_lists_are_reported(self):
        comparison = compare_reports(reference_report(), v2_headings_only_report())
        assessment = comparison["benchmark_completion_assessment"]
        self.assertFalse(assessment["benchmark_complete"])
        self.assertEqual(assessment["cases_missing_numeric_signal"], ["case-a"])
        self.assertEqual(assessment["cases_missing_text_block_signal"], ["case-a"])

    def test_closeout_markdown_renders_final_benchmark_metrics(self):
        comparison = compare_reports(reference_report(), v2_mixed_provider_report())
        closeout = build_huggingface_qwen_closeout_report(
            reference_report_path=Path("reports/reference.json"),
            extraction_report_path=Path("reports/extraction.json"),
            comparison_report_path=Path("reports/comparison.json"),
            checkpoint_path=Path("reports/checkpoints/checkpoint.json"),
            v2_report=v2_mixed_provider_report(),
            comparison_report=comparison,
            output_json=Path("reports/huggingface_qwen_benchmark_closeout_13q.json"),
        )
        markdown = render_closeout_markdown(closeout)
        self.assertIn("Total candidates: 4", markdown)
        self.assertIn("Hugging Face candidates: 2", markdown)
        self.assertIn("Native-only candidates: 1", markdown)

    def test_safety_metadata_remains_false(self):
        comparison = compare_reports(reference_report(), v2_mixed_provider_report())
        self.assertFalse(comparison["run_metadata"]["database_mutated"])
        self.assertFalse(comparison["run_metadata"]["xbrl_generated"])
        self.assertFalse(comparison["run_metadata"]["arelle_validation_run"])


if __name__ == "__main__":
    unittest.main()
