import asyncio
import inspect
import threading
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

from celery import Celery, states

import tasks


class RecordingResultBackend:
    def __init__(self):
        self._lock = threading.Lock()
        self.records = []
        self.metadata = {}

    def store_result(self, task_id, result, state, traceback=None):
        date_done = (
            datetime.now(timezone.utc).isoformat()
            if state in {states.SUCCESS, states.FAILURE}
            else None
        )
        record = {
            "task_id": task_id,
            "result": result,
            "status": state,
            "traceback": traceback,
            "date_done": date_done,
        }
        with self._lock:
            self.records.append(record)
            self.metadata[task_id] = record
        return result

    def meta(self, task_id):
        with self._lock:
            return dict(self.metadata[task_id])


class CeleryTerminalStateFinalizationTests(unittest.TestCase):
    def setUp(self):
        tasks.shutdown_celery_event_loop(close_resources=True)

    def tearDown(self):
        tasks.shutdown_celery_event_loop(close_resources=True)

    def run_bound_task(self, task_id, job_id):
        tasks.process_pdf_task.push_request(id=task_id)
        try:
            return tasks.process_pdf_task.run(job_id)
        finally:
            tasks.process_pdf_task.pop_request()

    @contextmanager
    def task_environment(self, backend, async_implementation):
        reporter_class = tasks.CeleryTaskStateReporter
        created_reporters = []

        def create_reporter(task_id, job_id, **_kwargs):
            reporter = reporter_class(task_id, job_id, backend=backend)
            created_reporters.append(reporter)
            return reporter

        with (
            patch("tasks.CeleryTaskStateReporter", side_effect=create_reporter),
            patch("tasks.process_pdf_job_async", new=async_implementation),
            patch("tasks.record_fatal_pdf_task_failure", return_value=True),
        ):
            yield created_reporters

    def test_successful_task_transitions_progress_to_success_with_terminal_metadata(self):
        backend = RecordingResultBackend()

        async def complete(*, job_id, celery_task_id, state_reporter):
            state_reporter.progress({"job_id": job_id, "progress": 35})
            state_reporter.progress({"job_id": job_id, "progress": 100})
            return {
                "job_id": job_id,
                "filing_status": "REVIEW",
                "extracted_row_count": 83,
                "ai_mapping_status": "completed",
                "ai_suggestion_count": 50,
                "warnings": [],
            }

        with self.task_environment(backend, complete) as reporters:
            result = self.run_bound_task("task-job-55", 55)

        meta = backend.meta("task-job-55")
        self.assertEqual(
            [record["status"] for record in backend.records],
            [states.STARTED, "PROGRESS", "PROGRESS", states.SUCCESS],
        )
        self.assertEqual(meta["status"], states.SUCCESS)
        self.assertIsNotNone(meta["date_done"])
        self.assertTrue(meta["result"]["success"])
        self.assertEqual(meta["result"]["filing_status"], "REVIEW")
        self.assertEqual(meta["result"]["extracted_row_count"], 83)
        self.assertEqual(result, meta["result"])
        self.assertEqual(reporters[0].terminal_state, states.SUCCESS)
        self.assertIsNotNone(reporters[0].completed_at)
        self.assertTrue(tasks.process_pdf_task.ignore_result)

    def test_late_progress_after_success_is_ignored(self):
        backend = RecordingResultBackend()
        reporter = tasks.CeleryTaskStateReporter("task-job-55", 55, backend=backend)

        self.assertTrue(reporter.progress({"progress": 100}))
        reporter.success({"filing_status": "REVIEW"})
        self.assertFalse(reporter.progress({"progress": 100, "status": "late"}))

        self.assertEqual(backend.meta("task-job-55")["status"], states.SUCCESS)
        self.assertEqual(
            [record["status"] for record in backend.records],
            ["PROGRESS", states.SUCCESS],
        )
        self.assertFalse(reporter.transition_history[-1]["accepted"])

    def test_fatal_task_transitions_progress_to_failure_with_terminal_metadata(self):
        backend = RecordingResultBackend()

        async def fail(*, job_id, celery_task_id, state_reporter):
            state_reporter.progress({"job_id": job_id, "progress": 35})
            raise RuntimeError("mock fatal core-processing failure")

        with self.task_environment(backend, fail) as reporters:
            with self.assertRaises(tasks.PdfProcessingTaskError):
                self.run_bound_task("task-fatal-56", 56)

        meta = backend.meta("task-fatal-56")
        self.assertEqual(meta["status"], states.FAILURE)
        self.assertIsNotNone(meta["date_done"])
        self.assertIsInstance(meta["result"], tasks.PdfProcessingTaskError)
        self.assertEqual(reporters[0].terminal_state, states.FAILURE)
        self.assertEqual(
            [record["status"] for record in backend.records],
            [states.STARTED, "PROGRESS", states.FAILURE],
        )

    def test_late_progress_after_failure_is_ignored(self):
        backend = RecordingResultBackend()
        reporter = tasks.CeleryTaskStateReporter("task-fatal-56", 56, backend=backend)

        reporter.progress({"progress": 70})
        reporter.close_progress_for_failure()
        self.assertFalse(reporter.progress({"progress": 100}))
        reporter.failure(tasks.PdfProcessingTaskError("test_failure", "failed safely"))
        self.assertFalse(reporter.progress({"progress": 100}))

        self.assertEqual(backend.meta("task-fatal-56")["status"], states.FAILURE)
        self.assertEqual(
            [record["status"] for record in backend.records],
            ["PROGRESS", states.FAILURE],
        )

    def test_explicit_task_uuid_is_used_for_every_backend_write(self):
        backend = RecordingResultBackend()
        reporter = tasks.CeleryTaskStateReporter("explicit-uuid-57", 57, backend=backend)
        reporter.started()
        reporter.progress({"progress": 50})
        reporter.success({"filing_status": "REVIEW"})

        self.assertEqual(
            {record["task_id"] for record in backend.records},
            {"explicit-uuid-57"},
        )

    def test_async_worker_loop_code_does_not_access_task_request(self):
        process_source = inspect.getsource(tasks.process_pdf_job_async)
        azure_source = inspect.getsource(tasks._run_azure_di_pdf_processing)
        self.assertNotIn(".request", process_source)
        self.assertNotIn(".request", azure_source)
        self.assertNotIn(".update_state", process_source)
        self.assertNotIn(".update_state", azure_source)

    def test_optional_mapping_failure_preserves_review_rows_and_finishes_success(self):
        backend = RecordingResultBackend()

        async def optional_failure(*, job_id, celery_task_id, state_reporter):
            state_reporter.progress({"job_id": job_id, "progress": 100})
            return {
                "job_id": job_id,
                "filing_status": "REVIEW",
                "extracted_row_count": 107,
                "ai_mapping_status": "failed",
                "ai_suggestion_count": 6,
                "warnings": [
                    {
                        "code": "async_resource_loop_mismatch",
                        "message": "AI mapping suggestions failed after extraction completed.",
                    }
                ],
                "optional_stage": "mapping",
                "optional_stage_status": "failed",
                "optional_stage_error_code": "async_resource_loop_mismatch",
                "optional_stage_error_message": (
                    "AI mapping suggestions failed after extraction completed."
                ),
            }

        with self.task_environment(backend, optional_failure):
            result = self.run_bound_task("task-optional-51", 51)

        meta = backend.meta("task-optional-51")
        self.assertEqual(meta["status"], states.SUCCESS)
        self.assertEqual(result["filing_status"], "REVIEW")
        self.assertEqual(result["extracted_row_count"], 107)
        self.assertEqual(result["ai_mapping_status"], "failed")
        self.assertEqual(result["optional_stage"], "mapping")
        self.assertEqual(result["optional_stage_status"], "failed")
        self.assertEqual(
            result["optional_stage_error_code"],
            "async_resource_loop_mismatch",
        )

    def test_three_jobs_share_persistent_loop_and_all_finish_success(self):
        backend = RecordingResultBackend()
        loop_ids = []

        async def complete(*, job_id, celery_task_id, state_reporter):
            loop_ids.append(id(asyncio.get_running_loop()))
            state_reporter.progress({"job_id": job_id, "progress": 70})
            optional_failed = job_id == 2
            return {
                "job_id": job_id,
                "filing_status": "REVIEW",
                "extracted_row_count": 10 + job_id,
                "ai_mapping_status": "failed" if optional_failed else "completed",
                "ai_suggestion_count": 0 if optional_failed else 5,
                "warnings": [],
                "optional_stage": "mapping" if optional_failed else None,
                "optional_stage_status": "failed" if optional_failed else None,
                "optional_stage_error_code": "mapping_suggestion_failed" if optional_failed else None,
                "optional_stage_error_message": (
                    "AI mapping suggestions failed after extraction completed."
                    if optional_failed
                    else None
                ),
            }

        for job_id in (1, 2, 3):
            with self.task_environment(backend, complete):
                result = self.run_bound_task(f"task-sequential-{job_id}", job_id)
            self.assertEqual(result["final_celery_state"], states.SUCCESS)

        self.assertEqual(len(set(loop_ids)), 1)
        for job_id in (1, 2, 3):
            meta = backend.meta(f"task-sequential-{job_id}")
            self.assertEqual(meta["status"], states.SUCCESS)
            self.assertIsNotNone(meta["date_done"])
        self.assertNotIn("different loop", repr(backend.records).casefold())

    def test_job_55_pattern_rejects_delayed_progress_after_wrapper_return(self):
        backend = RecordingResultBackend()
        release_late_progress = threading.Event()
        late_attempts = []
        late_threads = []

        async def complete(*, job_id, celery_task_id, state_reporter):
            for progress in (10, 35, 50, 70, 90, 100):
                state_reporter.progress({"job_id": job_id, "progress": progress})

            def publish_late_progress():
                release_late_progress.wait(timeout=5)
                late_attempts.append(
                    state_reporter.progress(
                        {"job_id": job_id, "progress": 100, "status": "delayed"}
                    )
                )

            thread = threading.Thread(target=publish_late_progress)
            thread.start()
            late_threads.append(thread)
            return {
                "job_id": job_id,
                "filing_status": "REVIEW",
                "extracted_row_count": 83,
                "ai_mapping_status": "completed",
                "ai_suggestion_count": 50,
                "warnings": [],
            }

        with self.task_environment(backend, complete):
            result = self.run_bound_task("task-job-55-delayed", 55)

        release_late_progress.set()
        for thread in late_threads:
            thread.join(timeout=5)

        self.assertTrue(result["success"])
        self.assertEqual(late_attempts, [False])
        meta = backend.meta("task-job-55-delayed")
        self.assertEqual(meta["status"], states.SUCCESS)
        self.assertIsNotNone(meta["date_done"])
        self.assertEqual(meta["result"]["extracted_row_count"], 83)
        self.assertEqual(backend.records[-1]["status"], states.SUCCESS)

    def test_terminal_state_cannot_be_reversed_or_written_twice(self):
        backend = RecordingResultBackend()
        reporter = tasks.CeleryTaskStateReporter("task-once", 60, backend=backend)
        reporter.success({"filing_status": "REVIEW"})

        self.assertFalse(
            reporter.failure(tasks.PdfProcessingTaskError("late_failure", "too late"))
        )
        with self.assertRaisesRegex(RuntimeError, "exactly once"):
            reporter.success({"filing_status": "REVIEW"})

        self.assertEqual(len(backend.records), 1)
        self.assertEqual(backend.records[0]["status"], states.SUCCESS)

    def test_celery_backend_creates_date_done_and_decodes_terminal_payloads(self):
        app = Celery("terminal-state-test", backend="cache+memory://")
        app.conf.update(
            result_serializer="json",
            accept_content=["json"],
        )

        success = tasks.CeleryTaskStateReporter(
            "real-backend-success",
            61,
            backend=app.backend,
        )
        success.progress({"progress": 100})
        success.success({"filing_status": "REVIEW", "extracted_row_count": 5})
        success_meta = app.backend.get_task_meta("real-backend-success")

        failure = tasks.CeleryTaskStateReporter(
            "real-backend-failure",
            62,
            backend=app.backend,
        )
        failure.close_progress_for_failure()
        failure.failure(tasks.PdfProcessingTaskError("test_failure", "failed safely"))
        failure_meta = app.backend.get_task_meta("real-backend-failure")

        self.assertEqual(success_meta["status"], states.SUCCESS)
        self.assertIsNotNone(success_meta["date_done"])
        self.assertEqual(success_meta["result"]["filing_status"], "REVIEW")
        self.assertEqual(failure_meta["status"], states.FAILURE)
        self.assertIsNotNone(failure_meta["date_done"])
        self.assertIsInstance(failure_meta["result"], Exception)
        self.assertIn("test_failure", str(failure_meta["result"]))


if __name__ == "__main__":
    unittest.main()
