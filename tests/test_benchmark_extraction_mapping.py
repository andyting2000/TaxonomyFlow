import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from scripts.benchmark_extraction_mapping import (
    aggregate_metrics,
    build_benchmark_report,
    calculate_job_metrics,
    duplicate_excess_count,
    has_suspicious_signed_value,
    render_markdown,
)


def item(
    label,
    value,
    *,
    statement_type="Statement of Financial Position",
    template_field_id="ssmt:TotalAssets",
    confirmed_tag_id=None,
    reviewed=True,
    previous_value=None,
    financial_year=2024,
    financial_year_previous=2023,
):
    return SimpleNamespace(
        extracted_label=label,
        extracted_value=value,
        statement_type=statement_type,
        template_field_id=template_field_id,
        confirmed_tag_id=confirmed_tag_id,
        confirmed_tag=None,
        is_reviewed=reviewed,
        value_previous_year=previous_value,
        financial_year=financial_year,
        financial_year_previous=financial_year_previous,
    )


def job(job_id, items):
    page = SimpleNamespace(page_number=1, extracted_items=items)
    return SimpleNamespace(
        id=job_id,
        company_name=f"Company {job_id}",
        registration_number="123",
        financial_year_end="2024-12-31",
        status="REVIEW",
        uploaded_at="2026-05-05T00:00:00",
        updated_at=None,
        source_pdf_path="uploads/pdfs/sample.pdf",
        pages=[page],
    )


class BenchmarkExtractionMappingTests(unittest.TestCase):
    def test_duplicate_excess_count(self):
        self.assertEqual(duplicate_excess_count(["cash", "cash", "bank"]), 1)
        self.assertEqual(duplicate_excess_count(["cash", "cash", "cash"]), 2)

    def test_suspicious_sign_helper(self):
        self.assertTrue(has_suspicious_signed_value(item("Loss", "(1,000)")))
        self.assertTrue(has_suspicious_signed_value(item("Loss", "-1000")))
        self.assertFalse(has_suspicious_signed_value(item("Revenue", "1000")))

    def test_calculate_job_metrics(self):
        metric = calculate_job_metrics(
            job(
                11,
                [
                    item("Cash", "1,000", template_field_id="ssmt:CashAndBankBalances"),
                    item("Cash", "1,000", template_field_id="ssmt:CashAndBankBalances"),
                    item("ACME Sdn Bhd", "(500)", template_field_id=None, reviewed=False),
                ],
            )
        )
        self.assertEqual(metric["extraction_metrics"]["total_extracted_rows"], 3)
        self.assertEqual(metric["mapping_metrics"]["unmapped_rows"], 1)
        self.assertGreater(metric["data_quality_metrics"]["duplicate_label_count"], 0)
        self.assertEqual(metric["data_quality_metrics"]["rows_with_company_name_like_labels"], 1)
        self.assertEqual(metric["data_quality_metrics"]["suspicious_signed_value_count"], 1)

    def test_job_9_smoke_labeling(self):
        metric = calculate_job_metrics(job(9, [item("Cash", "1")]), include_job_9=True)
        self.assertEqual(metric["job_metadata"]["job_role"], "smoke_test_only")

    def test_report_schema_and_missing_jobs(self):
        metric = calculate_job_metrics(job(11, [item("Cash", "1")]))
        report = build_benchmark_report(
            selected_jobs=[9, 11, 999999],
            per_job_metrics=[metric],
            missing_jobs=[999999],
            include_job_9=False,
            with_xbrl_audit=False,
            with_arelle_baseline=False,
            output_path=Path("reports/example.json"),
        )
        self.assertTrue(report["run_metadata"]["read_only"])
        self.assertFalse(report["run_metadata"]["database_mutated"])
        self.assertIn("missing_jobs", report)
        self.assertEqual(report["missing_jobs"], [999999])
        self.assertIn("Job 9", report["job_9_policy"])
        self.assertIn("benchmark_dataset_policy", report)

    def test_aggregate_metrics(self):
        metrics = [
            calculate_job_metrics(job(11, [item("Cash", "1"), item("Blank", "", template_field_id=None)])),
            calculate_job_metrics(job(12, [item("Revenue", "2", confirmed_tag_id=1)])),
        ]
        aggregate = aggregate_metrics(metrics)
        self.assertEqual(aggregate["total_jobs_analyzed"], 2)
        self.assertEqual(aggregate["total_rows"], 3)
        self.assertIn("average_template_field_coverage", aggregate)

    def test_markdown_rendering(self):
        metric = calculate_job_metrics(job(9, [item("Cash", "1")]), include_job_9=True)
        report = build_benchmark_report(
            selected_jobs=[9],
            per_job_metrics=[metric],
            missing_jobs=[],
            include_job_9=True,
            with_xbrl_audit=False,
            with_arelle_baseline=False,
            output_path=Path("reports/example.json"),
        )
        markdown = render_markdown(report)
        self.assertIn("Job 9 is included only as a smoke-test", markdown)
        self.assertIn("| Job | Role | Status |", markdown)

    def test_report_json_serializable(self):
        metric = calculate_job_metrics(job(11, [item("Cash", "1")]))
        report = build_benchmark_report(
            selected_jobs=[11],
            per_job_metrics=[metric],
            missing_jobs=[],
            include_job_9=False,
            with_xbrl_audit=False,
            with_arelle_baseline=False,
            output_path=Path("reports/example.json"),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            loaded = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(loaded["aggregate_metrics"]["total_jobs_analyzed"], 1)


if __name__ == "__main__":
    unittest.main()
