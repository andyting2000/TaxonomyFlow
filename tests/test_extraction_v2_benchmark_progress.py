import asyncio
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.run_extraction_v2 as runner


def fake_manifest() -> dict:
    return {
        "cases": [
            {
                "case_id": "case-001",
                "case_dir": "benchmark_cases/case-001",
                "pdf_path": "case-001.pdf",
                "reference_available": True,
                "reference_path": "source.xml",
                "reference_type": "xml",
                "status": "ready",
            }
        ]
    }


def hf_candidate(case_id: str = "case-001", page_number: int = 1) -> dict:
    return {
        "case_id": case_id,
        "source_pdf": f"{case_id}.pdf",
        "page_number": page_number,
        "extraction_method": "huggingface_vision_fallback",
        "row_type": "text_block",
        "statement_section": "Directors Report",
        "label": "Directors Report",
        "value": None,
        "previous_value": None,
        "current_year": None,
        "prior_year": None,
        "text": "The directors present their report.",
        "source_snippet": "The directors present their report.",
        "confidence": 0.8,
        "warnings": ["huggingface_vision_fallback", "text_block_not_numeric"],
        "provenance": {"page_number": page_number},
    }


def case_report(case_id: str, candidates: list[dict] | None = None, *, skipped_resume: int = 0) -> dict:
    candidates = candidates or []
    return {
        "case_id": case_id,
        "case_dir": f"benchmark_cases/{case_id}",
        "source_pdf": f"{case_id}.pdf",
        "reference_available": True,
        "reference_path": "source.xml",
        "reference_type": "xml",
        "status": "ok",
        "stages": [],
        "pages_analyzed": 1,
        "candidate_count": len(candidates),
        "native_candidate_count": 0,
        "huggingface_candidate_count": sum(1 for item in candidates if item.get("extraction_method") == "huggingface_vision_fallback"),
        "openai_candidate_count": 0,
        "vision_fallback": {
            "enabled": True,
            "provider": "huggingface",
            "pages_attempted": 0 if skipped_resume else 1,
            "pages_succeeded": 0 if skipped_resume else 1,
            "pages_failed": 0,
            "pages_skipped_max_limit": 0,
            "pages_skipped_resume": skipped_resume,
            "candidates_returned": 0 if skipped_resume else len(candidates),
            "candidates_kept": len(candidates),
            "duplicate_candidates_skipped": 0,
            "failures": [],
            "raw_response_preview_count": 0 if skipped_resume else 1,
            "parser_recovered_candidates": 0 if skipped_resume else len(candidates),
            "parser_failed_pages": 0,
            "empty_candidate_pages": 0,
            "no_relevant_content_pages": 0,
            "parser_failure_reasons": {},
        },
        "huggingface_fallback": {
            "enabled": True,
            "provider": "huggingface",
            "pages_attempted": 0 if skipped_resume else 1,
            "pages_succeeded": 0 if skipped_resume else 1,
            "pages_failed": 0,
            "pages_skipped_max_limit": 0,
            "pages_skipped_resume": skipped_resume,
            "candidates_returned": 0 if skipped_resume else len(candidates),
            "candidates_kept": len(candidates),
            "duplicate_candidates_skipped": 0,
            "failures": [],
            "raw_response_preview_count": 0 if skipped_resume else 1,
            "parser_recovered_candidates": 0 if skipped_resume else len(candidates),
            "parser_failed_pages": 0,
            "empty_candidate_pages": 0,
            "no_relevant_content_pages": 0,
            "parser_failure_reasons": {},
        },
        "openai_fallback": {"enabled": False},
        "vision_page_timings": [
            {
                "case_id": case_id,
                "page_number": 1,
                "provider": "huggingface",
                "elapsed_seconds": 0.1,
                "succeeded": True,
                "candidate_count": len(candidates),
            }
        ],
        "row_type_counts": {"text_block": len(candidates)} if candidates else {},
        "warning_counts": {},
        "warnings": [],
        "candidates": candidates,
    }


def no_vision_case_report(case_id: str) -> dict:
    report = case_report(case_id, [])
    report["vision_fallback"] = {"enabled": False}
    report["huggingface_fallback"] = {"enabled": False}
    report["vision_page_timings"] = []
    return report


class FakePipeline:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.progress_callback = kwargs.get("progress_callback")
        self.completed_vision_pages = kwargs.get("completed_vision_pages") or {}
        FakePipeline.instances.append(self)

    async def run_case(self, case, *, limit_pages=None, initial_candidates=None, completed_vision_pages=None):
        initial_candidates = list(initial_candidates or [])
        completed = set(completed_vision_pages or [])
        self.progress_callback(
            {"event": "case_start", "case_id": case.case_id, "source_pdf": case.pdf_path, "total_pages": 1}
        )
        self.progress_callback(
            {
                "event": "native_page_complete",
                "case_id": case.case_id,
                "source_pdf": case.pdf_path,
                "page_number": 1,
                "total_pages": 1,
                "native_candidate_count": 0,
                "native_numeric_or_text_count": 0,
            }
        )
        if not self.kwargs.get("use_vision_fallback"):
            return no_vision_case_report(case.case_id)
        if 1 in completed:
            self.progress_callback(
                {
                    "event": "vision_page_skipped",
                    "case_id": case.case_id,
                    "source_pdf": case.pdf_path,
                    "page_number": 1,
                    "provider": "huggingface",
                    "reason": "resume_completed",
                }
            )
            return case_report(case.case_id, initial_candidates, skipped_resume=1)
        candidate = hf_candidate(case.case_id)
        self.progress_callback(
            {
                "event": "vision_page_start",
                "case_id": case.case_id,
                "source_pdf": case.pdf_path,
                "page_number": 1,
                "total_pages": 1,
                "provider": "huggingface",
            }
        )
        self.progress_callback(
            {
                "event": "vision_page_complete",
                "case_id": case.case_id,
                "source_pdf": case.pdf_path,
                "page_number": 1,
                "total_pages": 1,
                "provider": "huggingface",
                "succeeded": True,
                "candidate_count": 1,
                "elapsed_seconds": 0.1,
                "diagnostics": {
                    "raw_response_preview": '{"candidates":[...]}',
                    "raw_response_type": "str",
                    "parsed_json_detected": True,
                    "parsed_json_top_level_keys": ["candidates"],
                    "normalized_candidate_count": 1,
                    "parser_failure_reason": None,
                    "parser_status": "preferred_candidates_returned",
                },
                "candidates": [candidate],
            }
        )
        return case_report(case.case_id, runner.dedupe_candidate_dicts(initial_candidates + [candidate]))


class InterruptingPipeline(FakePipeline):
    async def run_case(self, case, *, limit_pages=None, initial_candidates=None, completed_vision_pages=None):
        await super().run_case(
            case,
            limit_pages=limit_pages,
            initial_candidates=initial_candidates,
            completed_vision_pages=completed_vision_pages,
        )
        raise KeyboardInterrupt()


class ResumeLimitPipeline(FakePipeline):
    attempted_pages: list[int] = []
    skipped_pages: list[tuple[int, str]] = []
    run_cases: list[str] = []

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.attempted_total = int(kwargs.get("previous_vision_pages_attempted") or 0)
        self._vision_pages_attempted_total = self.attempted_total

    async def run_case(self, case, *, limit_pages=None, initial_candidates=None, completed_vision_pages=None):
        ResumeLimitPipeline.run_cases.append(case.case_id)
        initial_candidates = list(initial_candidates or [])
        completed = set(completed_vision_pages or [])
        candidates = list(initial_candidates)
        skipped_resume = 0
        skipped_max = 0
        attempted = 0
        max_pages = self.kwargs.get("vision_max_pages")
        self.progress_callback(
            {"event": "case_start", "case_id": case.case_id, "source_pdf": case.pdf_path, "total_pages": 3}
        )
        for page in (1, 2, 3):
            self.progress_callback(
                {
                    "event": "native_page_complete",
                    "case_id": case.case_id,
                    "source_pdf": case.pdf_path,
                    "page_number": page,
                    "total_pages": 3,
                    "native_candidate_count": 0,
                    "native_numeric_or_text_count": 0,
                    "native_text_length": 0,
                }
            )
            if page in completed:
                skipped_resume += 1
                ResumeLimitPipeline.skipped_pages.append((page, "resume_completed"))
                self.progress_callback(
                    {
                        "event": "vision_page_skipped",
                        "case_id": case.case_id,
                        "source_pdf": case.pdf_path,
                        "page_number": page,
                        "provider": "huggingface",
                        "reason": "resume_completed",
                    }
                )
                continue
            if max_pages is not None and self.attempted_total >= max_pages:
                skipped_max += 1
                ResumeLimitPipeline.skipped_pages.append((page, "max_limit_reached"))
                self.progress_callback(
                    {
                        "event": "vision_page_skipped",
                        "case_id": case.case_id,
                        "source_pdf": case.pdf_path,
                        "page_number": page,
                        "provider": "huggingface",
                        "reason": "max_limit_reached",
                    }
                )
                continue
            candidate = hf_candidate(case.case_id, page)
            attempted += 1
            self.attempted_total += 1
            self._vision_pages_attempted_total = self.attempted_total
            ResumeLimitPipeline.attempted_pages.append(page)
            self.progress_callback(
                {
                    "event": "vision_page_start",
                    "case_id": case.case_id,
                    "source_pdf": case.pdf_path,
                    "page_number": page,
                    "total_pages": 3,
                    "provider": "huggingface",
                }
            )
            self.progress_callback(
                {
                    "event": "vision_page_complete",
                    "case_id": case.case_id,
                    "source_pdf": case.pdf_path,
                    "page_number": page,
                    "total_pages": 3,
                    "provider": "huggingface",
                    "succeeded": True,
                    "candidate_count": 1,
                    "elapsed_seconds": 0.1,
                    "diagnostics": {"normalized_candidate_count": 1, "parser_status": "preferred_candidates_returned"},
                    "candidates": [candidate],
                }
            )
            candidates.append(candidate)
        report = case_report(case.case_id, runner.dedupe_candidate_dicts(candidates), skipped_resume=skipped_resume)
        report["pages_analyzed"] = 3
        report["vision_fallback"]["pages_attempted"] = attempted
        report["huggingface_fallback"]["pages_attempted"] = attempted
        report["vision_fallback"]["pages_succeeded"] = attempted
        report["huggingface_fallback"]["pages_succeeded"] = attempted
        report["vision_fallback"]["pages_skipped_max_limit"] = skipped_max
        report["huggingface_fallback"]["pages_skipped_max_limit"] = skipped_max
        return report


def write_resume_checkpoint(path: Path, *, vision_max_pages: int = 1) -> None:
    payload = {
        "run_id": "old-run",
        "started_at": "2026-05-12T00:00:00+00:00",
        "updated_at": "2026-05-12T00:00:00+00:00",
        "cases_dir": "benchmark_cases",
        "selected_cases": fake_manifest()["cases"],
        "completed_cases": ["case-001"],
        "completed_vision_pages": {"case-001": [1]},
        "completed_page_identifiers": [{"case_id": "case-001", "page_number": 1, "stage": "huggingface_vision_fallback"}],
        "partial_candidates_by_case": {"case-001": [hf_candidate("case-001", 1)]},
        "partial_case_reports": {"case-001": case_report("case-001", [hf_candidate("case-001", 1)])},
        "partial_vision_metrics": {"attempted": 1, "succeeded": 1, "failed": 0, "skipped": 0},
        "partial_vision_diagnostics": [],
        "failures": [],
        "warnings": [],
        "flags": {
            "cases_dir": "benchmark_cases",
            "case": None,
            "all": True,
            "limit_pages": None,
            "use_vision_fallback": True,
            "vision_provider": "huggingface",
            "vision_max_pages": vision_max_pages,
            "vision_page_mode": "failed-native-only",
            "use_openai": False,
            "no_openai": False,
            "openai_max_pages": None,
            "openai_page_mode": "failed-native-only",
        },
        "interrupted": False,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class ExtractionV2BenchmarkProgressTests(unittest.TestCase):
    def setUp(self):
        FakePipeline.instances = []
        ResumeLimitPipeline.attempted_pages = []
        ResumeLimitPipeline.skipped_pages = []
        ResumeLimitPipeline.run_cases = []

    def run_cli(self, tmpdir: str, extra_args: list[str] | None = None, pipeline_class=FakePipeline, manifest: dict | None = None):
        output_json = Path(tmpdir) / "report.json"
        checkpoint_dir = Path(tmpdir) / "checkpoints"
        argv = [
            "--cases-dir",
            "benchmark_cases",
            "--all",
            "--use-vision-fallback",
            "--vision-provider",
            "huggingface",
            "--checkpoint-dir",
            str(checkpoint_dir),
            "--output-json",
            str(output_json),
            "--run-id",
            "test-run",
        ]
        argv.extend(extra_args or [])
        stdout = io.StringIO()
        with patch.object(runner, "load_or_discover_manifest", return_value=manifest or fake_manifest()):
            with patch.object(runner, "ExtractionV2Pipeline", pipeline_class):
                with contextlib.redirect_stdout(stdout):
                    code = asyncio.run(runner.async_main(argv))
        return code, stdout.getvalue(), output_json, checkpoint_dir / "extraction_v2_checkpoint_test-run.json"

    def test_progress_logging_prints_case_page_updates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            code, stdout, _output_json, _checkpoint = self.run_cli(tmpdir)

        self.assertEqual(code, 0)
        self.assertIn("[13Q-pre] Case case-001", stdout)
        self.assertIn("page 1/1", stdout)
        self.assertIn("Hugging Face vision succeeded", stdout)

    def test_quiet_mode_suppresses_normal_progress(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            code, stdout, _output_json, _checkpoint = self.run_cli(tmpdir, ["--quiet"])

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")

    def test_checkpoint_file_is_written_and_json_valid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            code, _stdout, _output_json, checkpoint = self.run_cli(tmpdir)

            self.assertEqual(code, 0)
            payload = json.loads(checkpoint.read_text(encoding="utf-8"))

        self.assertEqual(payload["run_id"], "test-run")
        self.assertIn("case-001", payload["completed_cases"])

    def test_checkpoint_contains_candidates_and_vision_metrics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            code, _stdout, _output_json, checkpoint = self.run_cli(tmpdir)
            payload = json.loads(checkpoint.read_text(encoding="utf-8"))

        self.assertEqual(code, 0)
        self.assertEqual(payload["partial_vision_metrics"]["attempted"], 1)
        self.assertEqual(payload["partial_vision_metrics"]["succeeded"], 1)
        self.assertEqual(payload["partial_vision_metrics"]["hf_raw_response_preview_count"], 1)
        self.assertEqual(payload["partial_vision_metrics"]["hf_parser_recovered_candidates"], 1)
        self.assertEqual(len(payload["partial_vision_diagnostics"]), 1)
        self.assertEqual(len(payload["partial_candidates_by_case"]["case-001"]), 1)

    def test_keyboard_interrupt_writes_interrupted_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            code, stdout, _output_json, checkpoint = self.run_cli(tmpdir, pipeline_class=InterruptingPipeline)
            payload = json.loads(checkpoint.read_text(encoding="utf-8"))

        self.assertEqual(code, 130)
        self.assertTrue(payload["interrupted"])
        self.assertIn("Interrupted by Ctrl+C", stdout)

    def test_resume_skips_completed_pages_and_does_not_duplicate_candidates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _code, _stdout, _output_json, checkpoint = self.run_cli(tmpdir, pipeline_class=InterruptingPipeline)
            resumed_output = Path(tmpdir) / "resumed.json"
            argv = [
                "--resume-from-checkpoint",
                str(checkpoint),
                "--checkpoint-dir",
                str(Path(tmpdir) / "checkpoints"),
                "--output-json",
                str(resumed_output),
                "--quiet",
            ]
            with patch.object(runner, "load_or_discover_manifest", return_value=fake_manifest()):
                with patch.object(runner, "ExtractionV2Pipeline", FakePipeline):
                    code = asyncio.run(runner.async_main(argv))
            report = json.loads(resumed_output.read_text(encoding="utf-8"))

        self.assertEqual(code, 0)
        self.assertEqual(FakePipeline.instances[-1].kwargs["completed_vision_pages"]["case-001"], {1})
        self.assertEqual(report["case_reports"][0]["candidate_count"], 1)
        self.assertTrue(report["run_metadata"]["resumed_from_checkpoint"])
        self.assertEqual(report["aggregate_metrics"]["huggingface_fallback_pages_skipped_resume"], 1)

    def test_resume_vision_max_pages_cli_override_extends_checkpoint_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint = Path(tmpdir) / "checkpoint.json"
            write_resume_checkpoint(checkpoint, vision_max_pages=1)
            output_json = Path(tmpdir) / "resumed.json"
            argv = [
                "--resume-from-checkpoint",
                str(checkpoint),
                "--vision-max-pages",
                "3",
                "--checkpoint-dir",
                str(Path(tmpdir) / "checkpoints"),
                "--output-json",
                str(output_json),
                "--progress",
                "--run-id",
                "new-run",
            ]
            stdout = io.StringIO()
            with patch.object(runner, "load_or_discover_manifest", return_value=fake_manifest()):
                with patch.object(runner, "ExtractionV2Pipeline", ResumeLimitPipeline):
                    with contextlib.redirect_stdout(stdout):
                        code = asyncio.run(runner.async_main(argv))
            report = json.loads(output_json.read_text(encoding="utf-8"))

        self.assertEqual(code, 0)
        self.assertIn("checkpoint vision_max_pages=1, effective vision_max_pages=3", stdout.getvalue())
        self.assertEqual(ResumeLimitPipeline.instances[-1].kwargs["vision_max_pages"], 3)
        self.assertEqual(ResumeLimitPipeline.instances[-1].kwargs["previous_vision_pages_attempted"], 1)
        self.assertEqual(report["run_metadata"]["checkpoint_vision_max_pages"], 1)
        self.assertEqual(report["run_metadata"]["effective_vision_max_pages"], 3)

    def test_resume_higher_max_attempts_unattempted_pages_without_reattempting_completed_page(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint = Path(tmpdir) / "checkpoint.json"
            write_resume_checkpoint(checkpoint, vision_max_pages=1)
            output_json = Path(tmpdir) / "resumed.json"
            argv = [
                "--resume-from-checkpoint",
                str(checkpoint),
                "--vision-max-pages",
                "3",
                "--checkpoint-dir",
                str(Path(tmpdir) / "checkpoints"),
                "--output-json",
                str(output_json),
                "--quiet",
            ]
            with patch.object(runner, "load_or_discover_manifest", return_value=fake_manifest()):
                with patch.object(runner, "ExtractionV2Pipeline", ResumeLimitPipeline):
                    code = asyncio.run(runner.async_main(argv))
            report = json.loads(output_json.read_text(encoding="utf-8"))

        self.assertEqual(code, 0)
        self.assertEqual(ResumeLimitPipeline.run_cases, ["case-001"])
        self.assertEqual(ResumeLimitPipeline.attempted_pages, [2, 3])
        self.assertNotIn(1, ResumeLimitPipeline.attempted_pages)
        self.assertEqual(report["case_reports"][0]["candidate_count"], 3)
        self.assertEqual(report["run_metadata"]["previous_vision_pages_attempted"], 1)
        self.assertEqual(report["run_metadata"]["additional_vision_pages_attempted"], 2)
        self.assertEqual(report["run_metadata"]["total_vision_pages_attempted"], 3)

    def test_resume_lower_or_equal_max_prints_no_additional_pages_message(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint = Path(tmpdir) / "checkpoint.json"
            write_resume_checkpoint(checkpoint, vision_max_pages=1)
            output_json = Path(tmpdir) / "resumed.json"
            argv = [
                "--resume-from-checkpoint",
                str(checkpoint),
                "--vision-max-pages",
                "1",
                "--checkpoint-dir",
                str(Path(tmpdir) / "checkpoints"),
                "--output-json",
                str(output_json),
                "--progress",
            ]
            stdout = io.StringIO()
            with patch.object(runner, "load_or_discover_manifest", return_value=fake_manifest()):
                with patch.object(runner, "ExtractionV2Pipeline", ResumeLimitPipeline):
                    with contextlib.redirect_stdout(stdout):
                        code = asyncio.run(runner.async_main(argv))

        self.assertEqual(code, 0)
        self.assertIn("no additional fallback pages will be attempted", stdout.getvalue())
        self.assertEqual(ResumeLimitPipeline.run_cases, [])

    def test_old_checkpoint_without_page_level_status_loads_safely_and_writes_valid_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint = Path(tmpdir) / "checkpoint.json"
            write_resume_checkpoint(checkpoint, vision_max_pages=1)
            output_json = Path(tmpdir) / "resumed.json"
            checkpoint_dir = Path(tmpdir) / "checkpoints"
            argv = [
                "--resume-from-checkpoint",
                str(checkpoint),
                "--vision-max-pages",
                "2",
                "--checkpoint-dir",
                str(checkpoint_dir),
                "--output-json",
                str(output_json),
                "--run-id",
                "resumed",
                "--quiet",
            ]
            with patch.object(runner, "load_or_discover_manifest", return_value=fake_manifest()):
                with patch.object(runner, "ExtractionV2Pipeline", ResumeLimitPipeline):
                    code = asyncio.run(runner.async_main(argv))
            resumed_checkpoint = json.loads((checkpoint_dir / "extraction_v2_checkpoint_resumed.json").read_text(encoding="utf-8"))

        self.assertEqual(code, 0)
        self.assertIn("vision_page_status", resumed_checkpoint)
        self.assertIn("case-001", resumed_checkpoint["vision_page_status"])
        self.assertEqual(resumed_checkpoint["flags"]["vision_max_pages"], 2)

    def test_final_report_marks_no_db_mutation_and_no_reference_xml_to_model(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            code, _stdout, output_json, _checkpoint = self.run_cli(tmpdir)
            report = json.loads(output_json.read_text(encoding="utf-8"))

        self.assertEqual(code, 0)
        self.assertFalse(report["run_metadata"]["database_mutated"])
        self.assertFalse(report["run_metadata"]["reference_xml_sent_to_model"])
        self.assertFalse(report["run_metadata"]["reference_xml_sent_to_openai"])

    def test_no_vision_path_still_works(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_json = Path(tmpdir) / "report.json"
            argv = [
                "--cases-dir",
                "benchmark_cases",
                "--all",
                "--no-openai",
                "--checkpoint-dir",
                str(Path(tmpdir) / "checkpoints"),
                "--output-json",
                str(output_json),
                "--quiet",
            ]
            with patch.object(runner, "load_or_discover_manifest", return_value=fake_manifest()):
                with patch.object(runner, "ExtractionV2Pipeline", FakePipeline):
                    code = asyncio.run(runner.async_main(argv))
            report = json.loads(output_json.read_text(encoding="utf-8"))

        self.assertEqual(code, 0)
        self.assertFalse(FakePipeline.instances[-1].kwargs["use_vision_fallback"])
        self.assertFalse(report["run_metadata"]["vision_fallback_used"])

    def test_runner_reuses_pipeline_so_vision_max_pages_is_run_scoped(self):
        manifest = fake_manifest()
        second_case = dict(manifest["cases"][0])
        second_case["case_id"] = "case-002"
        second_case["case_dir"] = "benchmark_cases/case-002"
        second_case["pdf_path"] = "case-002.pdf"
        manifest["cases"] = [manifest["cases"][0], second_case]
        with tempfile.TemporaryDirectory() as tmpdir:
            code, _stdout, _output_json, _checkpoint = self.run_cli(tmpdir, ["--vision-max-pages", "1"], manifest=manifest)

        self.assertEqual(code, 0)
        self.assertEqual(len(FakePipeline.instances), 1)
        self.assertEqual(FakePipeline.instances[0].kwargs["vision_max_pages"], 1)


if __name__ == "__main__":
    unittest.main()
