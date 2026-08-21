import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from config import settings
from routers.filings import _build_filing_job_cleanup_plan, _delete_upload_artifacts
from services.toc_aware_document_structure import persist_document_structure
from services.toc_aware_template_classification import (
    analyze_template_classification,
    classification_artifact_cleanup_candidate,
    persist_template_classification,
)
from tests.template_classification_test_support import section, structure
from tests.test_user_isolation_filings import FakeIsolationSession, build_isolation_app


def persist_artifacts(job_id):
    source = structure(
        job_id=job_id,
        sections=[
            section(
                canonical_section_type="statement_of_changes_in_equity",
                title="Statement of Changes in Equity",
            )
        ],
    )
    persist_document_structure(source)
    result = asyncio.run(
        analyze_template_classification(job_id=job_id, structure=source)
    )
    persist_template_classification(result, structure=source)


class TemplateClassificationApiTests(unittest.TestCase):
    def flags(self):
        return (
            patch.object(settings, "toc_aware_pipeline_enabled", True),
            patch.object(settings, "toc_aware_structure_persistence_enabled", True),
            patch.object(settings, "toc_aware_template_classification_enabled", True),
            patch.object(
                settings,
                "toc_aware_template_classification_persistence_enabled",
                True,
            ),
            patch.object(
                settings,
                "toc_aware_template_classification_live_llm_enabled",
                False,
            ),
        )

    def test_owned_read_only_capabilities_and_result_endpoints(self):
        session = FakeIsolationSession()
        app = build_isolation_app(session, user_id=1)
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            patches = (
                patch.object(settings, "upload_directory", str(uploads)),
                *self.flags(),
            )
            entered = []
            try:
                for item in patches:
                    entered.append(item)
                    item.__enter__()
                persist_artifacts(101)
                persist_artifacts(202)
                with TestClient(app) as client:
                    capabilities = client.get(
                        "/api/v1/filings/jobs/101/template-classification/capabilities"
                    )
                    result = client.get(
                        "/api/v1/filings/jobs/101/template-classification"
                    )
                    cross = client.get(
                        "/api/v1/filings/jobs/202/template-classification"
                    )
            finally:
                for item in reversed(entered):
                    item.__exit__(None, None, None)
        self.assertEqual(capabilities.status_code, 200)
        self.assertTrue(capabilities.json()["available"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["job_id"], 101)
        self.assertEqual(cross.status_code, 404)

    def test_disabled_feature_is_visible_but_artifact_is_unavailable(self):
        session = FakeIsolationSession()
        app = build_isolation_app(session, user_id=1)
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(settings, "upload_directory", str(Path(temp_dir) / "uploads")),
                patch.object(settings, "toc_aware_template_classification_enabled", False),
                patch.object(
                    settings,
                    "toc_aware_template_classification_persistence_enabled",
                    False,
                ),
            ):
                with TestClient(app) as client:
                    capabilities = client.get(
                        "/api/v1/filings/jobs/101/template-classification/capabilities"
                    )
                    result = client.get(
                        "/api/v1/filings/jobs/101/template-classification"
                    )
        self.assertEqual(capabilities.status_code, 200)
        self.assertFalse(capabilities.json()["enabled"])
        self.assertFalse(capabilities.json()["available"])
        self.assertEqual(result.status_code, 404)

    def test_job_cleanup_removes_classification_artifact(self):
        session = FakeIsolationSession()
        job = session.jobs[101]
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            with patch.object(settings, "upload_directory", str(uploads)):
                persist_artifacts(101)
                candidate = classification_artifact_cleanup_candidate(101)
                plan = _build_filing_job_cleanup_plan(job)
                self.assertIn(candidate, plan["file_candidates"])
                cleanup = _delete_upload_artifacts(plan["file_candidates"])
        self.assertFalse(Path(candidate[0]).exists())
        self.assertIn(
            Path(candidate[0]).resolve(),
            {Path(path).resolve() for path in cleanup["deleted_files"]},
        )


if __name__ == "__main__":
    unittest.main()
