import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from config import settings
from services.toc_pipeline_execution_status import (
    PIPELINE_STAGE_NAMES,
    REASON_CODES,
    PipelineExecutionStatusRecorder,
    build_safe_config_snapshot,
    load_pipeline_execution_status,
    pipeline_execution_status_artifact_path,
    safe_config_hash,
)


class TocPipelineExecutionStatusTests(unittest.TestCase):
    def enabled_settings(self):
        return (
            patch.object(settings, "extraction_pipeline", "azure_di"),
            patch.object(settings, "toc_aware_pipeline_enabled", True),
            patch.object(settings, "toc_aware_structure_persistence_enabled", True),
            patch.object(settings, "toc_aware_template_classification_enabled", True),
            patch.object(settings, "toc_aware_template_classification_persistence_enabled", True),
            patch.object(settings, "toc_aware_template_classification_live_llm_enabled", False),
            patch.object(settings, "toc_aware_taxonomy_candidate_retrieval_enabled", True),
            patch.object(settings, "toc_aware_initial_mapping_enabled", True),
            patch.object(settings, "toc_aware_initial_mapping_persistence_enabled", True),
            patch.object(settings, "toc_aware_initial_mapping_live_llm_enabled", False),
            patch.object(settings, "toc_aware_initial_mapping_mode", "deterministic_only"),
            patch.object(settings, "toc_aware_initial_mapping_max_rows_per_job", 5000),
            patch.object(settings, "toc_aware_initial_mapping_max_candidates", 8),
            patch.object(settings, "toc_aware_initial_mapping_max_concurrent_calls", 1),
            patch.object(settings, "toc_aware_initial_mapping_row_timeout_seconds", 120.0),
        )

    def enter(self, contexts):
        entered = []
        for context in contexts:
            context.__enter__()
            entered.append(context)
        self.addCleanup(
            lambda: [context.__exit__(None, None, None) for context in reversed(entered)]
        )

    def test_creation_persists_only_whitelisted_safe_config_and_canonical_hash(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            self.enter(
                (
                    patch.object(settings, "upload_directory", str(uploads)),
                    patch.object(settings, "model_api_token", "hf_do_not_persist"),
                    patch.object(settings, "database_url", "postgresql://secret@localhost/db"),
                    *self.enabled_settings(),
                )
            )
            recorder = PipelineExecutionStatusRecorder.create(
                101,
                pipeline_run_id="run-test-101",
            )
            loaded = load_pipeline_execution_status(101)
            raw = pipeline_execution_status_artifact_path(101).read_text(encoding="utf-8")

        expected = build_safe_config_snapshot(settings)
        self.assertEqual(loaded["pipeline_run_id"], "run-test-101")
        self.assertEqual(loaded["effective_safe_config"], expected)
        self.assertEqual(loaded["safe_config_hash"], safe_config_hash(expected))
        self.assertEqual(set(loaded["stages"]), set(PIPELINE_STAGE_NAMES))
        self.assertNotIn("hf_do_not_persist", raw)
        self.assertNotIn("postgresql://", raw)
        self.assertNotIn("TOKEN", json.dumps(loaded["effective_safe_config"]))
        self.assertIsNone(recorder.data["completed_at"])

    def test_stage_and_writer_transitions_are_durable_and_bounded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            self.enter((patch.object(settings, "upload_directory", str(uploads)), *self.enabled_settings()))
            recorder = PipelineExecutionStatusRecorder.create(101, pipeline_run_id="run-stage")
            recorder.transition("19C_candidate_retrieval", "started", source_rows=14)
            recorder.transition(
                "19C_candidate_retrieval",
                "completed",
                eligible_rows=12,
                candidate_sets=12,
            )
            recorder.transition("19C_mapping_build", "started", mode="deterministic_only")
            recorder.transition("19C_mapping_build", "completed", mapped_rows=9)
            for field in (
                "writer_invoked",
                "serialization_completed",
                "atomic_temp_write_completed",
                "rename_completed",
                "post_write_validation_completed",
            ):
                recorder.writer_transition(field)
            recorder.transition(
                "19C_persistence",
                "completed",
                artifact_path="initial_mapping_19c_v2.json",
            )
            recorder.finish("completed")
            loaded = load_pipeline_execution_status(101)
            artifact_size = pipeline_execution_status_artifact_path(101).stat().st_size

        self.assertEqual(loaded["status"], "completed")
        self.assertIsNotNone(loaded["completed_at"])
        self.assertEqual(loaded["stages"]["19C_candidate_retrieval"]["eligible_rows"], 12)
        self.assertTrue(all(loaded["stages"]["19C_persistence"][field] for field in (
            "writer_invoked",
            "serialization_completed",
            "atomic_temp_write_completed",
            "rename_completed",
            "post_write_validation_completed",
        )))
        self.assertLess(artifact_size, 128 * 1024)

    def test_required_outcomes_accept_exact_stable_reasons(self):
        required = {
            "feature_disabled",
            "persistence_disabled",
            "upstream_structure_missing",
            "upstream_structure_invalid",
            "upstream_classification_missing",
            "upstream_classification_invalid",
            "upstream_hash_mismatch",
            "registry_hash_mismatch",
            "concept_inventory_unavailable",
            "row_limit_exceeded",
            "zero_eligible_rows",
            "candidate_retrieval_failed",
            "mapping_build_failed",
            "artifact_serialization_failed",
            "artifact_write_failed",
            "artifact_validation_failed",
            "upstream_requires_review",
            "unexpected_exception",
        }
        self.assertTrue(required.issubset(REASON_CODES))
        with tempfile.TemporaryDirectory() as temp_dir:
            self.enter((patch.object(settings, "upload_directory", str(Path(temp_dir) / "uploads")), *self.enabled_settings()))
            recorder = PipelineExecutionStatusRecorder.create(101)
            for reason in sorted(required):
                recorder.transition("19C_mapping_build", "failed", reason_code=reason)
            with self.assertRaisesRegex(ValueError, "reason_code"):
                recorder.transition("19C_mapping_build", "failed", reason_code="free text failure")


if __name__ == "__main__":
    unittest.main()
