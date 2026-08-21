import asyncio
import inspect
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import tasks
from schemas import JobStatus, ProcessingStatus
from services.redis_status_tracker import redis_status_tracker


class FakeResult:
    def __init__(self, job):
        self.job = job

    def scalar_one_or_none(self):
        return self.job


class FakeFailureSession:
    def __init__(self, job):
        self.job = job
        self.rollback = AsyncMock()
        self.commit = AsyncMock()

    async def execute(self, _statement):
        return FakeResult(self.job)


class FakeFailureSessionManager:
    def __init__(self, job):
        self.session = FakeFailureSession(job)

    @asynccontextmanager
    async def get_session(self):
        yield self.session


class FakeProcessingSessionManager:
    def __init__(self):
        self.session = SimpleNamespace()
        self.creation_loop_id = None

    @asynccontextmanager
    async def get_session(self):
        self.creation_loop_id = id(asyncio.get_running_loop())
        yield self.session


class CeleryTaskIdentityHandoffTests(unittest.TestCase):
    def setUp(self):
        tasks.shutdown_celery_event_loop(close_resources=True)
        self.backend_store_patch = patch.object(tasks.celery_app.backend, "store_result")
        self.backend_store = self.backend_store_patch.start()

    def tearDown(self):
        self.backend_store_patch.stop()
        tasks.shutdown_celery_event_loop(close_resources=True)

    def run_bound_pdf_task(self, task_id, job_id):
        tasks.process_pdf_task.push_request(id=task_id)
        try:
            return tasks.process_pdf_task.run(job_id)
        finally:
            tasks.process_pdf_task.pop_request()

    def test_synchronous_task_captures_request_id_before_persistent_loop_handoff(self):
        received = []

        async def fake_process_pdf_job_async(*, job_id, celery_task_id, state_reporter):
            received.append(
                {
                    "job_id": job_id,
                    "celery_task_id": celery_task_id,
                    "loop_id": id(asyncio.get_running_loop()),
                    "reporter_task_id": state_reporter.task_id,
                }
            )
            return {"status": "completed", "job_id": job_id, "success": True}

        with patch("tasks.process_pdf_job_async", new=fake_process_pdf_job_async):
            result = self.run_bound_pdf_task("task-live-54", 54)

        self.assertTrue(result["success"])
        self.assertEqual(received[0]["job_id"], 54)
        self.assertEqual(received[0]["celery_task_id"], "task-live-54")
        self.assertEqual(received[0]["reporter_task_id"], "task-live-54")
        self.assertEqual(received[0]["loop_id"], id(tasks._loop))

    def test_async_pdf_functions_accept_explicit_id_and_do_not_accept_bound_task(self):
        process_parameters = inspect.signature(tasks.process_pdf_job_async).parameters
        azure_parameters = inspect.signature(tasks._run_azure_di_pdf_processing).parameters
        process_source = inspect.getsource(tasks.process_pdf_job_async)
        azure_source = inspect.getsource(tasks._run_azure_di_pdf_processing)

        self.assertIn("celery_task_id", process_parameters)
        self.assertIn("celery_task_id", azure_parameters)
        self.assertNotIn("task", process_parameters)
        self.assertNotIn("task", azure_parameters)
        self.assertNotIn(".request", process_source)
        self.assertNotIn(".update_state", azure_source)

    def test_explicit_task_state_update_uses_task_id(self):
        backend = SimpleNamespace(store_result=Mock())
        reporter = tasks.CeleryTaskStateReporter(
            "task-live-54",
            54,
            backend=backend,
        )

        updated = reporter.progress(
            {"job_id": 54, "progress": 10},
        )

        self.assertTrue(updated)
        backend.store_result.assert_called_once_with(
            "task-live-54",
            {"job_id": 54, "progress": 10, "task_id": "task-live-54"},
            "PROGRESS",
        )

    def test_progress_backend_failure_does_not_abort_azure_processing(self):
        backend = SimpleNamespace(store_result=Mock(side_effect=ValueError("backend unavailable")))
        reporter = tasks.CeleryTaskStateReporter(
            "task-live-54",
            54,
            backend=backend,
        )
        self.assertFalse(
            reporter.progress({"job_id": 54})
        )

        azure_called = []

        async def fake_process(job_id, db, *, progress_callback=None):
            azure_called.append(job_id)
            progress_callback(
                job_id=job_id,
                progress=35,
                status=JobStatus.PROCESSING,
                message="Azure DI result received",
            )
            return ProcessingStatus(
                job_id=job_id,
                status=JobStatus.REVIEW,
                progress=100,
                message="Azure DI complete",
            )

        async def run_stage():
            with patch(
                "services.azure_di_production_extraction.process_azure_di_filing_job",
                new=fake_process,
            ):
                result = await tasks._run_azure_di_pdf_processing(
                    "task-live-54",
                    54,
                    SimpleNamespace(),
                    state_reporter=reporter,
                )
            return result

        result = asyncio.run(run_stage())
        self.assertEqual(result.status, JobStatus.REVIEW)
        self.assertEqual(azure_called, [54])
        self.assertGreaterEqual(backend.store_result.call_count, 3)

    def test_missing_task_id_fails_before_async_processing_and_records_cleanup(self):
        with (
            patch("tasks.process_pdf_job_async", new=AsyncMock()) as process_async,
            patch("tasks.record_fatal_pdf_task_failure", return_value=True) as cleanup,
        ):
            with self.assertRaisesRegex(
                tasks.PdfProcessingTaskError,
                tasks.PDF_TASK_ID_MISSING_ERROR_CODE,
            ):
                self.run_bound_pdf_task(None, 54)

        process_async.assert_not_awaited()
        cleanup.assert_called_once()
        self.assertEqual(cleanup.call_args.args[0], 54)

    def test_fatal_cleanup_moves_processing_job_to_error_and_updates_redis(self):
        job = SimpleNamespace(
            id=54,
            status=JobStatus.PROCESSING.value,
            progress=20,
            error_message=None,
        )
        manager = FakeFailureSessionManager(job)

        async def run_cleanup():
            with (
                patch.object(redis_status_tracker, "initialize", new=AsyncMock()),
                patch.object(redis_status_tracker, "update_progress", new=AsyncMock()) as redis_update,
            ):
                marked = await tasks.mark_pdf_job_failed(
                    54,
                    error_code=tasks.PDF_TASK_EXECUTION_ERROR_CODE,
                    safe_message="Celery PDF processing failed before completion.",
                    session_manager=manager,
                )
            return marked, redis_update

        marked, redis_update = asyncio.run(run_cleanup())

        self.assertTrue(marked)
        self.assertEqual(job.status, JobStatus.ERROR.value)
        self.assertEqual(job.progress, 0)
        self.assertTrue(job.error_message.startswith("[celery_pdf_task_execution_failed]"))
        manager.session.commit.assert_awaited_once()
        redis_update.assert_awaited_once()
        self.assertEqual(redis_update.await_args.args[0].status, JobStatus.ERROR)

    def test_fatal_cleanup_preserves_review_after_optional_mapping_failure(self):
        job = SimpleNamespace(
            id=55,
            status=JobStatus.REVIEW.value,
            progress=100,
            error_message=None,
        )
        manager = FakeFailureSessionManager(job)

        async def run_cleanup():
            with (
                patch.object(redis_status_tracker, "initialize", new=AsyncMock()),
                patch.object(redis_status_tracker, "update_progress", new=AsyncMock()) as redis_update,
            ):
                marked = await tasks.mark_pdf_job_failed(
                    55,
                    error_code=tasks.PDF_TASK_EXECUTION_ERROR_CODE,
                    safe_message="optional mapping failure",
                    session_manager=manager,
                )
            return marked, redis_update

        marked, redis_update = asyncio.run(run_cleanup())

        self.assertFalse(marked)
        self.assertEqual(job.status, JobStatus.REVIEW.value)
        self.assertEqual(job.progress, 100)
        self.assertIsNone(job.error_message)
        manager.session.commit.assert_not_awaited()
        redis_update.assert_not_awaited()

    def test_fatal_task_raises_so_celery_records_failure_instead_of_success_payload(self):
        async def fail_processing(*, job_id, celery_task_id, state_reporter):
            raise RuntimeError("pre-Azure initialization failed")

        with (
            patch("tasks.process_pdf_job_async", new=fail_processing),
            patch("tasks.record_fatal_pdf_task_failure", return_value=True) as cleanup,
        ):
            with self.assertRaisesRegex(
                tasks.PdfProcessingTaskError,
                tasks.PDF_TASK_EXECUTION_ERROR_CODE,
            ):
                self.run_bound_pdf_task("task-live-54", 54)

        cleanup.assert_called_once()

    def test_explicit_id_allows_azure_stage_to_begin_past_previous_failure_point(self):
        manager = FakeProcessingSessionManager()
        azure_invocations = []

        async def fake_azure(celery_task_id, job_id, db, *, state_reporter=None):
            azure_invocations.append((celery_task_id, job_id, db))
            return ProcessingStatus(
                job_id=job_id,
                status=JobStatus.REVIEW,
                progress=100,
                message="Azure DI complete with rows",
            )

        async def run_process():
            with (
                patch.object(tasks.settings, "extraction_pipeline", "azure_di"),
                patch.object(tasks.settings, "extraction_allow_legacy_fallback", False),
                patch.object(redis_status_tracker, "initialize", new=AsyncMock()),
                patch("tasks._run_azure_di_pdf_processing", new=fake_azure),
            ):
                return await tasks.process_pdf_job_async(
                    job_id=54,
                    celery_task_id="task-live-54",
                    session_manager=manager,
                )

        result = asyncio.run(run_process())

        self.assertTrue(result["success"])
        self.assertEqual(azure_invocations[0][0], "task-live-54")
        self.assertEqual(azure_invocations[0][1], 54)
        self.assertIs(azure_invocations[0][2], manager.session)


if __name__ == "__main__":
    unittest.main()
