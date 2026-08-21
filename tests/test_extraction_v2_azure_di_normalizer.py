import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.extraction_v2_azure_di_normalizer import (
    normalize_azure_di_extraction_report,
    render_normalization_summary_markdown,
    run_azure_di_normalization,
)


def candidate(row_type, label, **overrides):
    payload = {
        "case_id": "case-a",
        "source_pdf": "sample.pdf",
        "pdf_filename": "sample.pdf",
        "page_number": overrides.pop("page_number", 1),
        "source_method": "azure_document_intelligence",
        "extraction_method": "azure_document_intelligence",
        "model_id": "prebuilt-layout",
        "row_type": row_type,
        "statement_section": overrides.pop("statement_section", "Statement of Financial Position"),
        "label": label,
        "value": overrides.pop("value", None),
        "previous_value": overrides.pop("previous_value", None),
        "current_year": overrides.pop("current_year", None),
        "prior_year": overrides.pop("prior_year", None),
        "text": overrides.pop("text", None),
        "source_snippet": overrides.pop("source_snippet", label),
        "confidence": overrides.pop("confidence", 0.75),
        "warnings": overrides.pop("warnings", []),
        "provenance": overrides.pop("provenance", {}),
    }
    payload.update(overrides)
    return payload


def sample_report(candidates):
    counts = {}
    for item in candidates:
        counts[item["row_type"]] = counts.get(item["row_type"], 0) + 1
    return {
        "run_metadata": {
            "feature": "13X",
            "report_type": "azure_di_sandbox_extraction_v2",
            "provider": "azure_document_intelligence",
            "model_id": "prebuilt-layout",
            "database_mutated": False,
            "production_behavior_changed": False,
            "reference_xml_sent_to_provider": False,
        },
        "pipeline_name": "Azure DI-first Extraction v2 Sandbox",
        "aggregate_metrics": {
            "total_candidates": len(candidates),
            "total_candidate_rows": len(candidates),
            "row_type_counts": counts,
        },
        "case_reports": [
            {
                "case_id": "case-a",
                "source_pdf": "sample.pdf",
                "candidate_count": len(candidates),
                "row_type_counts": counts,
                "candidates": candidates,
            }
        ],
        "sample_candidates": candidates[:3],
    }


class ExtractionV2AzureDINormalizerTests(unittest.TestCase):
    def normalize(self, candidates):
        report, summary = normalize_azure_di_extraction_report(sample_report(candidates), run_id="test")
        rows = report["case_reports"][0]["candidates"]
        audit = report["normalization"]["candidate_audit_trail"]
        return report, summary, rows, audit

    def test_table_of_contents_row_is_suppressed_or_downgraded_and_not_mapping_ready(self):
        report, _summary, rows, audit = self.normalize(
            [candidate("metadata", "1. DIRECTORS' REPORT 1-4", statement_section="Index / Contents")]
        )
        self.assertEqual(rows, [])
        self.assertEqual(audit[0]["action"], "suppress_index_or_toc_row")
        self.assertEqual(report["normalization"]["index_toc_rows_suppressed"], 1)

    def test_page_number_row_is_downgraded_to_metadata_context(self):
        _report, _summary, rows, audit = self.normalize([candidate("heading", "Page No.", page_number=1)])
        self.assertEqual(rows, [])
        self.assertEqual(audit[0]["action"], "suppress_index_or_toc_row")

    def test_repeated_company_header_is_downgraded_to_metadata_context(self):
        candidates = [
            candidate("metadata", "SHIELD PLUS SDN. BHD. (Incorporated in Malaysia)", page_number=page)
            for page in [1, 2, 3]
        ]
        _report, _summary, rows, audit = self.normalize(candidates)
        self.assertEqual(rows, [])
        self.assertTrue(all(entry["action"] == "keep_for_context_only" for entry in audit))

    def test_useful_section_heading_is_preserved_for_section_inheritance(self):
        _report, _summary, rows, audit = self.normalize(
            [candidate("heading", "DIRECTORS' REPORT", statement_section=None)]
        )
        self.assertEqual(rows[0]["row_type"], "heading")
        self.assertEqual(rows[0]["statement_section"], "Directors Report")
        self.assertEqual(audit[0]["action"], "keep")

    def test_directors_report_narrative_paragraph_remains_text_block(self):
        _report, _summary, rows, _audit = self.normalize(
            [
                candidate("heading", "DIRECTORS' REPORT", page_number=2, provenance={"paragraph_index": 1}),
                candidate(
                    "text_block",
                    "Notes to the Financial Statements",
                    page_number=2,
                    text="The Directors hereby submit their report and the audited financial statements for the year.",
                    source_snippet="The Directors hereby submit their report and the audited financial statements for the year.",
                    provenance={"paragraph_index": 2},
                ),
            ]
        )
        text_blocks = [item for item in rows if item["row_type"] == "text_block"]
        self.assertEqual(text_blocks[0]["statement_section"], "Directors Report")
        self.assertIn("The Directors hereby", text_blocks[0]["label"])

    def test_index_entry_is_not_converted_to_text_block(self):
        _report, _summary, rows, audit = self.normalize(
            [candidate("text_block", "INDEX", text="4. STATEMENT OF FINANCIAL POSITION 6", page_number=1)]
        )
        self.assertEqual(rows, [])
        self.assertEqual(audit[0]["action"], "suppress_index_or_toc_row")

    def test_adjacent_short_narrative_fragments_in_same_section_can_merge(self):
        text1 = "The Company is principally engaged in insurance brokerage:"
        text2 = "and related agency services during the financial year."
        _report, _summary, rows, audit = self.normalize(
            [
                candidate("text_block", "Directors Report", text=text1, source_snippet=text1, page_number=2, statement_section="Directors Report", provenance={"paragraph_index": 1}),
                candidate("text_block", "Directors Report", text=text2, source_snippet=text2, page_number=2, statement_section="Directors Report", provenance={"paragraph_index": 2}),
            ]
        )
        self.assertEqual(len([item for item in rows if item["row_type"] == "text_block"]), 1)
        self.assertIn("related agency", rows[0]["text"])
        self.assertIn("merge_text_block_fragment", [entry["action"] for entry in audit])

    def test_text_blocks_across_different_sections_are_not_merged(self):
        _report, _summary, rows, _audit = self.normalize(
            [
                candidate("text_block", "Directors Report", text="The Directors submit their report:", page_number=2, statement_section="Directors Report", provenance={"paragraph_index": 1}),
                candidate("text_block", "Statutory Declaration", text="I make this solemn declaration for the financial statements.", page_number=2, statement_section="Statutory Declaration", provenance={"paragraph_index": 2}),
            ]
        )
        self.assertEqual(len([item for item in rows if item["row_type"] == "text_block"]), 2)

    def test_row_with_one_amount_remains_numeric_fact(self):
        _report, _summary, rows, _audit = self.normalize(
            [candidate("numeric_fact", "Cash", value="1,234", provenance={"table_index": 0, "row_index": 1, "cell_indexes": [0, 1]})]
        )
        self.assertEqual(rows[0]["row_type"], "numeric_fact")

    def test_row_with_two_year_values_becomes_comparative_numeric_fact(self):
        _report, _summary, rows, audit = self.normalize(
            [candidate("numeric_fact", "Cash", value="1,234", previous_value="1,000")]
        )
        self.assertEqual(rows[0]["row_type"], "comparative_numeric_fact")
        self.assertEqual(audit[0]["action"], "convert_numeric_to_comparative")

    def test_percentage_only_column_is_not_treated_as_prior_year_value(self):
        _report, _summary, rows, _audit = self.normalize(
            [
                candidate(
                    "comparative_numeric_fact",
                    "Gross profit",
                    value="1,234",
                    previous_value="25%",
                    provenance={"percentage_cells": ["25%"]},
                )
            ]
        )
        self.assertEqual(rows[0]["row_type"], "numeric_fact")
        self.assertIsNone(rows[0]["previous_value"])

    def test_total_subtotal_row_is_classified_as_subtotal_or_total(self):
        _report, _summary, rows, _audit = self.normalize([candidate("numeric_fact", "Total assets", value="400")])
        self.assertEqual(rows[0]["row_type"], "subtotal_or_total")

    def test_account_code_column_is_preserved_as_provenance_code(self):
        _report, _summary, rows, _audit = self.normalize(
            [candidate("numeric_fact", "Cash", value="1,234", provenance={"account_code": "AFF-1103"})]
        )
        self.assertEqual(rows[0]["provenance"]["account_code"], "AFF-1103")

    def test_negative_amount_is_preserved(self):
        _report, _summary, rows, _audit = self.normalize([candidate("numeric_fact", "Loss", value="(1,234)")])
        self.assertEqual(rows[0]["value"], "(1,234)")

    def test_year_only_label_is_downgraded_or_marked_context(self):
        _report, _summary, rows, audit = self.normalize([candidate("numeric_fact", "2024", value="1,234")])
        self.assertEqual(rows[0]["row_type"], "metadata")
        self.assertEqual(audit[0]["action"], "downgrade_to_metadata")

    def test_heading_like_numeric_fact_is_converted_or_downgraded(self):
        _report, _summary, rows, audit = self.normalize([candidate("numeric_fact", "STATEMENT OF FINANCIAL POSITION")])
        self.assertEqual(rows[0]["row_type"], "heading")
        self.assertEqual(audit[0]["action"], "convert_heading_like_fact_to_heading")

    def test_candidate_audit_trail_preserves_original_candidate_id(self):
        _report, _summary, _rows, audit = self.normalize([candidate("heading", "DIRECTORS' REPORT")])
        self.assertEqual(audit[0]["original_candidate_id"], "case-a:candidate:0:0")

    def test_normalized_report_includes_before_after_counts(self):
        report, _summary, _rows, _audit = self.normalize(
            [candidate("heading", "INDEX", page_number=1), candidate("text_block", "Directors Report", text="The directors submit their report for the year.", statement_section="Directors Report")]
        )
        self.assertIn("before_row_type_counts", report["normalization"])
        self.assertIn("after_row_type_counts", report["normalization"])

    def test_no_azure_di_call_is_required(self):
        with patch("services.azure_document_intelligence_provider.AzureDocumentIntelligenceProvider.analyze_pdf_path") as mocked:
            self.normalize([candidate("numeric_fact", "Cash", value="1")])
        mocked.assert_not_called()

    def test_no_hugging_face_or_openai_call_is_required(self):
        report, _summary, _rows, _audit = self.normalize([candidate("numeric_fact", "Cash", value="1")])
        metadata = report["run_metadata"]
        self.assertFalse(metadata["live_huggingface_calls_made"])
        self.assertFalse(metadata["live_openai_calls_made"])

    def test_no_db_is_required(self):
        report, _summary, _rows, _audit = self.normalize([candidate("numeric_fact", "Cash", value="1")])
        self.assertFalse(report["run_metadata"]["database_mutated"])

    def test_markdown_summary_renders(self):
        report, summary = normalize_azure_di_extraction_report(
            sample_report([candidate("numeric_fact", "Cash", value="1")])
        )
        summary["before_after"]["mapping_handoff_candidates"] = {"before": 0, "after": 1, "delta": 1}
        text = render_normalization_summary_markdown(summary)
        self.assertIn("Azure DI Normalization Summary", text)

    def test_runner_writes_reports_without_live_calls_when_gates_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "input.json"
            input_path.write_text(json.dumps(sample_report([candidate("numeric_fact", "Cash", value="1")])), encoding="utf-8")
            result = run_azure_di_normalization(
                azure_di_report_path=input_path,
                output_prefix=root / "out",
                skip_gates=True,
            )
            self.assertTrue(result["paths"].extraction_json.exists())
            self.assertTrue(result["paths"].summary_json.exists())
            self.assertFalse(result["normalized_report"]["run_metadata"]["live_external_provider_call"])


if __name__ == "__main__":
    unittest.main()
