import unittest
from pathlib import Path

from scripts.compare_extraction_pipelines import (
    build_comparison_report,
    duplicate_excess_count,
    normalize_label,
    normalize_value,
    render_markdown,
    summarize_rows,
)


class CompareExtractionPipelinesTests(unittest.TestCase):
    def test_duplicate_counting(self):
        self.assertEqual(duplicate_excess_count(["cash", "cash", "bank"]), 1)
        self.assertEqual(duplicate_excess_count(["cash", "cash", "cash"]), 2)

    def test_normalization(self):
        self.assertEqual(normalize_label(" Cash  and  Bank "), "cash and bank")
        self.assertEqual(normalize_value("RM 1,234"), "1234")
        self.assertEqual(normalize_value("(1,234)"), "-1234")

    def test_summarize_rows(self):
        rows = [
            {"label": "Cash", "value": "1,000", "row_type": "numeric_fact", "statement_hint": "SFP"},
            {"label": "Cash", "value": "1,000", "row_type": "numeric_fact", "statement_hint": "SFP"},
            {"label": "Policy", "value": "Long disclosure", "row_type": "text_block", "statement_hint": "Notes"},
        ]
        summary = summarize_rows(rows, source="shadow")
        self.assertEqual(summary["row_count"], 3)
        self.assertEqual(summary["duplicate_label_count"], 1)
        self.assertEqual(summary["duplicate_label_value_count"], 1)
        self.assertEqual(summary["row_type_counts"]["numeric_fact"], 2)

    def test_comparison_summary_generation(self):
        production_rows = [
            {
                "job_id": 13,
                "label": "Cash and bank balances",
                "value": "1,234",
                "statement_type": "Statement of Financial Position",
                "template_field_id": "ifrs-smes:CashAndCashEquivalents",
                "confirmed_tag_id": None,
            },
            {
                "job_id": 13,
                "label": "Inventory",
                "value": "2,000",
                "statement_type": "Statement of Financial Position",
                "template_field_id": None,
                "confirmed_tag_id": None,
            },
        ]
        shadow_rows = [
            {
                "job_id": 13,
                "label": "Cash and bank balances",
                "value": "RM 1,234",
                "row_type": "numeric_fact",
                "statement_hint": "Statement of Financial Position",
                "warnings": [],
            },
            {
                "job_id": 13,
                "label": "Revenue",
                "value": "(500)",
                "row_type": "numeric_fact",
                "statement_hint": "Statement of Comprehensive Income",
                "warnings": ["possible_sign_issue"],
            },
        ]

        report = build_comparison_report(
            [13],
            production_rows,
            shadow_rows,
            shadow_report_path="reports/shadow.json",
            output_json=Path("reports/comparison.json"),
        )

        self.assertTrue(report["run_metadata"]["read_only"])
        self.assertFalse(report["run_metadata"]["database_mutated"])
        self.assertEqual(report["aggregate_metrics"]["production_row_count"], 2)
        self.assertEqual(report["aggregate_metrics"]["shadow_row_count"], 2)
        self.assertEqual(report["aggregate_metrics"]["production_mapped_rows"], 1)
        self.assertEqual(report["job_comparisons"][0]["normalized_label_overlap_count"], 1)
        self.assertEqual(report["job_comparisons"][0]["normalized_label_value_overlap_count"], 1)
        self.assertIn("shadow_possible_sign_issues_present", report["job_comparisons"][0]["top_high_risk_differences"])

    def test_markdown_rendering(self):
        report = build_comparison_report(
            [13],
            [],
            [],
            shadow_report_path="reports/shadow.json",
            output_json=Path("reports/comparison.json"),
        )
        markdown = render_markdown(report)
        self.assertIn("Pipeline Side-by-Side Comparison", markdown)
        self.assertIn("| Job | Production Rows | Shadow Rows |", markdown)


if __name__ == "__main__":
    unittest.main()
