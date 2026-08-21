from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from config import settings
from schemas import JobStatus
from services.section_aware_initial_mapping import (
    initial_mapping_artifact_path,
    load_initial_mapping,
)
from services.toc_pipeline_execution_status import load_pipeline_execution_status
from tests import test_toc_aware_pipeline_integration as pipeline_support


class TocAwareInitialMappingIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def run_pipeline(
        self,
        uploads,
        *,
        enabled=True,
        fail=False,
        retrieval_enabled=None,
        mapping_enabled=None,
        persistence_enabled=None,
        failure_target=None,
    ):
        helper = pipeline_support.TocAwarePipelineIntegrationTests(methodName="runTest")
        retrieval = enabled if retrieval_enabled is None else retrieval_enabled
        mapping = enabled if mapping_enabled is None else mapping_enabled
        persistence = enabled if persistence_enabled is None else persistence_enabled
        patches = [
            patch.object(settings, "toc_aware_template_classification_enabled", enabled),
            patch.object(settings, "toc_aware_template_classification_persistence_enabled", enabled),
            patch.object(settings, "toc_aware_template_classification_live_llm_enabled", False),
            patch.object(settings, "toc_aware_taxonomy_candidate_retrieval_enabled", retrieval),
            patch.object(settings, "toc_aware_initial_mapping_enabled", mapping),
            patch.object(settings, "toc_aware_initial_mapping_persistence_enabled", persistence),
            patch.object(settings, "toc_aware_initial_mapping_live_llm_enabled", False),
            patch.object(settings, "toc_aware_initial_mapping_mode", "deterministic_only"),
        ]
        if fail:
            patches.append(
                patch(
                    "services.section_aware_initial_mapping.build_document_initial_mapping",
                    side_effect=RuntimeError("synthetic initial mapping failure"),
                )
            )
        if failure_target:
            patches.append(
                patch(
                    failure_target,
                    side_effect=OSError("synthetic artifact publication failure"),
                )
            )
        entered = []
        try:
            for item in patches:
                entered.append(item)
                item.__enter__()
            return await helper.run_job(uploads, enabled=enabled, persistence=enabled)
        finally:
            for item in reversed(entered):
                item.__exit__(None, None, None)

    async def test_enabled_pipeline_publishes_advisory_artifact_without_mapping_mutation(self):
        with tempfile.TemporaryDirectory() as disabled_temp, tempfile.TemporaryDirectory() as enabled_temp:
            disabled = await self.run_pipeline(Path(disabled_temp) / "uploads", enabled=False)
            enabled_uploads = Path(enabled_temp) / "uploads"
            enabled = await self.run_pipeline(enabled_uploads, enabled=True)
            with patch.object(settings, "upload_directory", str(enabled_uploads)):
                artifact = load_initial_mapping(16)
                execution = load_pipeline_execution_status(16)
        disabled_result, _disabled_session, disabled_provider, disabled_snapshot = disabled
        enabled_result, enabled_session, enabled_provider, enabled_snapshot = enabled
        self.assertEqual(disabled_result.status, JobStatus.REVIEW)
        self.assertEqual(enabled_result.status, JobStatus.REVIEW)
        self.assertEqual(disabled_provider.call_count, 1)
        self.assertEqual(enabled_provider.call_count, 1)
        self.assertEqual(enabled_snapshot, disabled_snapshot)
        self.assertTrue(all(item.confirmed_tag_id is None for item in enabled_session.added_items))
        self.assertEqual(artifact.llm_calls, 0)
        self.assertEqual(artifact.safety_summary["existing_mapping_suggestion_mutations"], 0)
        self.assertEqual(artifact.safety_summary["template_field_mutations"], 0)
        self.assertEqual(artifact.safety_summary["confirmed_tag_id_mutations"], 0)
        self.assertEqual(artifact.safety_summary["final_mapping_mutations"], 0)
        self.assertEqual(artifact.safety_summary["template_group_leakage_count"], 0)
        self.assertEqual(execution["status"], "completed")
        self.assertEqual(execution["stages"]["19A_analysis"]["version"], "19A-v4")
        self.assertEqual(execution["stages"]["19A_persistence"]["version"], "19A-v4")
        self.assertEqual(execution["stages"]["19C_candidate_retrieval"]["status"], "completed")
        self.assertEqual(execution["stages"]["19C_mapping_build"]["status"], "completed")
        self.assertEqual(execution["stages"]["19C_persistence"]["status"], "completed")
        self.assertTrue(
            all(
                execution["stages"]["19C_persistence"][field]
                for field in (
                    "writer_invoked",
                    "serialization_completed",
                    "atomic_temp_write_completed",
                    "rename_completed",
                    "post_write_validation_completed",
                )
            )
        )

    async def test_failure_is_warning_only_and_preserves_19a_19b(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            result, _session, provider, _snapshot = await self.run_pipeline(uploads, enabled=True, fail=True)
            with patch.object(settings, "upload_directory", str(uploads)):
                artifact_exists = initial_mapping_artifact_path(16).exists()
                execution = load_pipeline_execution_status(16)
            structure_exists = any(uploads.rglob("structure_19a_v4.json"))
            classification_exists = any(uploads.rglob("template_classification_19b_v2.json"))
        self.assertEqual(result.status, JobStatus.REVIEW)
        self.assertEqual(provider.call_count, 1)
        self.assertIn("toc_aware_initial_mapping_failed", {warning["code"] for warning in result.warnings})
        self.assertFalse(artifact_exists)
        self.assertTrue(structure_exists)
        self.assertTrue(classification_exists)
        self.assertEqual(execution["stages"]["19C_mapping_build"]["status"], "failed")
        self.assertEqual(
            execution["stages"]["19C_mapping_build"]["reason_code"],
            "mapping_build_failed",
        )
        self.assertEqual(execution["stages"]["19C_persistence"]["status"], "skipped")

    async def test_row_local_retrieval_failure_still_publishes_19c_artifact(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            with patch(
                "services.section_aware_initial_mapping.retrieve_section_aware_candidates",
                side_effect=RuntimeError("synthetic row-local retrieval failure"),
            ):
                result, _session, _provider, _snapshot = await self.run_pipeline(
                    uploads,
                    enabled=True,
                )
            with patch.object(settings, "upload_directory", str(uploads)):
                artifact = load_initial_mapping(16)
                execution = load_pipeline_execution_status(16)

        retrieval = execution["stages"]["19C_candidate_retrieval"]
        self.assertEqual(result.status, JobStatus.REVIEW)
        self.assertEqual(retrieval["status"], "completed")
        self.assertGreater(retrieval["rows_failed_locally"], 0)
        self.assertTrue(retrieval["row_errors"])
        self.assertEqual(execution["stages"]["19C_mapping_build"]["status"], "completed")
        self.assertEqual(execution["stages"]["19C_persistence"]["status"], "completed")
        self.assertEqual(artifact.failed_rows, retrieval["rows_failed_locally"])
        self.assertEqual(artifact.llm_calls, 0)
        self.assertEqual(artifact.safety_summary["confirmed_tag_id_mutations"], 0)

    async def test_retry_invalidates_artifact_when_feature_is_disabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            await self.run_pipeline(uploads, enabled=True)
            with patch.object(settings, "upload_directory", str(uploads)):
                self.assertTrue(initial_mapping_artifact_path(16).is_file())
                stale = initial_mapping_artifact_path(16).with_name("initial_mapping_19c_v1.json")
                stale.write_text("stale-v1", encoding="utf-8")
            result, _session, _provider, _snapshot = await self.run_pipeline(uploads, enabled=False)
            with patch.object(settings, "upload_directory", str(uploads)):
                exists = initial_mapping_artifact_path(16).exists()
                stale_exists = stale.exists()
                execution = load_pipeline_execution_status(16)
        self.assertEqual(result.status, JobStatus.REVIEW)
        self.assertFalse(exists)
        self.assertFalse(stale_exists)
        self.assertEqual(
            execution["stages"]["19C_candidate_retrieval"]["reason_code"],
            "feature_disabled",
        )

    async def test_partial_feature_and_persistence_config_get_exact_skip_reasons(self):
        cases = (
            ({"retrieval_enabled": False}, "feature_disabled"),
            ({"persistence_enabled": False}, "persistence_disabled"),
        )
        for overrides, reason in cases:
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as temp_dir:
                uploads = Path(temp_dir) / "uploads"
                result, _session, _provider, _snapshot = await self.run_pipeline(
                    uploads,
                    enabled=True,
                    **overrides,
                )
                with patch.object(settings, "upload_directory", str(uploads)):
                    execution = load_pipeline_execution_status(16)
                self.assertEqual(result.status, JobStatus.REVIEW)
                self.assertEqual(
                    execution["stages"]["19C_candidate_retrieval"]["status"],
                    "skipped",
                )
                self.assertEqual(
                    execution["stages"]["19C_candidate_retrieval"]["reason_code"],
                    reason,
                )

    async def test_publication_failures_persist_exact_reason_and_writer_progress(self):
        cases = (
            (
                "services.section_aware_initial_mapping._serialize_initial_mapping",
                "artifact_serialization_failed",
                (),
            ),
            (
                "services.section_aware_initial_mapping._write_initial_mapping_temp",
                "artifact_write_failed",
                ("writer_invoked", "serialization_completed"),
            ),
            (
                "services.section_aware_initial_mapping._validate_published_initial_mapping",
                "artifact_validation_failed",
                (
                    "writer_invoked",
                    "serialization_completed",
                    "atomic_temp_write_completed",
                    "rename_completed",
                ),
            ),
        )
        for target, reason, completed_fields in cases:
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as temp_dir:
                uploads = Path(temp_dir) / "uploads"
                result, _session, _provider, _snapshot = await self.run_pipeline(
                    uploads,
                    enabled=True,
                    failure_target=target,
                )
                with patch.object(settings, "upload_directory", str(uploads)):
                    execution = load_pipeline_execution_status(16)
                    artifact_exists = initial_mapping_artifact_path(16).exists()
                persistence = execution["stages"]["19C_persistence"]
                self.assertEqual(result.status, JobStatus.REVIEW)
                self.assertEqual(persistence["status"], "failed")
                self.assertEqual(persistence["reason_code"], reason)
                self.assertTrue(persistence["writer_invoked"])
                self.assertTrue(all(persistence[field] for field in completed_fields))
                self.assertFalse(artifact_exists)

    def test_flags_default_false_and_no_frontend_panel_exists(self):
        with (
            patch.object(settings, "toc_aware_taxonomy_candidate_retrieval_enabled", False),
            patch.object(settings, "toc_aware_initial_mapping_enabled", False),
            patch.object(settings, "toc_aware_initial_mapping_persistence_enabled", False),
            patch.object(settings, "toc_aware_initial_mapping_live_llm_enabled", False),
        ):
            self.assertFalse(settings.toc_aware_taxonomy_candidate_retrieval_enabled)
            self.assertFalse(settings.toc_aware_initial_mapping_enabled)
            self.assertFalse(settings.toc_aware_initial_mapping_persistence_enabled)
            self.assertFalse(settings.toc_aware_initial_mapping_live_llm_enabled)
        workspace = (Path(__file__).resolve().parents[1] / "frontend/src/review-workspace.jsx").read_text(encoding="utf-8")
        self.assertNotIn("initial-mapping", workspace)
        self.assertNotIn("Initial Mapping", workspace)


if __name__ == "__main__":
    unittest.main()
