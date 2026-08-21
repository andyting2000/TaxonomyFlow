import asyncio
import json
import threading
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import tasks
from celery_db_manager import CeleryDatabaseManager
from schemas import JobStatus, ProcessingStatus, ProgressUpdate
from services.azure_di_production_extraction import _mapping_suggestion_error_metadata
from services.redis_status_tracker import redis_status_tracker


class FakeRedisClient:
    def __init__(self):
        self.loop_ids = []
        self.values = {}
        self.closed = False

    async def ping(self):
        self.loop_ids.append(id(asyncio.get_running_loop()))
        return True

    async def setex(self, key, ttl, value):
        self.loop_ids.append(id(asyncio.get_running_loop()))
        self.values[key] = json.loads(value)
        return True

    async def aclose(self):
        self.loop_ids.append(id(asyncio.get_running_loop()))
        self.closed = True


class RecordingSession:
    def __init__(self, loop_id):
        self.loop_id = loop_id
        self.queried_job_ids = []
        self.persisted_job_ids = []
        self.mapping_status = None

    async def query_filing_job(self, job_id):
        self.queried_job_ids.append(job_id)

    async def persist_extracted_rows(self, job_id):
        self.persisted_job_ids.append(job_id)


class RecordingSessionManager:
    def __init__(self):
        self.creation_loop_id = None
        self.sessions = []

    @asynccontextmanager
    async def get_session(self):
        loop_id = id(asyncio.get_running_loop())
        if self.creation_loop_id is None:
            self.creation_loop_id = loop_id
        if self.creation_loop_id != loop_id:
            raise RuntimeError("session manager crossed event loops")
        session = RecordingSession(loop_id)
        self.sessions.append(session)
        yield session


class FakeEngine:
    def __init__(self):
        self.dispose_loop_ids = []

    async def dispose(self):
        self.dispose_loop_ids.append(id(asyncio.get_running_loop()))


class FakeDatabaseSession:
    def __init__(self):
        self.closed_loop_ids = []

    def in_transaction(self):
        return False

    async def close(self):
        self.closed_loop_ids.append(id(asyncio.get_running_loop()))


class CeleryAsyncResourceLifecycleTests(unittest.TestCase):
    def setUp(self):
        tasks.shutdown_celery_event_loop(close_resources=True)
        redis_status_tracker.redis_client = None
        redis_status_tracker.initialized = False
        redis_status_tracker._creation_loop_id = None
        redis_status_tracker._creation_process_id = None

    def tearDown(self):
        tasks.shutdown_celery_event_loop(close_resources=True)
        redis_status_tracker.redis_client = None
        redis_status_tracker.initialized = False
        redis_status_tracker._creation_loop_id = None
        redis_status_tracker._creation_process_id = None

    def test_three_sequential_pdf_tasks_share_worker_loop_and_isolate_mapping_failure(self):
        fake_redis = FakeRedisClient()
        manager = RecordingSessionManager()
        stage_loop_ids = []
        stage_task_ids = []

        async def fake_azure_stage(celery_task_id, job_id, db, *, state_reporter=None):
            loop_id = id(asyncio.get_running_loop())
            stage_loop_ids.append(loop_id)
            stage_task_ids.append(celery_task_id)
            await db.query_filing_job(job_id)
            await redis_status_tracker.update_progress(
                ProgressUpdate(
                    job_id=job_id,
                    progress=70,
                    status=JobStatus.PROCESSING,
                    message="Persisting extracted data",
                )
            )
            await db.persist_extracted_rows(job_id)
            try:
                if job_id == 2:
                    raise RuntimeError("mock mapping suggestion failure")
                db.mapping_status = "completed"
            except RuntimeError:
                db.mapping_status = "failed"
            return ProcessingStatus(
                job_id=job_id,
                status=JobStatus.REVIEW,
                progress=100,
                message=f"job {job_id} reached review",
            )

        with (
            patch.object(tasks.settings, "extraction_pipeline", "azure_di"),
            patch.object(tasks.settings, "extraction_allow_legacy_fallback", False),
            patch("services.redis_status_tracker.aioredis.from_url", new=AsyncMock(return_value=fake_redis)) as from_url,
            patch("tasks._run_azure_di_pdf_processing", new=fake_azure_stage),
        ):
            results = [
                tasks.run_async_in_celery(
                    tasks.process_pdf_job_async(
                        job_id,
                        f"task-{job_id}",
                        session_manager=manager,
                    )
                )
                for job_id in (1, 2, 3)
            ]

        self.assertTrue(all(result["success"] for result in results))
        self.assertEqual([result["job_id"] for result in results], [1, 2, 3])
        self.assertEqual(stage_task_ids, ["task-1", "task-2", "task-3"])
        self.assertEqual(len(set(stage_loop_ids)), 1)
        self.assertEqual(manager.creation_loop_id, stage_loop_ids[0])
        self.assertEqual(redis_status_tracker.creation_loop_id, stage_loop_ids[0])
        self.assertEqual(from_url.await_count, 1)
        self.assertEqual([session.queried_job_ids for session in manager.sessions], [[1], [2], [3]])
        self.assertEqual([session.persisted_job_ids for session in manager.sessions], [[1], [2], [3]])
        self.assertEqual(
            [session.mapping_status for session in manager.sessions],
            ["completed", "failed", "completed"],
        )
        self.assertEqual(fake_redis.values["job_progress:3"]["status"], "PROCESSING")
        self.assertNotIn("different loop", repr(results).casefold())
        self.assertNotIn("unknown protocol state", repr(results).casefold())

    def test_celery_database_engine_is_created_reused_and_disposed_on_worker_loop(self):
        manager = CeleryDatabaseManager()
        engine = FakeEngine()
        sessions = []
        creation_loop_ids = []

        def fake_create_engine(*args, **kwargs):
            creation_loop_ids.append(id(asyncio.get_running_loop()))
            return engine

        def fake_sessionmaker(*args, **kwargs):
            def create_session():
                session = FakeDatabaseSession()
                sessions.append(session)
                return session

            return create_session

        async def use_session():
            async with manager.get_session():
                return id(asyncio.get_running_loop())

        with (
            patch("celery_db_manager.create_async_engine", side_effect=fake_create_engine) as create_engine,
            patch("celery_db_manager.async_sessionmaker", side_effect=fake_sessionmaker),
        ):
            use_loop_ids = [tasks.run_async_in_celery(use_session()) for _ in range(3)]
            with self.assertRaisesRegex(RuntimeError, "incompatible async resource context"):
                asyncio.run(manager.initialize())
            tasks.run_async_in_celery(manager.close())

        self.assertEqual(create_engine.call_count, 1)
        self.assertEqual(len(set(use_loop_ids)), 1)
        self.assertEqual(creation_loop_ids, [use_loop_ids[0]])
        self.assertEqual(len(sessions), 3)
        self.assertTrue(all(session.closed_loop_ids == [use_loop_ids[0]] for session in sessions))
        self.assertEqual(engine.dispose_loop_ids, [use_loop_ids[0]])
        self.assertIsNone(manager.creation_loop_id)

    def test_worker_shutdown_closes_redis_and_database_before_stopping_loop(self):
        tasks.get_or_create_event_loop()
        with (
            patch(
                "services.redis_status_tracker.redis_status_tracker.close",
                new=AsyncMock(),
            ) as redis_close,
            patch(
                "celery_db_manager.celery_db_manager.close",
                new=AsyncMock(),
            ) as database_close,
        ):
            tasks.shutdown_celery_event_loop(close_resources=True)

        redis_close.assert_awaited_once()
        database_close.assert_awaited_once()
        self.assertIsNone(tasks._loop)

    def test_mapping_failure_metadata_classifies_loop_mismatch_without_failing_extraction(self):
        different_loop = _mapping_suggestion_error_metadata(
            RuntimeError("Task got Future attached to a different loop")
        )
        protocol_state = _mapping_suggestion_error_metadata(
            RuntimeError("got result for unknown protocol state 3")
        )
        generic = _mapping_suggestion_error_metadata(RuntimeError("provider unavailable"))

        self.assertTrue(different_loop.startswith("[async_resource_loop_mismatch]"))
        self.assertTrue(protocol_state.startswith("[async_resource_loop_mismatch]"))
        self.assertTrue(generic.startswith("[mapping_suggestion_failed]"))

    def test_worker_loop_is_dedicated_and_stable_across_calling_threads(self):
        worker_loop_ids = []
        caller_thread_ids = []

        def submit():
            caller_thread_ids.append(threading.get_ident())

            async def identify_loop():
                return id(asyncio.get_running_loop())

            worker_loop_ids.append(tasks.run_async_in_celery(identify_loop()))

        threads = [threading.Thread(target=submit) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(len(worker_loop_ids), 3)
        self.assertEqual(len(set(worker_loop_ids)), 1)
        self.assertNotIn(tasks._loop_thread.ident, caller_thread_ids)


if __name__ == "__main__":
    unittest.main()
