import unittest

from scripts.compare_azure_di_vs_hf_qwen import compare_reports, render_markdown


def candidate(row_type="numeric_fact", label="Cash", value="100", **overrides):
    base = {
        "case_id": "case-a",
        "source_pdf": "case-a.pdf",
        "page_number": 1,
        "source_method": "azure_document_intelligence",
        "extraction_method": "azure_document_intelligence",
        "row_type": row_type,
        "statement_section": "Statement of Financial Position",
        "label": label,
        "value": value,
        "previous_value": None,
        "text": None,
        "source_snippet": f"{label} {value}",
        "provenance": {"page_number": 1},
    }
    base.update(overrides)
    return base


def report(candidates, *, provider="azure", runtime=True):
    aggregate = {
        "total_candidate_rows": len(candidates),
        "azure_di_tables_detected": 1 if provider == "azure" else 0,
        "azure_di_pages_processed": 2 if provider == "azure" else 0,
        "estimated_pages_billable": 2 if provider == "azure" else 0,
        "average_seconds_per_page": 1.5 if runtime else None,
        "total_runtime_seconds": 3.0 if runtime else None,
    }
    return {
        "run_metadata": {"database_mutated": False},
        "aggregate_metrics": aggregate,
        "case_reports": [
            {
                "case_id": "case-a",
                "pages_analyzed": 2,
                "azure_di_tables_detected": 1 if provider == "azure" else 0,
                "azure_di_runtime_seconds": 3.0 if runtime else None,
                "candidates": candidates,
            }
        ],
    }


def reference_report():
    return {
        "aggregate_metrics": {"total_facts": 2, "numeric_fact_count": 1, "text_block_count": 1},
        "case_reports": [
            {
                "case_id": "case-a",
                "total_facts": 2,
                "numeric_fact_count": 1,
                "text_block_count": 1,
                "facts": [
                    {"local_name": "CashAndBankBalances", "is_numeric": True},
                    {"local_name": "DisclosureOfDirectorsReport", "is_text_block": True},
                ],
            }
        ],
    }


class CompareAzureDIVsHFQwenTests(unittest.TestCase):
    def test_comparison_counts_azure_di_and_hf_candidates_separately(self):
        azure = report([candidate(), candidate(row_type="text_block", label="Directors report", value="", text="Directors report narrative text.")])
        hf = report([candidate(label="Revenue")], provider="hf")
        comparison = compare_reports(azure_report=azure, hf_report=hf, reference_report=reference_report())
        self.assertEqual(comparison["aggregate_comparison"]["azure_di"]["total_candidates"], 2)
        self.assertEqual(comparison["aggregate_comparison"]["hf_qwen"]["total_candidates"], 1)

    def test_missing_numeric_text_block_signal_is_reported_by_case(self):
        azure = report([])
        hf = report([candidate(label="Revenue")], provider="hf")
        comparison = compare_reports(azure_report=azure, hf_report=hf, reference_report=reference_report())
        self.assertIn("case-a", comparison["aggregate_comparison"]["azure_di"]["missing_numeric_or_text_cases"])
        self.assertTrue(comparison["per_case"][0]["missing_numeric_signal"])

    def test_runtime_per_page_metrics_are_included(self):
        comparison = compare_reports(
            azure_report=report([candidate()]),
            hf_report=report([candidate(label="Revenue")], provider="hf"),
            reference_report=reference_report(),
        )
        self.assertEqual(comparison["aggregate_comparison"]["azure_di"]["average_seconds_per_page"], 1.5)
        self.assertEqual(comparison["aggregate_comparison"]["azure_di"]["estimated_billable_pages"], 2)

    def test_recommendation_logic_handles_azure_better_worse_and_mixed_cases(self):
        better = compare_reports(
            azure_report=report(
                [
                    candidate(label="Cash"),
                    candidate(label="Revenue"),
                    candidate(row_type="text_block", label="Directors report", value="", text="Directors report narrative text."),
                ]
            ),
            hf_report=report([candidate(label="Cash")], provider="hf"),
            reference_report=reference_report(),
        )
        self.assertIn(better["recommendation"]["recommended_role"], {"primary extraction source", "OCR/layout preprocessor before Qwen cleanup"})
        worse = compare_reports(
            azure_report=report([]),
            hf_report=report([candidate(label="Cash")], provider="hf"),
            reference_report=reference_report(),
        )
        self.assertEqual(worse["recommendation"]["recommended_role"], "not recommended yet")
        mixed = compare_reports(
            azure_report=report([candidate(label="Cash")]),
            hf_report=report([candidate(label="Cash"), candidate(label="Revenue")], provider="hf"),
            reference_report=reference_report(),
        )
        self.assertIn(mixed["recommendation"]["recommended_role"], {"fallback only", "OCR/layout preprocessor before Qwen cleanup"})

    def test_markdown_comparison_renders_summary(self):
        comparison = compare_reports(
            azure_report=report([candidate()]),
            hf_report=report([candidate(label="Revenue")], provider="hf"),
            reference_report=reference_report(),
        )
        markdown = render_markdown(comparison)
        self.assertIn("Azure DI vs HF Qwen Comparison", markdown)
        self.assertIn("Recommended role", markdown)

    def test_no_live_model_call_is_required_for_comparison_tests(self):
        comparison = compare_reports(
            azure_report=report([candidate()]),
            hf_report=report([candidate(label="Revenue")], provider="hf"),
            reference_report=reference_report(),
        )
        self.assertFalse(comparison["run_metadata"]["live_model_calls"])
        self.assertFalse(comparison["run_metadata"]["external_provider_calls"])


if __name__ == "__main__":
    unittest.main()
