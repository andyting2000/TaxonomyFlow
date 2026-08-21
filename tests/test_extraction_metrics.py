import unittest
from types import SimpleNamespace

from scripts.extraction_metrics import calculate_job_metrics, render_console_report


def item(
    label,
    value,
    *,
    previous_value=None,
    statement_type="Statement of Financial Position",
    template_field_id="ifrs-smes:Cash",
    is_reviewed=False,
    confirmed_tag_id=None,
):
    return SimpleNamespace(
        extracted_label=label,
        extracted_value=value,
        value_previous_year=previous_value,
        statement_type=statement_type,
        template_field_id=template_field_id,
        is_reviewed=is_reviewed,
        confirmed_tag_id=confirmed_tag_id,
    )


class ExtractionMetricsTests(unittest.TestCase):
    def test_calculate_job_metrics_counts_baseline_fields(self):
        job = SimpleNamespace(
            id=3,
            company_name="Example Sdn Bhd",
            status="REVIEW",
            pages=[
                SimpleNamespace(
                    page_number=1,
                    extracted_items=[
                        item("Cash", "100", is_reviewed=True),
                        item("Cash", "100", confirmed_tag_id=7),
                        item("Inventory", "(50)", statement_type="", template_field_id=None),
                    ],
                ),
                SimpleNamespace(
                    page_number=2,
                    extracted_items=[
                        item("Cash", "-25", template_field_id=""),
                    ],
                ),
            ],
        )

        metrics = calculate_job_metrics(job)

        self.assertEqual(metrics["total_extracted_rows"], 4)
        self.assertEqual(metrics["rows_with_template_field_id"], 2)
        self.assertEqual(metrics["rows_without_template_field_id"], 2)
        self.assertEqual(metrics["rows_with_blank_statement_type"], 1)
        self.assertEqual(metrics["duplicate_label_count"], 2)
        self.assertEqual(metrics["duplicate_label_value_count"], 1)
        self.assertEqual(metrics["suspicious_signed_value_count"], 2)
        self.assertEqual(metrics["reviewed_count"], 1)
        self.assertEqual(metrics["tagged_count"], 1)
        self.assertEqual(metrics["reviewed_or_tagged_count"], 2)

    def test_render_console_report_lists_missing_jobs(self):
        report = render_console_report([], [99])

        self.assertIn("No requested jobs were found.", report)
        self.assertIn("Missing jobs:", report)
        self.assertIn("  - 99", report)


if __name__ == "__main__":
    unittest.main()
