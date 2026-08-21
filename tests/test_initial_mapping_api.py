import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from config import settings
from fastapi.testclient import TestClient
from routers.filings import _build_filing_job_cleanup_plan, _delete_upload_artifacts
from services.section_aware_initial_mapping import (
    build_document_initial_mapping,
    initial_mapping_artifact_cleanup_candidate,
    initial_mapping_artifact_cleanup_candidates,
    persist_initial_mapping,
)
from services.section_aware_initial_mapping_llm import InitialMappingLLMConfig
from tests.section_aware_mapping_test_support import persist_mapping_sources
from tests.test_user_isolation_filings import FakeIsolationSession, build_isolation_app


def persist_initial_artifact(job_id):
    _structure, _classification, rows = persist_mapping_sources(job_id=job_id)
    result = asyncio.run(
        build_document_initial_mapping(
            job_id=job_id,
            filing_id=job_id,
            source_rows=rows,
            llm_config=InitialMappingLLMConfig(mode="deterministic_only"),
        )
    )
    persist_initial_mapping(result)
    return result


class InitialMappingApiTests(unittest.TestCase):
    def flags(self):
        return (
            patch.object(settings, "toc_aware_taxonomy_candidate_retrieval_enabled", True),
            patch.object(settings, "toc_aware_initial_mapping_enabled", True),
            patch.object(settings, "toc_aware_initial_mapping_persistence_enabled", True),
            patch.object(settings, "toc_aware_initial_mapping_live_llm_enabled", False),
            patch.object(settings, "toc_aware_initial_mapping_mode", "deterministic_only"),
        )

    def test_owned_read_only_capabilities_artifact_and_row_endpoints(self):
        session = FakeIsolationSession()
        app = build_isolation_app(session, user_id=1)
        with tempfile.TemporaryDirectory() as temp_dir:
            patches = (patch.object(settings, "upload_directory", str(Path(temp_dir) / "uploads")), *self.flags())
            entered = []
            try:
                for item in patches:
                    entered.append(item)
                    item.__enter__()
                owned = persist_initial_artifact(101)
                persist_initial_artifact(202)
                row_id = owned.mappings[0].source_row_id
                with TestClient(app) as client:
                    capabilities = client.get("/api/v1/filings/jobs/101/initial-mapping/capabilities")
                    result = client.get("/api/v1/filings/jobs/101/initial-mapping")
                    row = client.get(f"/api/v1/filings/jobs/101/initial-mapping/rows/{row_id}")
                    cross = client.get("/api/v1/filings/jobs/202/initial-mapping")
            finally:
                for item in reversed(entered):
                    item.__exit__(None, None, None)
        self.assertEqual(capabilities.status_code, 200)
        self.assertTrue(capabilities.json()["available"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["job_id"], 101)
        self.assertEqual(row.status_code, 200)
        self.assertEqual(row.json()["source_row_id"], row_id)
        self.assertEqual(cross.status_code, 404)

    def test_disabled_feature_hides_artifact_and_cleanup_removes_it(self):
        session = FakeIsolationSession()
        app = build_isolation_app(session, user_id=1)
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            with (
                patch.object(settings, "upload_directory", str(uploads)),
                patch.object(settings, "toc_aware_taxonomy_candidate_retrieval_enabled", False),
                patch.object(settings, "toc_aware_initial_mapping_enabled", False),
                patch.object(settings, "toc_aware_initial_mapping_persistence_enabled", False),
                patch.object(settings, "toc_aware_initial_mapping_live_llm_enabled", False),
            ):
                persist_initial_artifact(101)
                candidate = initial_mapping_artifact_cleanup_candidate(101)
                stale_candidate = initial_mapping_artifact_cleanup_candidates(101)[1]
                Path(stale_candidate[0]).write_text("stale-v1", encoding="utf-8")
                with TestClient(app) as client:
                    capabilities = client.get("/api/v1/filings/jobs/101/initial-mapping/capabilities")
                    result = client.get("/api/v1/filings/jobs/101/initial-mapping")
                plan = _build_filing_job_cleanup_plan(session.jobs[101])
                self.assertIn(candidate, plan["file_candidates"])
                self.assertIn(stale_candidate, plan["file_candidates"])
                cleanup = _delete_upload_artifacts(plan["file_candidates"])
        self.assertEqual(capabilities.status_code, 200)
        self.assertFalse(capabilities.json()["available"])
        self.assertEqual(result.status_code, 404)
        self.assertFalse(Path(candidate[0]).exists())
        self.assertFalse(Path(stale_candidate[0]).exists())
        self.assertIn(Path(candidate[0]).resolve(), {Path(path).resolve() for path in cleanup["deleted_files"]})


if __name__ == "__main__":
    unittest.main()
