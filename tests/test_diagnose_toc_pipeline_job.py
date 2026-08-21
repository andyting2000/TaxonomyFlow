import asyncio
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from config import settings
from services.section_aware_initial_mapping import (
    build_document_initial_mapping,
    initial_mapping_artifact_path,
    persist_initial_mapping,
)
from services.section_aware_initial_mapping_llm import InitialMappingLLMConfig
from services.toc_pipeline_execution_status import PipelineExecutionStatusRecorder
from tests.section_aware_mapping_test_support import persist_mapping_sources

from scripts.diagnose_toc_pipeline_job import (
    build_diagnostic,
    exit_code_for,
    main,
    render_text,
)


class DiagnoseTocPipelineJobTests(unittest.TestCase):
    def job(self, **overrides):
        value = {
            "available": True,
            "exists": True,
            "id": 101,
            "status": "REVIEW",
            "owner_id": 26,
            "progress": 100,
            "extracted_row_count": 1,
            "warning_codes": [],
            "error_code": None,
        }
        value.update(overrides)
        return value

    def flags(self, **overrides):
        values = {
            "toc_aware_pipeline_enabled": True,
            "toc_aware_structure_persistence_enabled": True,
            "toc_aware_llm_fallback_enabled": False,
            "toc_aware_template_classification_enabled": True,
            "toc_aware_template_classification_persistence_enabled": True,
            "toc_aware_template_classification_live_llm_enabled": False,
            "toc_aware_taxonomy_candidate_retrieval_enabled": True,
            "toc_aware_initial_mapping_enabled": True,
            "toc_aware_initial_mapping_persistence_enabled": True,
            "toc_aware_initial_mapping_live_llm_enabled": False,
            "toc_aware_initial_mapping_mode": "deterministic_only",
        }
        values.update(overrides)
        return tuple(patch.object(settings, name, value) for name, value in values.items())

    def enter(self, patches):
        entered = []
        for item in patches:
            entered.append(item)
            item.__enter__()
        self.addCleanup(
            lambda: [item.__exit__(None, None, None) for item in reversed(entered)]
        )

    def persist_sources(self, *, include_mapping=False, eligible_rows=None):
        _structure, _classification, rows = persist_mapping_sources(job_id=101)
        if not include_mapping:
            return
        result = asyncio.run(
            build_document_initial_mapping(
                job_id=101,
                filing_id=101,
                source_rows=rows,
                llm_config=InitialMappingLLMConfig(mode="deterministic_only"),
            )
        )
        if eligible_rows is not None:
            result.eligible_rows = eligible_rows
            for mapping in result.mappings:
                mapping.row_eligibility.eligible = False
        persist_initial_mapping(result)

    def test_all_three_current_artifacts_are_complete_and_healthy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.enter((patch.object(settings, "upload_directory", str(Path(temp_dir) / "uploads")), *self.flags()))
            self.persist_sources(include_mapping=True)
            report = build_diagnostic(101, job_metadata=self.job())

        self.assertEqual(report["overall"], "PASS")
        self.assertEqual(exit_code_for(report), 0)
        self.assertEqual(report["artifacts"]["19A"]["status"], "PRESENT")
        self.assertEqual(report["artifacts"]["19B"]["structure_linkage"], "PASS")
        self.assertEqual(report["artifacts"]["19C"]["status"], "PRESENT")
        self.assertIn(
            "raw_heading_candidate_count",
            report["smoke_summary"]["19B"]["notes_segmentation_metrics"],
        )

    def test_missing_19c_is_incomplete_and_does_not_guess(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.enter((patch.object(settings, "upload_directory", str(Path(temp_dir) / "uploads")), *self.flags()))
            self.persist_sources()
            report = build_diagnostic(101, job_metadata=self.job())

        self.assertEqual(report["overall"], "INCOMPLETE")
        self.assertEqual(exit_code_for(report), 2)
        self.assertTrue(report["diagnosis"]["expected_to_run"])
        self.assertEqual(report["diagnosis"]["diagnosis"], "UNKNOWN")
        self.assertIn("persisted_stage_warning_or_exception", report["diagnosis"]["missing_evidence"])

    def test_disabled_mapping_feature_reports_exact_gate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.enter((patch.object(settings, "upload_directory", str(Path(temp_dir) / "uploads")), *self.flags(toc_aware_initial_mapping_enabled=False)))
            self.persist_sources()
            report = build_diagnostic(101, job_metadata=self.job())

        self.assertEqual(report["overall"], "FAIL")
        self.assertEqual(exit_code_for(report), 1)
        self.assertFalse(report["diagnosis"]["expected_to_run"])
        self.assertIn("initial_mapping_enabled=false", report["diagnosis"]["gating_reasons"])

    def test_disabled_persistence_reports_exact_gate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.enter((patch.object(settings, "upload_directory", str(Path(temp_dir) / "uploads")), *self.flags(toc_aware_initial_mapping_persistence_enabled=False)))
            self.persist_sources()
            report = build_diagnostic(101, job_metadata=self.job())

        self.assertEqual(exit_code_for(report), 1)
        self.assertIn("initial_mapping_persistence_enabled=false", report["diagnosis"]["gating_reasons"])

    def test_stale_v3_19a_is_not_treated_as_current_v4(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            self.enter((patch.object(settings, "upload_directory", str(uploads)), *self.flags()))
            job_dir = uploads / "document-structures" / "job_101"
            job_dir.mkdir(parents=True)
            (job_dir / "structure_19a_v3.json").write_text("{}", encoding="utf-8")
            report = build_diagnostic(101, job_metadata=self.job())

        self.assertEqual(report["artifacts"]["19A"]["status"], "STALE_ONLY")
        self.assertEqual(report["artifacts"]["19A"]["stale_files"], ["structure_19a_v3.json"])
        self.assertEqual(exit_code_for(report), 1)

    def test_stale_19b_is_not_treated_as_current(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            self.enter((patch.object(settings, "upload_directory", str(uploads)), *self.flags()))
            self.persist_sources()
            current = uploads / "document-structures" / "job_101" / "template_classification_19b_v2.json"
            current.rename(current.with_name("template_classification_19b_v1.json"))
            report = build_diagnostic(101, job_metadata=self.job())

        self.assertEqual(report["artifacts"]["19B"]["status"], "STALE_ONLY")
        self.assertEqual(exit_code_for(report), 1)

    def test_hash_mismatch_is_a_pipeline_problem(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            self.enter((patch.object(settings, "upload_directory", str(uploads)), *self.flags()))
            self.persist_sources()
            path = uploads / "document-structures" / "job_101" / "template_classification_19b_v2.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["source_structure_hash"] = "0" * 64
            path.write_text(json.dumps(payload), encoding="utf-8")
            report = build_diagnostic(101, job_metadata=self.job())

        self.assertEqual(report["artifacts"]["19B"]["status"], "INVALID")
        self.assertEqual(report["artifacts"]["19B"]["structure_linkage"], "FAIL")
        self.assertEqual(exit_code_for(report), 1)

    def test_zero_eligible_rows_is_visible_and_fails_health(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.enter((patch.object(settings, "upload_directory", str(Path(temp_dir) / "uploads")), *self.flags()))
            self.persist_sources(include_mapping=True, eligible_rows=0)
            report = build_diagnostic(101, job_metadata=self.job())

        self.assertEqual(report["smoke_summary"]["19C"]["eligible_rows"], 0)
        self.assertIn("initial_mapping_has_zero_eligible_rows", report["problems"])
        self.assertEqual(exit_code_for(report), 1)

    def test_warning_only_pipeline_exception_identifies_reached_failure_branch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.enter((patch.object(settings, "upload_directory", str(Path(temp_dir) / "uploads")), *self.flags()))
            self.persist_sources()
            report = build_diagnostic(
                101,
                job_metadata=self.job(warning_codes=["toc_aware_initial_mapping_failed"]),
            )

        self.assertEqual(report["diagnosis"]["diagnosis"], "INITIAL_MAPPING_STAGE_FAILED")
        self.assertTrue(report["diagnosis"]["pipeline_stage_reached"])
        self.assertEqual(exit_code_for(report), 1)

    def test_execution_telemetry_replaces_unknown_with_exact_skip_reason(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.enter((patch.object(settings, "upload_directory", str(Path(temp_dir) / "uploads")), *self.flags(toc_aware_initial_mapping_enabled=False)))
            self.persist_sources()
            recorder = PipelineExecutionStatusRecorder.create(101)
            for stage in (
                "19C_candidate_retrieval",
                "19C_mapping_build",
                "19C_persistence",
            ):
                recorder.transition(stage, "skipped", reason_code="feature_disabled")
            recorder.finish("completed")
            report = build_diagnostic(101, job_metadata=self.job())

        self.assertEqual(report["pipeline_execution_status"]["status"], "PRESENT")
        self.assertEqual(report["diagnosis"]["diagnosis"], "INITIAL_MAPPING_STAGE_SKIPPED")
        self.assertEqual(report["diagnosis"]["reason_code"], "feature_disabled")
        self.assertEqual(report["diagnosis"]["missing_evidence"], [])
        self.assertNotEqual(report["diagnosis"]["diagnosis"], "UNKNOWN")

    def test_execution_telemetry_reports_exact_writer_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.enter((patch.object(settings, "upload_directory", str(Path(temp_dir) / "uploads")), *self.flags()))
            self.persist_sources()
            recorder = PipelineExecutionStatusRecorder.create(101)
            recorder.transition("19C_candidate_retrieval", "completed", eligible_rows=1, candidate_sets=1)
            recorder.transition("19C_mapping_build", "completed", mapped_rows=1)
            recorder.writer_transition("writer_invoked")
            recorder.writer_transition("serialization_completed")
            recorder.fail("19C_persistence", "artifact_write_failed", OSError("private path"))
            recorder.finish("completed")
            report = build_diagnostic(101, job_metadata=self.job())

        self.assertEqual(report["diagnosis"]["diagnosis"], "INITIAL_MAPPING_STAGE_FAILED")
        self.assertEqual(report["diagnosis"]["stage"], "19C_persistence")
        self.assertEqual(report["diagnosis"]["reason_code"], "artifact_write_failed")
        self.assertEqual(report["diagnosis"]["exception_class"], "OSError")
        self.assertTrue(
            report["pipeline_execution_status"]["stages"]["19C_persistence"]["writer_invoked"]
        )

    def test_execution_time_config_hash_detects_stale_worker(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.enter((patch.object(settings, "upload_directory", str(Path(temp_dir) / "uploads")), *self.flags()))
            self.persist_sources()
            with patch.object(settings, "toc_aware_initial_mapping_enabled", False):
                recorder = PipelineExecutionStatusRecorder.create(101)
                for stage in (
                    "19C_candidate_retrieval",
                    "19C_mapping_build",
                    "19C_persistence",
                ):
                    recorder.transition(stage, "skipped", reason_code="feature_disabled")
                recorder.finish("completed")
            report = build_diagnostic(101, job_metadata=self.job())

        execution = report["pipeline_execution_status"]
        self.assertEqual(execution["safe_config_comparison"], "DIFFERENT")
        self.assertIn(
            "TOC_AWARE_INITIAL_MAPPING_ENABLED",
            {item["name"] for item in execution["config_differences"]},
        )
        self.assertEqual(report["diagnosis"]["reason_code"], "feature_disabled")

    def test_secret_values_never_appear_in_text_or_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "MODEL_API_TOKEN=hf_super_secret\n"
                "TOC_AWARE_INITIAL_MAPPING_ENABLED=true\n"
                "TOC_AWARE_INITIAL_MAPPING_ENABLED=false\n",
                encoding="utf-8",
            )
            self.enter((patch.object(settings, "upload_directory", str(Path(temp_dir) / "uploads")), patch.object(settings, "model_api_token", "hf_super_secret"), *self.flags(toc_aware_initial_mapping_enabled=False)))
            report = build_diagnostic(
                101,
                job_metadata=self.job(
                    warning_codes=["provider warning hf_super_secret"],
                    error_code="Bearer hf_super_secret",
                ),
                env_path=env_path,
            )

        output = render_text(report) + json.dumps(report)
        self.assertNotIn("hf_super_secret", output)
        self.assertNotIn("MODEL_API_TOKEN", output)
        self.assertIn("TOC_AWARE_INITIAL_MAPPING_ENABLED", output)

    def test_diagnostic_does_not_change_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            self.enter((patch.object(settings, "upload_directory", str(uploads)), *self.flags()))
            self.persist_sources(include_mapping=True)
            before = {
                path.relative_to(uploads).as_posix(): path.read_bytes()
                for path in uploads.rglob("*")
                if path.is_file()
            }
            with (
                patch("services.section_aware_initial_mapping.build_document_initial_mapping") as build,
                patch("services.section_aware_initial_mapping.persist_initial_mapping") as persist,
            ):
                report = build_diagnostic(101, job_metadata=self.job())
            after = {
                path.relative_to(uploads).as_posix(): path.read_bytes()
                for path in uploads.rglob("*")
                if path.is_file()
            }

        self.assertEqual(report["safety"]["database_writes"], 0)
        self.assertEqual(before, after)
        build.assert_not_called()
        persist.assert_not_called()

    def test_json_output_is_machine_readable(self):
        expected = {
            "job_id": 101,
            "overall": "INCOMPLETE",
            "exit_code": 2,
            "read_only": True,
        }
        output = StringIO()
        with (
            patch("scripts.diagnose_toc_pipeline_job.build_diagnostic", return_value=expected),
            redirect_stdout(output),
        ):
            code = main(["101", "--json"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue()), expected)

    def test_exit_code_contract_and_invalid_input(self):
        self.assertEqual(exit_code_for({"overall": "PASS"}), 0)
        self.assertEqual(exit_code_for({"overall": "FAIL"}), 1)
        self.assertEqual(exit_code_for({"overall": "INCOMPLETE"}), 2)
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["0"]), 3)
            self.assertEqual(main(["not-a-job"]), 3)


if __name__ == "__main__":
    unittest.main()
