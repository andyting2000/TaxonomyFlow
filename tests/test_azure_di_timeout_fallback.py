import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from config import settings
from schemas import JobStatus
from services import azure_di_production_extraction as production
from tests.test_azure_di_production_cutover import (
    FakeProvider,
    FakeSession,
    make_job,
    many_page_table_result,
)


class FailingProvider(FakeProvider):
    def __init__(self, message):
        super().__init__()
        self.message = message

    def analyze_pdf_path(self, pdf_path):
        self.called = True
        raise RuntimeError(self.message)


class AzureDITimeoutFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def _run_outer_timeout(self, azure_result):
        real_normalization = production._run_local_normalization

        def delayed_normalization(**kwargs):
            if kwargs.get("text_blocks_enabled") is not False:
                time.sleep(0.05)
            return real_normalization(**kwargs)

        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        uploads = Path(temp_dir.name) / "uploads"
        pdf_dir = uploads / "pdfs"
        pdf_dir.mkdir(parents=True)
        pdf = pdf_dir / "source.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        session = FakeSession(make_job(pdf))
        provider = FakeProvider(result=azure_result)

        with (
            patch.object(settings, "upload_directory", str(uploads)),
            patch.object(settings, "azure_di_normalization_timeout_seconds", 0.01),
            patch.object(settings, "azure_di_allow_table_fallback_on_text_timeout", True),
            patch.object(settings, "llm_mapping_enabled", False),
            patch.object(production, "_run_local_normalization", side_effect=delayed_normalization),
        ):
            result = await production.process_azure_di_filing_job(
                16,
                session,
                provider=provider,
            )
        return result, session, provider

    async def test_service_result_and_outer_timeout_with_tables_completes_with_warning(self):
        result, session, provider = await self._run_outer_timeout(
            many_page_table_result(page_count=23, table_count=17, paragraph_count=664)
        )

        self.assertTrue(provider.called)
        self.assertEqual(result.status, JobStatus.REVIEW)
        self.assertEqual(session.job.status, "REVIEW")
        self.assertEqual(session.job.progress, 100)
        self.assertGreater(len(session.added_items), 0)
        self.assertIn("table candidates were used", result.message)
        session.rollback.assert_not_awaited()

    async def test_timeout_fallback_persists_normalized_candidates_and_warning_metadata(self):
        result, session, _provider = await self._run_outer_timeout(
            many_page_table_result(page_count=23, table_count=17, paragraph_count=664)
        )

        self.assertEqual(result.status, JobStatus.REVIEW)
        warning_items = json.loads(session.added_items[0].validation_warnings)
        metadata = next(
            item
            for item in warning_items
            if isinstance(item, dict)
            and item.get("warning_code") == "azure_di_text_block_normalization_timeout"
        )
        self.assertEqual(metadata["fallback_used"], "table_candidates_only")
        self.assertEqual(metadata["pages_count"], 23)
        self.assertEqual(metadata["tables_count"], 17)
        self.assertGreater(metadata["table_candidate_count"], 0)
        self.assertGreater(metadata["normalized_candidates_count"], 0)
        self.assertEqual(metadata["paragraph_count"], 664)
        self.assertEqual(metadata["timeout_seconds"], 0.01)
        self.assertIsNone(metadata["paragraph_index_at_timeout"])

    async def test_outer_timeout_with_zero_table_candidates_remains_error(self):
        result, session, _provider = await self._run_outer_timeout(
            many_page_table_result(page_count=23, table_count=0, paragraph_count=664)
        )

        self.assertEqual(result.status, JobStatus.ERROR)
        self.assertEqual(result.error, "Azure DI normalization timed out.")
        self.assertEqual(session.job.status, "ERROR")
        self.assertEqual(session.added_items, [])

    async def test_submit_failure_remains_error(self):
        result, session = await self._run_provider_failure("Azure DI submit failed")

        self.assertEqual(result.status, JobStatus.ERROR)
        self.assertIn("submit failed", result.error)
        self.assertEqual(session.job.status, "ERROR")
        self.assertEqual(session.added_items, [])

    async def test_analyze_failure_remains_error(self):
        result, session = await self._run_provider_failure("Azure DI analyze result failed")

        self.assertEqual(result.status, JobStatus.ERROR)
        self.assertIn("analyze result failed", result.error)
        self.assertEqual(session.job.status, "ERROR")
        self.assertEqual(session.added_items, [])

    async def _run_provider_failure(self, message):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            pdf_dir = uploads / "pdfs"
            pdf_dir.mkdir(parents=True)
            pdf = pdf_dir / "source.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            session = FakeSession(make_job(pdf))
            provider = FailingProvider(message)

            with patch.object(settings, "upload_directory", str(uploads)):
                result = await production.process_azure_di_filing_job(
                    16,
                    session,
                    provider=provider,
                )
        return result, session


if __name__ == "__main__":
    unittest.main()
