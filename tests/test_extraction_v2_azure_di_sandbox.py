import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.extraction_v2_azure_di_sandbox import (
    APPROVAL_MESSAGE,
    AzureDISandboxApprovalError,
    build_dry_run_plan,
    build_quality_gate_reports,
    output_paths_from_prefix,
    render_summary_markdown,
    run_azure_di_sandbox,
)


def azure_result(rows=None, paragraphs=None, *, content="Statement of Financial Position", tables=True):
    rows = rows or [["Description", "2024"], ["Cash and bank balances", "1,234"]]
    paragraphs = paragraphs or []
    cells = []
    if tables:
        for row_index, row in enumerate(rows):
            for col_index, value in enumerate(row):
                cells.append(
                    {
                        "content": value,
                        "row_index": row_index,
                        "column_index": col_index,
                        "page_number": 1,
                        "bounding_regions": [{"page_number": 1, "polygon": [1, 2, 3, 4]}],
                    }
                )
    return {
        "ok": True,
        "provider": "azure_document_intelligence",
        "model_id": "prebuilt-layout",
        "source_pdf": "sample.pdf",
        "runtime_seconds": 1.25,
        "pages_count": 1,
        "content_length": len(content),
        "content": content,
        "pages": [{"page_number": 1}],
        "lines": [{"content": content, "page_number": 1}],
        "words": [],
        "paragraphs": [
            {"paragraph_index": index, "content": text, "page_number": 1, "bounding_regions": [{"page_number": 1}]}
            for index, text in enumerate(paragraphs)
        ],
        "tables": [
            {
                "table_index": 0,
                "row_count": len(rows),
                "column_count": len(rows[0]),
                "page_numbers": [1],
                "cells": cells,
            }
        ]
        if tables
        else [],
        "table_cells": cells,
        "warnings": [],
        "errors": [],
        "reference_xml_sent_to_provider": False,
    }


class FakeProvider:
    endpoint = "https://example.cognitiveservices.azure.com/"
    key = "secret-key"
    model_id = "prebuilt-layout"

    def __init__(self, result=None):
        self.result = result or azure_result()
        self.calls = []

    def analyze_pdf_path(self, pdf_path, pages=None):
        self.calls.append({"pdf_path": str(pdf_path), "pages": pages})
        return self.result


def create_pdf(directory: Path, name="sample.pdf") -> Path:
    path = directory / name
    path.write_bytes(b"%PDF-1.4 fake")
    return path


class ExtractionV2AzureDISandboxTests(unittest.TestCase):
    def run_sandbox(self, provider=None, *, result=None, skip_quality_gates=True):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        pdf = create_pdf(root)
        provider = provider or FakeProvider(result=result)
        output_prefix = root / "azure_di_sandbox"
        return root, provider, run_azure_di_sandbox(
            pdf=pdf,
            output_prefix=output_prefix,
            approve_azure_document_intelligence_upload=True,
            skip_quality_gates=skip_quality_gates,
            provider=provider,
            run_id="test-run",
        )

    def test_dry_run_does_not_call_azure_di(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = create_pdf(Path(tmp))
            plan = build_dry_run_plan(pdf=pdf, output_prefix=Path(tmp) / "out")
        self.assertFalse(plan["would_call_azure_document_intelligence"])
        self.assertFalse(plan["run_metadata"]["live_external_provider_call"])

    def test_missing_approval_flag_blocks_live_azure_di_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = create_pdf(Path(tmp))
            provider = FakeProvider()
            with self.assertRaises(AzureDISandboxApprovalError) as ctx:
                run_azure_di_sandbox(pdf=pdf, provider=provider)
        self.assertIn(APPROVAL_MESSAGE, str(ctx.exception))
        self.assertEqual(provider.calls, [])

    def test_approval_flag_allows_mocked_azure_di_call(self):
        _root, provider, result = self.run_sandbox()
        self.assertEqual(len(provider.calls), 1)
        self.assertTrue(result["extraction_report"]["run_metadata"]["approval_flag_used"])

    def test_single_pdf_input_is_accepted(self):
        _root, _provider, result = self.run_sandbox()
        self.assertEqual(result["extraction_report"]["aggregate_metrics"]["total_pdfs_processed"], 1)

    def test_case_dir_input_discovers_one_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp) / "007-Shield-Plus"
            case_dir.mkdir()
            create_pdf(case_dir, "Shield-Plus.pdf")
            provider = FakeProvider()
            result = run_azure_di_sandbox(
                case_dir=case_dir,
                output_prefix=Path(tmp) / "out",
                approve_azure_document_intelligence_upload=True,
                skip_quality_gates=True,
                provider=provider,
            )
        self.assertEqual(result["extraction_report"]["input"]["case_id"], "007-Shield-Plus")

    def test_sandbox_extraction_report_contains_provider_model_pages_tables_candidate_counts(self):
        _root, _provider, result = self.run_sandbox()
        report = result["extraction_report"]
        self.assertEqual(report["run_metadata"]["provider"], "azure_document_intelligence")
        self.assertEqual(report["run_metadata"]["model_id"], "prebuilt-layout")
        self.assertEqual(report["aggregate_metrics"]["pages_processed"], 1)
        self.assertEqual(report["aggregate_metrics"]["tables_detected"], 1)
        self.assertEqual(report["aggregate_metrics"]["total_candidates"], 1)

    def test_candidate_provenance_includes_page_table_row_cell_for_table_candidates(self):
        _root, _provider, result = self.run_sandbox()
        candidate = result["extraction_report"]["case_reports"][0]["candidates"][0]
        self.assertEqual(candidate["page_number"], 1)
        self.assertEqual(candidate["provenance"]["table_index"], 0)
        self.assertEqual(candidate["provenance"]["row_index"], 1)
        self.assertIn(1, candidate["provenance"]["cell_indexes"])

    def test_narrative_paragraph_can_become_text_block(self):
        result = azure_result(
            rows=[["Description", "2024"], ["Cash", "1,000"]],
            paragraphs=[
                "Directors' Report",
                "The directors hereby submit their report and the audited financial statements for the financial year ended 31 December 2024.",
            ],
        )
        _root, _provider, sandbox = self.run_sandbox(result=result)
        candidates = sandbox["extraction_report"]["case_reports"][0]["candidates"]
        self.assertTrue(any(item["row_type"] == "text_block" for item in candidates))

    def test_table_of_contents_rows_are_not_mapping_ready_financial_facts(self):
        result = azure_result(rows=[["Contents", "Page"], ["Directors' Report", "2"]], content="Contents Page")
        _root, _provider, sandbox = self.run_sandbox(result=result)
        candidates = sandbox["extraction_report"]["case_reports"][0]["candidates"]
        self.assertFalse([item for item in candidates if item["row_type"] in {"numeric_fact", "comparative_numeric_fact"}])

    def test_quality_gate_stage_can_be_skipped(self):
        _root, _provider, result = self.run_sandbox(skip_quality_gates=True)
        self.assertEqual(result["gate_reports"]["quality"]["status"], "skipped")
        self.assertTrue(result["summary_report"]["summary"]["quality_gates_skipped"])

    def test_quality_gate_stage_writes_clear_limitation_if_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = output_paths_from_prefix(Path(tmp) / "out")
            extraction = {
                "run_metadata": {"database_mutated": False},
                "case_reports": [{"case_id": "case-a", "candidates": []}],
            }
            with patch(
                "services.extraction_v2_azure_di_sandbox.analyze_candidate_quality_reports",
                side_effect=RuntimeError("not supported"),
            ):
                reports = build_quality_gate_reports(extraction, paths=paths)
        self.assertEqual(reports["quality"]["status"], "limitation")
        self.assertIn("could not consume", reports["quality"]["limitation"])

    def test_database_mutated_false(self):
        _root, _provider, result = self.run_sandbox()
        self.assertFalse(result["extraction_report"]["run_metadata"]["database_mutated"])
        self.assertFalse(result["summary_report"]["run_metadata"]["database_mutated"])

    def test_production_behavior_changed_false(self):
        _root, _provider, result = self.run_sandbox()
        self.assertFalse(result["extraction_report"]["run_metadata"]["production_behavior_changed"])

    def test_reference_xml_sent_to_provider_false(self):
        _root, _provider, result = self.run_sandbox()
        self.assertFalse(result["extraction_report"]["run_metadata"]["reference_xml_sent_to_provider"])

    def test_live_external_provider_call_metadata_is_correct(self):
        _root, _provider, result = self.run_sandbox()
        self.assertTrue(result["extraction_report"]["run_metadata"]["live_external_provider_call"])
        self.assertTrue(result["extraction_report"]["run_metadata"]["approval_flag_used"])

    def test_api_keys_are_not_logged_or_written_to_reports(self):
        root, _provider, result = self.run_sandbox()
        payload = json.dumps(result["extraction_report"]) + (root / "azure_di_sandbox_extraction_v2_report_13x.json").read_text()
        self.assertNotIn("secret-key", payload)

    def test_no_hugging_face_or_openai_calls_are_required(self):
        _root, _provider, result = self.run_sandbox()
        metadata = result["extraction_report"]["run_metadata"]
        self.assertFalse(metadata["live_huggingface_calls_made"])
        self.assertFalse(metadata["live_openai_calls_made"])

    def test_no_db_is_required(self):
        _root, _provider, result = self.run_sandbox()
        self.assertEqual(result["extraction_report"]["pipeline_name"], "Azure DI-first Extraction v2 Sandbox")

    def test_markdown_summary_renders(self):
        _root, _provider, result = self.run_sandbox()
        markdown = render_summary_markdown(result["summary_report"])
        self.assertIn("Azure DI-first Sandbox Summary", markdown)
        self.assertIn("Recommended next feature", markdown)

    def test_existing_azure_di_provider_and_converter_tests_still_have_compatible_metadata(self):
        _root, _provider, result = self.run_sandbox()
        candidate = result["extraction_report"]["case_reports"][0]["candidates"][0]
        self.assertEqual(candidate["source_method"], "azure_document_intelligence")
        self.assertEqual(candidate["extraction_method"], "azure_document_intelligence")


if __name__ == "__main__":
    unittest.main()
