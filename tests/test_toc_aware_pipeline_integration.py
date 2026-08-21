import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from config import settings
from schemas import JobStatus
from services.azure_di_production_extraction import process_azure_di_filing_job
from services.toc_aware_document_structure import document_structure_artifact_path
from services.toc_aware_document_structure import (
    analyze_document_structure,
    load_document_structure,
    persist_document_structure,
)
from tests.test_azure_di_production_cutover import FakeProvider, FakeSession, make_job


FIXTURES = Path(__file__).parent / "fixtures" / "toc_aware"


def production_result():
    payload = json.loads((FIXTURES / "fixture_a_explicit_ranges.json").read_text(encoding="utf-8"))
    cells = [
        {"content": "Description", "row_index": 0, "column_index": 0, "page_number": 4, "bounding_regions": [{"page_number": 4}]},
        {"content": "2026", "row_index": 0, "column_index": 1, "page_number": 4, "bounding_regions": [{"page_number": 4}]},
        {"content": "Cash and bank balances", "row_index": 1, "column_index": 0, "page_number": 4, "bounding_regions": [{"page_number": 4}]},
        {"content": "1,234", "row_index": 1, "column_index": 1, "page_number": 4, "bounding_regions": [{"page_number": 4}]},
    ]
    payload.update(
        {
            "ok": True,
            "provider": "azure_document_intelligence",
            "model_id": "prebuilt-layout",
            "pages_count": len(payload["pages"]),
            "content": "INDEX Directors Report Statement of Financial Position Cash and bank balances",
            "content_length": 81,
            "tables": [
                {
                    "table_index": 0,
                    "row_count": 2,
                    "column_count": 2,
                    "page_numbers": [4],
                    "cells": cells,
                    "bounding_regions": [],
                }
            ],
            "table_cells": cells,
            "warnings": [],
            "errors": [],
            "reference_xml_sent_to_provider": False,
        }
    )
    return payload


class CountingProvider(FakeProvider):
    def __init__(self, result):
        super().__init__(result=result)
        self.call_count = 0

    def analyze_pdf_path(self, pdf_path):
        self.call_count += 1
        return super().analyze_pdf_path(pdf_path)


class TocAwarePipelineIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def run_job(
        self,
        uploads,
        *,
        enabled,
        persistence,
        analyze_patch=None,
        persist_patch=None,
        provider_result=None,
        llm_fallback=False,
    ):
        pdf_dir = uploads / "pdfs"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        pdf = pdf_dir / "source.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        job = make_job(pdf)
        session = FakeSession(job)
        provider = CountingProvider(provider_result or production_result())
        patches = [
            patch.object(settings, "upload_directory", str(uploads)),
            patch.object(settings, "toc_aware_pipeline_enabled", enabled),
            patch.object(settings, "toc_aware_structure_persistence_enabled", persistence),
            patch.object(settings, "toc_aware_llm_fallback_enabled", llm_fallback),
            patch.object(settings, "llm_mapping_enabled", False),
        ]
        if analyze_patch is not None:
            patches.append(
                patch(
                    "services.toc_aware_document_structure.analyze_document_structure",
                    side_effect=analyze_patch,
                )
            )
        if persist_patch is not None:
            patches.append(
                patch(
                    "services.toc_aware_document_structure.persist_document_structure",
                    side_effect=persist_patch,
                )
            )
        entered = []
        try:
            for context in patches:
                entered.append(context)
                context.__enter__()
            result = await process_azure_di_filing_job(16, session, provider=provider)
        finally:
            for context in reversed(entered):
                context.__exit__(None, None, None)
        snapshot = [
            (
                item.extracted_label,
                item.extracted_value,
                item.financial_year,
                item.value_previous_year,
                item.financial_year_previous,
                item.statement_type,
                item.template_field_id,
                item.template_position,
                item.is_required_field,
                item.is_reviewed,
                item.confirmed_tag_id,
                item.validation_warnings,
                item.has_calculation_warning,
            )
            for item in session.added_items
        ]
        return result, session, provider, snapshot

    async def test_disabled_feature_makes_no_structure_or_additional_provider_call(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            with patch(
                "services.toc_aware_document_structure.analyze_document_structure"
            ) as analyzer:
                result, _session, provider, _snapshot = await self.run_job(
                    uploads,
                    enabled=False,
                    persistence=False,
                )
            self.assertEqual(result.status, JobStatus.REVIEW)
            self.assertEqual(provider.call_count, 1)
            analyzer.assert_not_called()
            self.assertFalse(any(uploads.rglob("structure_19a_v4.json")))

    async def test_retry_invalidates_prior_artifact_when_pipeline_is_disabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            with patch.object(settings, "upload_directory", str(uploads)):
                persist_document_structure(
                    analyze_document_structure(
                        job_id=16,
                        azure_result=production_result(),
                        normalized_candidates=[],
                    )
                )
                self.assertTrue(document_structure_artifact_path(16).is_file())

            result, _session, provider, _snapshot = await self.run_job(
                uploads,
                enabled=False,
                persistence=False,
            )

            self.assertEqual(result.status, JobStatus.REVIEW)
            self.assertEqual(provider.call_count, 1)
            self.assertFalse(any(uploads.rglob("structure_19a_v4.json")))

    async def test_retry_invalidates_prior_artifact_when_persistence_is_disabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            with patch.object(settings, "upload_directory", str(uploads)):
                persist_document_structure(
                    analyze_document_structure(
                        job_id=16,
                        azure_result=production_result(),
                        normalized_candidates=[],
                    )
                )
                self.assertTrue(document_structure_artifact_path(16).is_file())

            result, _session, provider, _snapshot = await self.run_job(
                uploads,
                enabled=True,
                persistence=False,
            )

            self.assertEqual(result.status, JobStatus.REVIEW)
            self.assertEqual(provider.call_count, 1)
            self.assertFalse(any(uploads.rglob("structure_19a_v4.json")))

    async def test_reserved_toc_llm_fallback_flag_makes_no_llm_call(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            with (
                patch(
                    "services.llm_taxonomy_mapping.HuggingFaceQwenMappingClient"
                ) as llm_client,
                patch(
                    "services.llm_taxonomy_mapping.run_llm_mapping_for_job"
                ) as mapping_runner,
            ):
                result, _session, provider, _snapshot = await self.run_job(
                    uploads,
                    enabled=True,
                    persistence=True,
                    llm_fallback=True,
                )

            self.assertEqual(result.status, JobStatus.REVIEW)
            self.assertEqual(provider.call_count, 1)
            llm_client.assert_not_called()
            mapping_runner.assert_not_called()

    async def test_no_toc_is_a_warning_and_usable_filing_reaches_review(self):
        payload = production_result()
        payload["pages"][0]["lines"] = [
            {"content": "ANNUAL REPORT 2026", "page_number": 1}
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            result, _session, provider, _snapshot = await self.run_job(
                uploads,
                enabled=True,
                persistence=True,
                provider_result=payload,
            )
            with patch.object(settings, "upload_directory", str(uploads)):
                artifact = load_document_structure(16)

        self.assertEqual(result.status, JobStatus.REVIEW)
        self.assertEqual(provider.call_count, 1)
        self.assertFalse(artifact.toc_detected)
        self.assertIn("toc_not_detected", artifact.warnings)
        self.assertIn("toc_not_detected", {warning["code"] for warning in result.warnings})

    async def test_enabled_structure_is_persisted_without_changing_existing_mapping_fields(self):
        with tempfile.TemporaryDirectory() as disabled_temp, tempfile.TemporaryDirectory() as enabled_temp:
            disabled_result, _disabled_session, disabled_provider, disabled_snapshot = await self.run_job(
                Path(disabled_temp) / "uploads",
                enabled=False,
                persistence=False,
            )
            enabled_uploads = Path(enabled_temp) / "uploads"
            enabled_result, enabled_session, enabled_provider, enabled_snapshot = await self.run_job(
                enabled_uploads,
                enabled=True,
                persistence=True,
            )
            with patch.object(settings, "upload_directory", str(enabled_uploads)):
                artifact_exists = document_structure_artifact_path(16).is_file()
                artifact = load_document_structure(16)

        self.assertEqual(disabled_result.status, JobStatus.REVIEW)
        self.assertEqual(enabled_result.status, JobStatus.REVIEW)
        self.assertEqual(disabled_provider.call_count, 1)
        self.assertEqual(enabled_provider.call_count, 1)
        self.assertEqual(enabled_snapshot, disabled_snapshot)
        self.assertTrue(artifact_exists)
        self.assertTrue(
            all(item.confirmed_tag_id is None for item in enabled_session.added_items)
        )
        persisted_item_ids = {item.id for item in enabled_session.added_items}
        artifact_row_ids = {
            row_id
            for section in artifact.sections
            for row_id in section.extracted_row_ids
        }
        artifact_row_ids.update(
            disposition.content_id
            for disposition in [
                *artifact.unassigned_content,
                *artifact.ambiguous_content,
            ]
            if disposition.content_type == "extracted_row"
        )
        self.assertEqual(artifact_row_ids, persisted_item_ids)
        row_evidence = [
            evidence
            for evidence in artifact.content_evidence
            if evidence.content_type == "extracted_row"
        ]
        self.assertEqual(
            {evidence.content_id for evidence in row_evidence},
            persisted_item_ids,
        )
        self.assertTrue(
            all(
                evidence.provenance.get("original_candidate_id")
                for evidence in row_evidence
            )
        )
        self.assertEqual(
            artifact.safety_summary["persisted_extracted_row_reference_count"],
            len(persisted_item_ids),
        )
        self.assertEqual(
            artifact.safety_summary["unresolved_extracted_row_reference_count"],
            0,
        )
        self.assertFalse(artifact.safety_summary["statement_assignments_mutated"])
        self.assertFalse(artifact.safety_summary["mapping_suggestions_mutated"])
        self.assertEqual(artifact.safety_summary["confirmed_tag_id_mutations"], 0)
        self.assertEqual(artifact.safety_summary["final_mapping_mutations"], 0)

    async def test_analysis_and_persistence_failures_are_warning_only(self):
        with tempfile.TemporaryDirectory() as analyze_temp:
            result, _session, _provider, _snapshot = await self.run_job(
                Path(analyze_temp) / "uploads",
                enabled=True,
                persistence=True,
                analyze_patch=RuntimeError("synthetic analyzer failure"),
            )
            self.assertEqual(result.status, JobStatus.REVIEW)
            self.assertIn(
                "toc_aware_structure_analysis_failed",
                {warning["code"] for warning in result.warnings},
            )

        with tempfile.TemporaryDirectory() as persist_temp:
            persist_uploads = Path(persist_temp) / "uploads"
            with patch.object(settings, "upload_directory", str(persist_uploads)):
                stale = analyze_document_structure(
                    job_id=16,
                    azure_result=production_result(),
                    normalized_candidates=[],
                )
                persist_document_structure(stale)
            result, _session, _provider, _snapshot = await self.run_job(
                persist_uploads,
                enabled=True,
                persistence=True,
                persist_patch=OSError("synthetic persistence failure"),
            )
            self.assertEqual(result.status, JobStatus.REVIEW)
            self.assertIn(
                "toc_aware_structure_persistence_failed",
                {warning["code"] for warning in result.warnings},
            )
            self.assertFalse(any(persist_uploads.rglob("structure_19a_v4.json")))


if __name__ == "__main__":
    unittest.main()
