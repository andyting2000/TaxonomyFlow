import tempfile
import time as time_module
import unittest
import importlib
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from config import settings
from database import ExtractedDataItem, FilingJob, FinancialStatementPage
from schemas import JobStatus, ProcessingStatus
from services.azure_di_production_mapping import (
    diagnose_azure_di_candidate_mapping,
    map_azure_di_candidate_to_template_field,
)
from services.azure_di_production_extraction import process_azure_di_filing_job


class DummyResult:
    def __init__(self, one=None):
        self._one = one

    def scalar_one_or_none(self):
        return self._one


class FakeSession:
    def __init__(self, job):
        self.job = job
        self.added_pages = []
        self.added_items = []
        self.executed = []
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.flush = AsyncMock()

    async def execute(self, statement):
        self.executed.append(str(statement))
        if "FROM filing_jobs" in str(statement):
            return DummyResult(self.job)
        return DummyResult(None)

    def add(self, value):
        if isinstance(value, FinancialStatementPage):
            self.added_pages.append(value)
        elif isinstance(value, ExtractedDataItem):
            self.added_items.append(value)


class FakeProvider:
    endpoint = "https://example.cognitiveservices.azure.com/"
    model_id = "prebuilt-layout"

    def __init__(self, result=None, validate_error=None):
        self.result = result or azure_table_result()
        self.validate_error = validate_error
        self.called = False

    def validate_config(self):
        if self.validate_error:
            raise self.validate_error

    def analyze_pdf_path(self, pdf_path):
        self.called = True
        self.pdf_path = pdf_path
        return self.result


def azure_table_result():
    cells = []
    rows = [["Description", "2026"], ["Cash and bank balances", "1,234"]]
    for row_index, row in enumerate(rows):
        for col_index, value in enumerate(row):
            cells.append(
                {
                    "content": value,
                    "row_index": row_index,
                    "column_index": col_index,
                    "page_number": 1,
                    "bounding_regions": [{"page_number": 1}],
                }
            )
    return {
        "ok": True,
        "provider": "azure_document_intelligence",
        "model_id": "prebuilt-layout",
        "source_pdf": "sample.pdf",
        "runtime_seconds": 0.1,
        "pages_count": 1,
        "content_length": 48,
        "content": "Statement of Financial Position\nCash and bank balances 1,234",
        "pages": [{"page_number": 1, "lines": [], "words": []}],
        "lines": [{"content": "Statement of Financial Position", "page_number": 1}],
        "paragraphs": [],
        "tables": [
            {
                "table_index": 0,
                "row_count": 2,
                "column_count": 2,
                "page_numbers": [1],
                "cells": cells,
            }
        ],
        "table_cells": cells,
        "warnings": [],
        "errors": [],
        "reference_xml_sent_to_provider": False,
    }


def azure_note_column_result():
    cells = []
    rows = [
        ["Description", "Note", "2026", "2025"],
        ["Other receivable", "5", "1,000", "900"],
    ]
    for row_index, row in enumerate(rows):
        for col_index, value in enumerate(row):
            cells.append(
                {
                    "content": value,
                    "row_index": row_index,
                    "column_index": col_index,
                    "page_number": 1,
                    "bounding_regions": [{"page_number": 1}],
                }
            )
    return {
        "ok": True,
        "provider": "azure_document_intelligence",
        "model_id": "prebuilt-layout",
        "source_pdf": "sample.pdf",
        "runtime_seconds": 0.1,
        "pages_count": 1,
        "content_length": 90,
        "content": "Statement of Financial Position\nOther receivable 5 1,000 900",
        "pages": [{"page_number": 1, "lines": [], "words": []}],
        "lines": [{"content": "Statement of Financial Position", "page_number": 1}],
        "paragraphs": [],
        "tables": [
            {
                "table_index": 0,
                "row_count": 2,
                "column_count": 4,
                "page_numbers": [1],
                "cells": cells,
            }
        ],
        "table_cells": cells,
        "warnings": [],
        "errors": [],
        "reference_xml_sent_to_provider": False,
    }


def many_page_table_result(page_count=26, table_count=13, paragraph_count=0):
    tables = []
    all_cells = []
    for table_index in range(table_count):
        page_number = (table_index % page_count) + 1
        cells = []
        rows = [["Description", "2026"], [f"Cash balance {table_index}", f"{1000 + table_index:,}"]]
        for row_index, row in enumerate(rows):
            for col_index, value in enumerate(row):
                cell = {
                    "content": value,
                    "row_index": row_index,
                    "column_index": col_index,
                    "page_number": page_number,
                    "bounding_regions": [{"page_number": page_number}],
                }
                cells.append(cell)
                all_cells.append(cell)
        tables.append(
            {
                "table_index": table_index,
                "row_count": 2,
                "column_count": 2,
                "page_numbers": [page_number],
                "cells": cells,
            }
        )
    paragraphs = [
        {
            "paragraph_index": idx,
            "content": f"General report paragraph {idx} without usable financial table data.",
            "page_number": (idx % page_count) + 1 if page_count else 1,
            "bounding_regions": [{"page_number": (idx % page_count) + 1 if page_count else 1}],
            "spans": [],
        }
        for idx in range(paragraph_count)
    ]
    return {
        "ok": True,
        "provider": "azure_document_intelligence",
        "model_id": "prebuilt-layout",
        "source_pdf": "sample.pdf",
        "runtime_seconds": 0.1,
        "pages_count": page_count,
        "content_length": 200 + sum(len(item["content"]) for item in paragraphs),
        "content": "Statement of Financial Position\n" + "\n".join(item["content"] for item in paragraphs),
        "pages": [{"page_number": page, "lines": [], "words": []} for page in range(1, page_count + 1)],
        "lines": [{"content": "Statement of Financial Position", "page_number": 1}],
        "paragraphs": paragraphs,
        "tables": tables,
        "table_cells": all_cells,
        "warnings": [],
        "errors": [],
        "reference_xml_sent_to_provider": False,
    }


def make_job(source_pdf_path):
    return FilingJob(
        id=16,
        user_id=22,
        company_name="Azure DI Smoke",
        registration_number="AZ-16",
        financial_year_end=datetime(2026, 12, 31),
        source_pdf_path=str(source_pdf_path),
        status="PROCESSING",
    )


class AzureDIProductionCutoverTests(unittest.IsolatedAsyncioTestCase):
    async def test_config_default_resolves_to_azure_di(self):
        self.assertEqual(settings.extraction_pipeline, "azure_di")
        self.assertFalse(settings.extraction_allow_legacy_fallback)
        self.assertGreater(settings.azure_di_normalization_timeout_seconds, 0)
        self.assertTrue(settings.azure_di_text_blocks_enabled)
        self.assertGreater(settings.azure_di_text_block_timeout_seconds, 0)

    async def test_azure_di_candidates_are_persisted_to_existing_tables(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            pdf_dir = uploads / "pdfs"
            pdf_dir.mkdir(parents=True)
            pdf = pdf_dir / "source.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            session = FakeSession(make_job(pdf))
            provider = FakeProvider()
            progress_events = []

            def progress_callback(**event):
                progress_events.append(event)

            with (
                patch.object(settings, "upload_directory", str(uploads)),
                self.assertLogs("services.extraction_v2_azure_di_pipeline", level="INFO") as pipeline_logs,
                self.assertLogs("services.extraction_v2_azure_di_normalizer", level="INFO") as normalizer_logs,
            ):
                result = await process_azure_di_filing_job(
                    16,
                    session,
                    provider=provider,
                    progress_callback=progress_callback,
                )

        self.assertTrue(provider.called)
        self.assertEqual(result.status, JobStatus.REVIEW)
        self.assertEqual(session.job.status, "REVIEW")
        self.assertEqual(session.job.user_id, 22)
        self.assertEqual(len(session.added_pages), 1)
        self.assertEqual(session.added_pages[0].job_id, 16)
        self.assertEqual(session.added_pages[0].page_number, 1)
        self.assertEqual(len(session.added_items), 1)
        item = session.added_items[0]
        self.assertEqual(item.extracted_label, "Cash and bank balances")
        self.assertEqual(item.extracted_value, "1234")
        self.assertEqual(item.financial_year, 2026)
        self.assertEqual(item.page_id, session.added_pages[0].id)
        self.assertEqual(item.template_field_id, "ssmt:CashAndBankBalances")
        self.assertEqual(
            item.statement_type,
            "Statement of Financial Position (Current/Non-Current Method)",
        )
        self.assertTrue(item.is_reviewed)
        self.assertIn("azure_di_template_mapping", item.validation_warnings)
        self.assertEqual(session.job.progress, 100)
        self.assertIsNone(session.job.error_message)
        progress_messages = [event["message"] for event in progress_events]
        self.assertIn("Azure DI submitted", progress_messages)
        self.assertIn("Azure DI result received", progress_messages)
        self.assertIn("Normalizing Azure DI result", progress_messages)
        self.assertIn("Persisting extracted data", progress_messages)
        self.assertIn("Finalizing review workspace", progress_messages)
        self.assertIn("Azure DI tables loop finished", "\n".join(pipeline_logs.output))
        self.assertIn("Azure DI report normalization finished", "\n".join(normalizer_logs.output))

    async def test_automatic_llm_mapping_updates_ai_mapping_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            pdf_dir = uploads / "pdfs"
            pdf_dir.mkdir(parents=True)
            pdf = pdf_dir / "source.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            session = FakeSession(make_job(pdf))
            provider = FakeProvider()

            async def fake_run_llm_mapping(*_args, **_kwargs):
                self.assertEqual(session.job.ai_mapping_status, "running")
                return {
                    "summary": {
                        "rows_sent_to_llm": 1,
                        "suggestions_generated": 1,
                        "applied_suggestions": 0,
                    }
                }

            with (
                patch.object(settings, "upload_directory", str(uploads)),
                patch.object(settings, "llm_mapping_enabled", True),
                patch(
                    "services.llm_taxonomy_mapping.run_llm_mapping_for_job",
                    new=AsyncMock(side_effect=fake_run_llm_mapping),
                ),
                patch(
                    "services.llm_taxonomy_mapping.HuggingFaceQwenMappingClient",
                    return_value=object(),
                ),
            ):
                result = await process_azure_di_filing_job(16, session, provider=provider)

        self.assertEqual(result.status, JobStatus.REVIEW)
        self.assertEqual(session.job.ai_mapping_status, "completed")
        self.assertIsNone(session.job.ai_mapping_last_error_message)
        self.assertEqual(result.extracted_row_count, 1)
        self.assertEqual(result.ai_mapping_status, "completed")
        self.assertEqual(result.ai_suggestion_count, 1)

    async def test_mapping_loop_failure_keeps_persisted_extraction_in_review(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            pdf_dir = uploads / "pdfs"
            pdf_dir.mkdir(parents=True)
            pdf = pdf_dir / "source.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            session = FakeSession(make_job(pdf))
            provider = FakeProvider()

            with (
                patch.object(settings, "upload_directory", str(uploads)),
                patch.object(settings, "llm_mapping_enabled", True),
                patch(
                    "services.llm_taxonomy_mapping.run_llm_mapping_for_job",
                    new=AsyncMock(
                        side_effect=RuntimeError("Task got Future attached to a different loop")
                    ),
                ),
                patch(
                    "services.llm_taxonomy_mapping.HuggingFaceQwenMappingClient",
                    return_value=object(),
                ),
            ):
                result = await process_azure_di_filing_job(16, session, provider=provider)

        self.assertEqual(result.status, JobStatus.REVIEW)
        self.assertEqual(session.job.status, "REVIEW")
        self.assertEqual(len(session.added_items), 1)
        self.assertEqual(session.job.ai_mapping_status, "failed")
        self.assertTrue(
            session.job.ai_mapping_last_error_message.startswith(
                "[async_resource_loop_mismatch]"
            )
        )
        self.assertEqual(result.extracted_row_count, 1)
        self.assertEqual(result.ai_mapping_status, "failed")
        self.assertEqual(result.optional_stage, "mapping")
        self.assertEqual(result.optional_stage_status, "failed")
        self.assertEqual(result.optional_stage_error_code, "async_resource_loop_mismatch")
        self.assertEqual(
            result.optional_stage_error_message,
            "AI mapping suggestions failed after extraction completed.",
        )

    async def test_high_confidence_azure_di_label_maps_to_template_field(self):
        mapping = map_azure_di_candidate_to_template_field(
            {
                "row_type": "numeric_fact",
                "label": "Cash and bank balances",
                "statement_section": "Statement of Financial Position",
            }
        )

        self.assertEqual(mapping.template_field_id, "ssmt:CashAndBankBalances")
        self.assertEqual(
            mapping.statement_type,
            "Statement of Financial Position (Current/Non-Current Method)",
        )
        self.assertEqual(mapping.confidence, "high")
        self.assertTrue(mapping.is_reviewed)
        self.assertIn("azure_di_template_mapping", mapping.warning)

    async def test_ambiguous_azure_di_label_remains_unassigned(self):
        mapping = map_azure_di_candidate_to_template_field(
            {
                "row_type": "numeric_fact",
                "label": "Trade and other receivables",
                "statement_section": "Statement of Financial Position",
            }
        )

        self.assertIsNone(mapping.template_field_id)
        self.assertFalse(mapping.is_reviewed)

    async def test_weak_generic_azure_di_label_remains_unassigned(self):
        mapping = map_azure_di_candidate_to_template_field(
            {
                "row_type": "numeric_fact",
                "label": "Other",
                "statement_section": "Statement of Financial Position",
            }
        )

        self.assertIsNone(mapping.template_field_id)
        self.assertEqual(mapping.reason, "rejected_generic_label")

    async def test_profit_loss_labels_do_not_map_to_financial_position(self):
        labels = [
            ("Revenue", "ifrs-smes:Revenue"),
            ("Administration expenses", "ifrs-smes:AdministrativeExpense"),
            ("Loss before tax", "ifrs-smes:ProfitLossBeforeTax"),
            ("Tax expense", "ifrs-smes:IncomeTaxExpenseContinuingOperations"),
        ]
        for label, concept_id in labels:
            with self.subTest(label=label):
                mapping = map_azure_di_candidate_to_template_field(
                    {
                        "row_type": "numeric_fact",
                        "label": label,
                        "value": "1000",
                        "statement_section": "Statement of Financial Position",
                    }
                )

                self.assertEqual(mapping.template_field_id, concept_id)
                self.assertIn("Profit or Loss", mapping.statement_type)

    async def test_current_liabilities_remains_financial_position(self):
        mapping = map_azure_di_candidate_to_template_field(
            {
                "row_type": "subtotal_or_total",
                "label": "Total current liabilities",
                "value": "1000",
                "statement_section": "Statement of Financial Position",
            }
        )

        self.assertEqual(mapping.template_field_id, "ifrs-smes:CurrentLiabilities")
        self.assertEqual(
            mapping.statement_type,
            "Statement of Financial Position (Current/Non-Current Method)",
        )

    async def test_cash_equivalent_movement_rows_map_to_cash_flow_family(self):
        labels = [
            "Cash and cash equivalents at beginning of year",
            "Cash and cash equivalents at end of year",
            "Net decrease in cash and cash equivalents",
        ]
        for label in labels:
            with self.subTest(label=label):
                mapping = map_azure_di_candidate_to_template_field(
                    {
                        "row_type": "numeric_fact",
                        "label": label,
                        "value": "1000",
                        "statement_section": "Statement of Financial Position",
                    }
                )

                self.assertIsNotNone(mapping.template_field_id)
                self.assertIn("Cash Flows", mapping.statement_type)

    async def test_person_and_company_names_remain_unassigned(self):
        for label in ["Acme Sdn Bhd", "John Tan"]:
            with self.subTest(label=label):
                mapping = map_azure_di_candidate_to_template_field(
                    {
                        "row_type": "numeric_fact",
                        "label": label,
                        "value": "1000",
                        "statement_section": "Statement of Financial Position",
                    }
                )

                self.assertIsNone(mapping.template_field_id)
                self.assertEqual(mapping.reason, "rejected_person_or_company_name")

    async def test_mapping_diagnostics_include_rejection_reason_and_candidates(self):
        diagnosis = diagnose_azure_di_candidate_mapping(
            {
                "row_type": "numeric_fact",
                "label": "Other",
                "value": "1000",
                "statement_section": "Statement of Financial Position",
                "page_number": 3,
            }
        )

        self.assertFalse(diagnosis["mapped"])
        self.assertEqual(diagnosis["mapping_rejection_reason"], "rejected_generic_label")
        self.assertEqual(diagnosis["page_number"], 3)

    async def test_no_confirmed_tag_is_set_for_mapped_azure_di_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            pdf_dir = uploads / "pdfs"
            pdf_dir.mkdir(parents=True)
            pdf = pdf_dir / "source.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            session = FakeSession(make_job(pdf))
            provider = FakeProvider()

            with patch.object(settings, "upload_directory", str(uploads)):
                await process_azure_di_filing_job(16, session, provider=provider)

        self.assertEqual(session.added_items[0].template_field_id, "ssmt:CashAndBankBalances")
        self.assertIsNone(session.added_items[0].confirmed_tag_id)

    async def test_note_column_is_not_used_as_extracted_value_when_amount_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            pdf_dir = uploads / "pdfs"
            pdf_dir.mkdir(parents=True)
            pdf = pdf_dir / "source.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            session = FakeSession(make_job(pdf))
            provider = FakeProvider(result=azure_note_column_result())

            with patch.object(settings, "upload_directory", str(uploads)):
                result = await process_azure_di_filing_job(16, session, provider=provider)

        self.assertEqual(result.status, JobStatus.REVIEW)
        self.assertEqual(len(session.added_items), 1)
        item = session.added_items[0]
        self.assertEqual(item.extracted_label, "Other receivable")
        self.assertEqual(item.extracted_value, "1000")
        self.assertEqual(item.value_previous_year, "900")
        self.assertNotEqual(item.extracted_value, "5")
        self.assertIn("note_column_values_ignored", item.validation_warnings)

    async def test_review_api_template_fallback_resolves_xbrl_concept_label(self):
        from routers.filings import _xbrl_template_field_info

        info = _xbrl_template_field_info(
            "ssmt:CashAndBankBalances",
            "Statement of Financial Position",
        )

        self.assertIsNotNone(info)
        self.assertEqual(info["field_id"], "ssmt:CashAndBankBalances")
        self.assertEqual(info["label"], "Total cash and cash equivalents")
        self.assertEqual(info["statement_code"], "210000")

    async def test_many_page_many_table_azure_di_result_normalizes_and_persists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            pdf_dir = uploads / "pdfs"
            pdf_dir.mkdir(parents=True)
            pdf = pdf_dir / "source.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            session = FakeSession(make_job(pdf))
            provider = FakeProvider(result=many_page_table_result())

            with patch.object(settings, "upload_directory", str(uploads)):
                result = await process_azure_di_filing_job(16, session, provider=provider)

        self.assertEqual(result.status, JobStatus.REVIEW)
        self.assertEqual(session.job.status, "REVIEW")
        self.assertEqual(len(session.added_pages), 26)
        self.assertEqual(len(session.added_items), 13)

    async def test_many_page_many_table_many_paragraph_result_reaches_review(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            pdf_dir = uploads / "pdfs"
            pdf_dir.mkdir(parents=True)
            pdf = pdf_dir / "source.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            session = FakeSession(make_job(pdf))
            provider = FakeProvider(result=many_page_table_result(paragraph_count=664))

            with patch.object(settings, "upload_directory", str(uploads)):
                result = await process_azure_di_filing_job(16, session, provider=provider)

        self.assertEqual(result.status, JobStatus.REVIEW)
        self.assertEqual(session.job.status, "REVIEW")
        self.assertEqual(session.job.progress, 100)
        self.assertEqual(len(session.added_pages), 26)
        self.assertEqual(len(session.added_items), 13)

    async def test_text_block_timeout_continues_with_table_candidates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            pdf_dir = uploads / "pdfs"
            pdf_dir.mkdir(parents=True)
            pdf = pdf_dir / "source.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            session = FakeSession(make_job(pdf))
            provider = FakeProvider(result=many_page_table_result(paragraph_count=664))
            progress_events = []

            def progress_callback(**event):
                progress_events.append(event)

            with (
                patch.object(settings, "upload_directory", str(uploads)),
                patch.object(settings, "azure_di_text_block_timeout_seconds", 0),
                patch.object(settings, "azure_di_text_blocks_enabled", True),
                self.assertLogs("services.extraction_v2_azure_di_pipeline", level="WARNING") as pipeline_logs,
            ):
                result = await process_azure_di_filing_job(
                    16,
                    session,
                    provider=provider,
                    progress_callback=progress_callback,
                )

        self.assertEqual(result.status, JobStatus.REVIEW)
        self.assertEqual(session.job.status, "REVIEW")
        self.assertEqual(session.job.progress, 100)
        self.assertEqual(len(session.added_pages), 26)
        self.assertEqual(len(session.added_items), 13)
        self.assertIn(
            "Azure DI text block normalization timed out; continuing with table candidates.",
            "\n".join(pipeline_logs.output),
        )
        self.assertIn(
            "Azure DI text block normalization timed out; continuing with table candidates.",
            session.added_items[0].validation_warnings,
        )
        progress_messages = [event["message"] for event in progress_events]
        self.assertLess(
            progress_messages.index("Normalizing Azure DI result"),
            progress_messages.index("Persisting extracted data"),
        )

    async def test_text_blocks_can_be_disabled_and_tables_still_persist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            pdf_dir = uploads / "pdfs"
            pdf_dir.mkdir(parents=True)
            pdf = pdf_dir / "source.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            session = FakeSession(make_job(pdf))
            provider = FakeProvider(result=many_page_table_result(paragraph_count=664))

            with (
                patch.object(settings, "upload_directory", str(uploads)),
                patch.object(settings, "azure_di_text_blocks_enabled", False),
                self.assertLogs("services.extraction_v2_azure_di_pipeline", level="INFO") as pipeline_logs,
            ):
                result = await process_azure_di_filing_job(16, session, provider=provider)

        self.assertEqual(result.status, JobStatus.REVIEW)
        self.assertEqual(session.job.status, "REVIEW")
        self.assertEqual(len(session.added_items), 13)
        self.assertIn("Azure DI text block normalization skipped", "\n".join(pipeline_logs.output))
        self.assertIn(
            "Azure DI text block normalization skipped because AZURE_DI_TEXT_BLOCKS_ENABLED=false.",
            session.added_items[0].validation_warnings,
        )

    async def test_text_block_timeout_without_table_candidates_marks_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            pdf_dir = uploads / "pdfs"
            pdf_dir.mkdir(parents=True)
            pdf = pdf_dir / "source.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            session = FakeSession(make_job(pdf))
            provider = FakeProvider(result=many_page_table_result(table_count=0, paragraph_count=664))

            with (
                patch.object(settings, "upload_directory", str(uploads)),
                patch.object(settings, "azure_di_text_block_timeout_seconds", 0),
                patch.object(settings, "azure_di_text_blocks_enabled", True),
                self.assertLogs("services.extraction_v2_azure_di_pipeline", level="WARNING") as pipeline_logs,
            ):
                result = await process_azure_di_filing_job(16, session, provider=provider)

        self.assertEqual(result.status, JobStatus.ERROR)
        self.assertIn("Azure DI text block normalization timed out", result.error)
        self.assertEqual(session.job.status, "ERROR")
        self.assertEqual(session.job.progress, 0)
        self.assertNotEqual(session.job.status, "PROCESSING")
        self.assertEqual(session.added_pages, [])
        self.assertEqual(session.added_items, [])
        self.assertIn(
            "Azure DI text block normalization timed out; continuing with table candidates.",
            "\n".join(pipeline_logs.output),
        )

    async def test_pathological_table_marks_job_failed_instead_of_hanging(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            pdf_dir = uploads / "pdfs"
            pdf_dir.mkdir(parents=True)
            pdf = pdf_dir / "source.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            session = FakeSession(make_job(pdf))
            pathological_result = azure_table_result()
            pathological_result["tables"] = [
                {
                    "table_index": 0,
                    "row_count": 1001,
                    "column_count": 2,
                    "page_numbers": [1],
                    "cells": [],
                }
            ]
            pathological_result["table_cells"] = []
            provider = FakeProvider(result=pathological_result)

            with patch.object(settings, "upload_directory", str(uploads)):
                result = await process_azure_di_filing_job(16, session, provider=provider)

        self.assertEqual(result.status, JobStatus.ERROR)
        self.assertIn("Azure DI normalization failed", result.error)
        self.assertIn("table row limit", session.job.error_message)
        self.assertEqual(session.job.status, "ERROR")
        self.assertEqual(session.job.progress, 0)
        self.assertEqual(session.added_pages, [])
        self.assertEqual(session.added_items, [])

    async def test_normalization_timeout_marks_job_failed_instead_of_processing(self):
        def slow_candidate_conversion(*args, **kwargs):
            time_module.sleep(0.05)
            return []

        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            pdf_dir = uploads / "pdfs"
            pdf_dir.mkdir(parents=True)
            pdf = pdf_dir / "source.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            session = FakeSession(make_job(pdf))
            provider = FakeProvider()

            with (
                patch.object(settings, "upload_directory", str(uploads)),
                patch.object(settings, "azure_di_normalization_timeout_seconds", 0.01),
                patch(
                    "services.azure_di_production_extraction.convert_azure_di_result_to_candidates",
                    side_effect=slow_candidate_conversion,
                ),
            ):
                result = await process_azure_di_filing_job(16, session, provider=provider)

        self.assertEqual(result.status, JobStatus.ERROR)
        self.assertEqual(result.error, "Azure DI normalization timed out.")
        self.assertEqual(session.job.status, "ERROR")
        self.assertEqual(session.job.progress, 0)
        self.assertEqual(session.job.error_message, "Azure DI normalization timed out.")
        self.assertEqual(session.added_pages, [])
        self.assertEqual(session.added_items, [])

    async def test_missing_azure_di_config_marks_job_failed_without_legacy(self):
        from services.azure_document_intelligence_provider import AzureDocumentIntelligenceConfigError

        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            pdf_dir = uploads / "pdfs"
            pdf_dir.mkdir(parents=True)
            pdf = pdf_dir / "source.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            session = FakeSession(make_job(pdf))
            provider = FakeProvider(
                validate_error=AzureDocumentIntelligenceConfigError(
                    "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT is not configured."
                )
            )

            with patch.object(settings, "upload_directory", str(uploads)):
                result = await process_azure_di_filing_job(16, session, provider=provider)

        self.assertFalse(provider.called)
        self.assertEqual(result.status, JobStatus.ERROR)
        self.assertIn("Azure Document Intelligence is not configured", result.error)
        self.assertEqual(session.job.status, "ERROR")
        self.assertEqual(session.job.progress, 0)
        self.assertIn("Azure Document Intelligence is not configured", session.job.error_message)
        self.assertEqual(session.added_pages, [])
        self.assertEqual(session.added_items, [])

    async def test_no_usable_rows_marks_job_failed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            pdf_dir = uploads / "pdfs"
            pdf_dir.mkdir(parents=True)
            pdf = pdf_dir / "source.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            session = FakeSession(make_job(pdf))
            empty_result = azure_table_result()
            empty_result["tables"] = []
            empty_result["table_cells"] = []
            empty_result["paragraphs"] = []
            provider = FakeProvider(result=empty_result)

            with patch.object(settings, "upload_directory", str(uploads)):
                result = await process_azure_di_filing_job(16, session, provider=provider)

        self.assertEqual(result.status, JobStatus.ERROR)
        self.assertEqual(result.error, "Azure DI returned no usable financial rows.")
        self.assertEqual(session.job.status, "ERROR")
        self.assertEqual(session.job.progress, 0)
        self.assertEqual(session.job.error_message, "Azure DI returned no usable financial rows.")

    async def test_normalization_failure_after_azure_result_marks_job_failed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            pdf_dir = uploads / "pdfs"
            pdf_dir.mkdir(parents=True)
            pdf = pdf_dir / "source.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            session = FakeSession(make_job(pdf))
            provider = FakeProvider()

            with (
                patch.object(settings, "upload_directory", str(uploads)),
                patch(
                    "services.azure_di_production_extraction.normalize_azure_di_extraction_report",
                    side_effect=RuntimeError("normalizer stopped"),
                ),
            ):
                result = await process_azure_di_filing_job(16, session, provider=provider)

        self.assertTrue(provider.called)
        self.assertEqual(result.status, JobStatus.ERROR)
        self.assertIn("Azure DI normalization failed", result.error)
        self.assertIn("normalizer stopped", session.job.error_message)
        self.assertEqual(session.job.status, "ERROR")
        self.assertEqual(session.job.progress, 0)
        self.assertEqual(session.added_pages, [])
        self.assertEqual(session.added_items, [])

    async def test_persistence_failure_after_azure_result_marks_job_failed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            pdf_dir = uploads / "pdfs"
            pdf_dir.mkdir(parents=True)
            pdf = pdf_dir / "source.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            session = FakeSession(make_job(pdf))
            provider = FakeProvider()

            with (
                patch.object(settings, "upload_directory", str(uploads)),
                patch(
                    "services.azure_di_production_extraction._persist_candidates",
                    new=AsyncMock(side_effect=RuntimeError("insert failed")),
                ),
            ):
                result = await process_azure_di_filing_job(16, session, provider=provider)

        self.assertTrue(provider.called)
        self.assertEqual(result.status, JobStatus.ERROR)
        self.assertIn("Azure DI persistence failed", result.error)
        self.assertIn("insert failed", session.job.error_message)
        self.assertEqual(session.job.status, "ERROR")
        self.assertEqual(session.job.progress, 0)
        session.rollback.assert_awaited()


class FakeSessionManager:
    def __init__(self):
        self.session = SimpleNamespace()

    @asynccontextmanager
    async def get_session(self):
        yield self.session


class ProcessPdfTaskRoutingTests(unittest.IsolatedAsyncioTestCase):
    def import_tasks_with_writable_temp(self, temp_dir):
        with patch.object(settings, "temp_directory", str(Path(temp_dir) / "worker-temp")):
            return importlib.import_module("tasks")

    async def test_process_pdf_task_routes_to_azure_di_without_smart_ai_processor(self):
        from services.redis_status_tracker import redis_status_tracker

        with tempfile.TemporaryDirectory() as temp_dir:
            tasks = self.import_tasks_with_writable_temp(temp_dir)
            result_status = ProcessingStatus(
                job_id=16,
                status=JobStatus.REVIEW,
                progress=100,
                message="Azure Document Intelligence processing complete.",
            )
            with (
                patch.object(settings, "extraction_pipeline", "azure_di"),
                patch.object(settings, "extraction_allow_legacy_fallback", False),
                patch.object(redis_status_tracker, "initialize", new=AsyncMock()),
                patch("tasks._run_azure_di_pdf_processing", new=AsyncMock(return_value=result_status)) as azure_run,
                patch("tasks.init_ai_processor", new=AsyncMock()) as init_ai,
            ):
                response = await tasks.process_pdf_job_async(
                    16,
                    "task-16",
                    session_manager=FakeSessionManager(),
                )

        self.assertTrue(response["success"])
        azure_run.assert_awaited_once()
        init_ai.assert_not_awaited()

    async def test_azure_di_mode_does_not_call_smart_ai_process_pdf(self):
        from services.redis_status_tracker import redis_status_tracker

        with tempfile.TemporaryDirectory() as temp_dir:
            tasks = self.import_tasks_with_writable_temp(temp_dir)
            result_status = ProcessingStatus(
                job_id=16,
                status=JobStatus.REVIEW,
                progress=100,
                message="Azure Document Intelligence processing complete.",
            )
            legacy_processor = SimpleNamespace(process_pdf=AsyncMock())
            with (
                patch.object(settings, "extraction_pipeline", "azure_di"),
                patch.object(settings, "extraction_allow_legacy_fallback", False),
                patch.object(redis_status_tracker, "initialize", new=AsyncMock()),
                patch("tasks._run_azure_di_pdf_processing", new=AsyncMock(return_value=result_status)),
                patch("tasks.init_ai_processor", new=AsyncMock(return_value=legacy_processor)) as init_ai,
            ):
                response = await tasks.process_pdf_job_async(
                    16,
                    "task-16",
                    session_manager=FakeSessionManager(),
                )

        self.assertTrue(response["success"])
        init_ai.assert_not_awaited()
        legacy_processor.process_pdf.assert_not_awaited()

    async def test_azure_di_celery_progress_updates_include_local_stages(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tasks = self.import_tasks_with_writable_temp(temp_dir)

            async def fake_process(job_id, db, *, progress_callback=None, provider=None):
                progress_callback(
                    job_id=job_id,
                    progress=35,
                    status=JobStatus.PROCESSING,
                    message="Azure DI result received",
                    total_pages=2,
                )
                progress_callback(
                    job_id=job_id,
                    progress=50,
                    status=JobStatus.PROCESSING,
                    message="Normalizing Azure DI result",
                )
                progress_callback(
                    job_id=job_id,
                    progress=70,
                    status=JobStatus.PROCESSING,
                    message="Persisting extracted data",
                )
                return ProcessingStatus(
                    job_id=job_id,
                    status=JobStatus.REVIEW,
                    progress=100,
                    message="Azure Document Intelligence processing complete.",
                )

            state_reporter = SimpleNamespace(progress=Mock(return_value=True))
            with patch(
                "services.azure_di_production_extraction.process_azure_di_filing_job",
                new=fake_process,
            ):
                result = await tasks._run_azure_di_pdf_processing(
                    "task-16",
                    16,
                    SimpleNamespace(),
                    state_reporter=state_reporter,
                )

        self.assertEqual(result.status, JobStatus.REVIEW)
        statuses = [
            call.args[0]["status"]
            for call in state_reporter.progress.call_args_list
        ]
        self.assertIn("Processing with Azure Document Intelligence", statuses)
        self.assertIn("Azure DI result received", statuses)
        self.assertIn("Normalizing Azure DI result", statuses)
        self.assertIn("Persisting extracted data", statuses)

    async def test_legacy_pipeline_remains_available_when_configured(self):
        from services.redis_status_tracker import redis_status_tracker

        with tempfile.TemporaryDirectory() as temp_dir:
            tasks = self.import_tasks_with_writable_temp(temp_dir)
            result_status = ProcessingStatus(
                job_id=16,
                status=JobStatus.REVIEW,
                progress=100,
                message="Legacy complete.",
            )
            with (
                patch.object(settings, "extraction_pipeline", "legacy"),
                patch.object(redis_status_tracker, "initialize", new=AsyncMock()),
                patch("tasks._run_legacy_pdf_processing", new=AsyncMock(return_value=result_status)) as legacy_run,
                patch("tasks._run_azure_di_pdf_processing", new=AsyncMock()) as azure_run,
            ):
                response = await tasks.process_pdf_job_async(
                    16,
                    "task-16",
                    session_manager=FakeSessionManager(),
                )

        self.assertTrue(response["success"])
        legacy_run.assert_awaited_once()
        azure_run.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
