import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from config import settings
from services.toc_aware_document_structure import (
    artifact_cleanup_candidate,
    analyze_document_structure,
    load_document_structure,
    persist_document_structure,
)
from routers.filings import _build_filing_job_cleanup_plan, _delete_upload_artifacts
from tests.test_user_isolation_filings import FakeIsolationSession, build_isolation_app


FIXTURES = Path(__file__).parent / "fixtures" / "toc_aware"


def structure_for(job_id):
    payload = json.loads((FIXTURES / "fixture_f_no_toc.json").read_text(encoding="utf-8"))
    return analyze_document_structure(
        job_id=job_id,
        azure_result=payload,
        normalized_candidates=[],
    )


class DocumentStructureApiTests(unittest.TestCase):
    def test_capabilities_and_result_are_owned_job_read_only_endpoints(self):
        session = FakeIsolationSession()
        app = build_isolation_app(session, user_id=1)
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            with (
                patch.object(settings, "upload_directory", str(uploads)),
                patch.object(settings, "toc_aware_pipeline_enabled", True),
                patch.object(settings, "toc_aware_structure_persistence_enabled", True),
                patch.object(settings, "toc_aware_llm_fallback_enabled", False),
            ):
                persist_document_structure(structure_for(101))
                persist_document_structure(structure_for(202))
                with TestClient(app) as client:
                    capabilities = client.get("/api/v1/filings/jobs/101/document-structure/capabilities")
                    result = client.get("/api/v1/filings/jobs/101/document-structure")
                    cross_capabilities = client.get("/api/v1/filings/jobs/202/document-structure/capabilities")
                    cross_result = client.get("/api/v1/filings/jobs/202/document-structure")

        self.assertEqual(capabilities.status_code, 200)
        self.assertTrue(capabilities.json()["available"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["job_id"], 101)
        self.assertEqual(cross_capabilities.status_code, 404)
        self.assertEqual(cross_result.status_code, 404)

    def test_disabled_feature_preserves_capability_visibility_but_hides_result(self):
        session = FakeIsolationSession()
        app = build_isolation_app(session, user_id=1)
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(settings, "upload_directory", str(Path(temp_dir) / "uploads")),
                patch.object(settings, "toc_aware_pipeline_enabled", False),
                patch.object(settings, "toc_aware_structure_persistence_enabled", False),
            ):
                with TestClient(app) as client:
                    capabilities = client.get("/api/v1/filings/jobs/101/document-structure/capabilities")
                    result = client.get("/api/v1/filings/jobs/101/document-structure")

        self.assertEqual(capabilities.status_code, 200)
        self.assertFalse(capabilities.json()["enabled"])
        self.assertFalse(capabilities.json()["available"])
        self.assertEqual(result.status_code, 404)

    def test_stale_artifact_is_unavailable_when_owned_job_is_in_error(self):
        session = FakeIsolationSession()
        session.jobs[101].status = "ERROR"
        app = build_isolation_app(session, user_id=1)
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            with (
                patch.object(settings, "upload_directory", str(uploads)),
                patch.object(settings, "toc_aware_pipeline_enabled", True),
                patch.object(settings, "toc_aware_structure_persistence_enabled", True),
                patch.object(settings, "toc_aware_llm_fallback_enabled", False),
            ):
                persist_document_structure(structure_for(101))
                with TestClient(app) as client:
                    capabilities = client.get(
                        "/api/v1/filings/jobs/101/document-structure/capabilities"
                    )
                    result = client.get(
                        "/api/v1/filings/jobs/101/document-structure"
                    )

        self.assertEqual(capabilities.status_code, 200)
        self.assertTrue(capabilities.json()["result_persisted"])
        self.assertFalse(capabilities.json()["available"])
        self.assertIn(
            "document_structure_unavailable_for_job_status",
            capabilities.json()["warnings"],
        )
        self.assertEqual(result.status_code, 404)

    def test_retry_upserts_one_fixed_versioned_artifact(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            with patch.object(settings, "upload_directory", str(uploads)):
                first = structure_for(101)
                second = structure_for(101)
                second.warnings.append("retry_snapshot")
                first_path = persist_document_structure(first)
                second_path = persist_document_structure(second)
                loaded = load_document_structure(101)

                self.assertEqual(first_path, second_path)
                self.assertEqual(len(list(uploads.rglob("*.json"))), 1)
                self.assertIn("retry_snapshot", loaded.warnings)

    def test_job_cleanup_plan_removes_the_derived_structure_artifact(self):
        session = FakeIsolationSession()
        job = session.jobs[101]
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            with patch.object(settings, "upload_directory", str(uploads)):
                artifact = persist_document_structure(structure_for(101))
                plan = _build_filing_job_cleanup_plan(job)
                self.assertIn(artifact_cleanup_candidate(101), plan["file_candidates"])
                cleanup = _delete_upload_artifacts(plan["file_candidates"])

        self.assertFalse(artifact.exists())
        self.assertIn(
            artifact.resolve(),
            {Path(path).resolve() for path in cleanup["deleted_files"]},
        )


if __name__ == "__main__":
    unittest.main()
