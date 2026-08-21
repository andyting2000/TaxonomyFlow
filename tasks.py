import asyncio
import logging
import os
import threading
import time
import traceback
from datetime import datetime, timezone

from celery import Celery, states
from celery.signals import worker_ready, worker_shutdown
from celery.schedules import crontab

from config import settings
from schemas import JobStatus


logger = logging.getLogger(__name__)


celery_app = Celery(
    "xbrl_tasks",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    worker_pool="threads" if os.name == "nt" else "prefork",
    worker_concurrency=4,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=50,
    task_routes={
        "tasks.process_pdf_task": {"queue": "pdf_processing"},
        "tasks.generate_xbrl_task": {"queue": "xbrl_generation"},
    },
    result_expires=3600,
    task_reject_on_worker_lost=True,
    task_acks_late=True,
    broker_connection_retry_on_startup=True,
    worker_hijack_root_logger=False,
    worker_log_color=False,
)

try:
    os.makedirs(settings.temp_directory, exist_ok=True)
except OSError as exc:
    print(f"Warning: could not create TEMP_DIRECTORY {settings.temp_directory}: {exc}")

_loop = None
_loop_thread = None
_loop_ready = threading.Event()
_loop_lock = threading.Lock()
_loop_start_error = None
_ai_processor = None
_xbrl_generator = None

PDF_TASK_ID_MISSING_ERROR_CODE = "celery_task_identity_missing"
PDF_TASK_EXECUTION_ERROR_CODE = "celery_pdf_task_execution_failed"
PDF_PROCESSING_ERROR_CODE = "pdf_processing_failed"
MAX_TASK_ERROR_MESSAGE_LENGTH = 1000


class PdfProcessingTaskError(RuntimeError):
    def __init__(self, error_code, safe_message):
        self.error_code = str(error_code or PDF_TASK_EXECUTION_ERROR_CODE)
        self.safe_message = _safe_task_error_message(safe_message)
        super().__init__(f"[{self.error_code}] {self.safe_message}")


def _safe_task_error_message(message):
    normalized = " ".join(str(message or "Celery PDF processing failed.").split())
    return normalized[:MAX_TASK_ERROR_MESSAGE_LENGTH]


def _require_celery_task_id(task_id):
    normalized = str(task_id or "").strip()
    if not normalized:
        raise PdfProcessingTaskError(
            PDF_TASK_ID_MISSING_ERROR_CODE,
            "Celery task identity was unavailable before PDF processing started.",
        )
    return normalized


class CeleryTaskStateReporter:
    """Own all result-backend transitions for one explicit Celery task ID."""

    TERMINAL_STATES = frozenset({states.SUCCESS, states.FAILURE})

    def __init__(self, celery_task_id, job_id, *, backend=None):
        self.task_id = _require_celery_task_id(celery_task_id)
        self.job_id = int(job_id)
        self.backend = backend or celery_app.backend
        self.process_id = os.getpid()
        self.thread_id = threading.get_ident()
        self.started_at = datetime.now(timezone.utc).isoformat()
        self._lock = threading.RLock()
        self._sequence = 0
        self._terminal_intent = None
        self._terminal_state = None
        self._terminal_write_attempted = False
        self._completed_at = None
        self._transition_history = []

    @staticmethod
    def _event_loop_id():
        try:
            return id(asyncio.get_running_loop())
        except RuntimeError:
            return None

    def _record(self, requested_state, *, accepted, reason):
        self._sequence += 1
        event = {
            "sequence": self._sequence,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "job_id": self.job_id,
            "task_id": self.task_id,
            "worker_pid": self.process_id,
            "thread_id": threading.get_ident(),
            "event_loop_id": self._event_loop_id(),
            "requested_state": requested_state,
            "accepted": bool(accepted),
            "reason": reason,
        }
        self._transition_history.append(event)
        logger.info(
            "Celery PDF task state transition job_id=%s task_id=%s process_id=%s "
            "thread_id=%s loop_id=%s sequence=%s requested_state=%s accepted=%s reason=%s",
            self.job_id,
            self.task_id,
            self.process_id,
            event["thread_id"],
            event["event_loop_id"],
            event["sequence"],
            requested_state,
            accepted,
            reason,
        )
        return event

    @property
    def terminal_state(self):
        with self._lock:
            return self._terminal_state

    @property
    def completed_at(self):
        with self._lock:
            return self._completed_at

    @property
    def transition_history(self):
        with self._lock:
            return [dict(event) for event in self._transition_history]

    def _publish_nonterminal(self, state, meta):
        if state not in {states.STARTED, "PROGRESS"}:
            raise ValueError(f"Unsupported non-terminal Celery state: {state}")
        with self._lock:
            if self._terminal_intent or self._terminal_state:
                self._record(
                    state,
                    accepted=False,
                    reason=f"terminal_{self._terminal_intent or self._terminal_state}_already_requested",
                )
                return False
            try:
                self.backend.store_result(self.task_id, meta, state)
            except Exception as exc:
                self._record(state, accepted=False, reason="result_backend_write_failed")
                logger.warning(
                    "Celery PDF task progress skipped job_id=%s task_id=%s state=%s error=%s",
                    self.job_id,
                    self.task_id,
                    state,
                    exc,
                )
                return False
            self._record(state, accepted=True, reason="result_backend_write_completed")
            return True

    def started(self, meta=None):
        payload = dict(meta or {})
        payload.setdefault("status", "started")
        payload.setdefault("progress", 0)
        payload.setdefault("job_id", self.job_id)
        payload.setdefault("task_id", self.task_id)
        payload.setdefault("started_at", self.started_at)
        return self._publish_nonterminal(states.STARTED, payload)

    def progress(self, meta):
        payload = dict(meta or {})
        payload.setdefault("job_id", self.job_id)
        payload.setdefault("task_id", self.task_id)
        return self._publish_nonterminal("PROGRESS", payload)

    def close_progress_for_failure(self):
        """Block new progress before fatal database/Redis cleanup begins."""
        with self._lock:
            if self._terminal_state or self._terminal_intent:
                self._record(
                    "FAILURE_INTENT",
                    accepted=False,
                    reason=f"terminal_{self._terminal_intent or self._terminal_state}_already_requested",
                )
                return False
            self._terminal_intent = states.FAILURE
            self._record(
                "FAILURE_INTENT",
                accepted=True,
                reason="progress_closed_and_synchronous_writes_drained",
            )
            return True

    def _publish_terminal(self, state, result, *, traceback_text=None):
        if state not in self.TERMINAL_STATES:
            raise ValueError(f"Unsupported terminal Celery state: {state}")
        with self._lock:
            if self._terminal_state is not None or self._terminal_write_attempted:
                self._record(
                    state,
                    accepted=False,
                    reason=f"terminal_{self._terminal_state or self._terminal_intent}_already_requested",
                )
                return False
            if self._terminal_intent not in {None, state}:
                self._record(
                    state,
                    accepted=False,
                    reason=f"conflicts_with_terminal_{self._terminal_intent}",
                )
                return False

            self._terminal_intent = state
            self._terminal_write_attempted = True
            try:
                if traceback_text is None:
                    self.backend.store_result(self.task_id, result, state)
                else:
                    self.backend.store_result(
                        self.task_id,
                        result,
                        state,
                        traceback=traceback_text,
                    )
            except Exception:
                self._record(state, accepted=False, reason="terminal_backend_write_failed")
                raise

            self._terminal_state = state
            self._completed_at = datetime.now(timezone.utc).isoformat()
            self._record(state, accepted=True, reason="terminal_backend_write_completed")
            return True

    def success(self, result):
        completed_at = datetime.now(timezone.utc).isoformat()
        payload = dict(result or {})
        payload.update(
            {
                "status": "completed",
                "success": True,
                "job_id": self.job_id,
                "celery_task_id": self.task_id,
                "worker_pid": self.process_id,
                "started_at": self.started_at,
                "completed_at": completed_at,
                "final_celery_state": states.SUCCESS,
            }
        )
        if not self._publish_terminal(states.SUCCESS, payload):
            raise RuntimeError("Celery PDF task SUCCESS was not published exactly once")
        return payload

    def failure(self, error, *, traceback_text=None):
        with self._lock:
            needs_close = self._terminal_intent is None
        if needs_close:
            self.close_progress_for_failure()
        return self._publish_terminal(
            states.FAILURE,
            error,
            traceback_text=traceback_text,
        )


def _run_worker_event_loop():
    global _loop, _loop_start_error

    loop = None
    try:
        if os.name == "nt":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _loop = loop
        logger.info(
            "Celery async event loop started process_id=%s loop_id=%s thread_id=%s",
            os.getpid(),
            id(loop),
            threading.get_ident(),
        )
        loop.call_soon(_loop_ready.set)
        loop.run_forever()
    except BaseException as exc:
        _loop_start_error = exc
        _loop_ready.set()
        logger.exception("Celery async event loop failed: %s", exc)
    finally:
        if loop is not None and not loop.is_closed():
            pending = asyncio.all_tasks(loop)
            for pending_task in pending:
                pending_task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()
            logger.info(
                "Celery async event loop closed process_id=%s loop_id=%s",
                os.getpid(),
                id(loop),
            )
        _loop = None


def get_or_create_event_loop():
    global _loop_thread, _loop_start_error

    with _loop_lock:
        if (
            _loop is not None
            and not _loop.is_closed()
            and _loop.is_running()
            and _loop_thread is not None
            and _loop_thread.is_alive()
        ):
            return _loop

        _loop_ready.clear()
        _loop_start_error = None
        _loop_thread = threading.Thread(
            target=_run_worker_event_loop,
            name=f"celery-async-loop-{os.getpid()}",
            daemon=True,
        )
        _loop_thread.start()
        if not _loop_ready.wait(timeout=10):
            raise RuntimeError("Timed out starting the Celery async event loop")
        if _loop_start_error is not None:
            raise RuntimeError("Failed to start the Celery async event loop") from _loop_start_error
        if _loop is None or _loop.is_closed() or not _loop.is_running():
            raise RuntimeError("Celery async event loop did not enter a running state")
        return _loop


async def _close_worker_async_resources():
    from celery_db_manager import celery_db_manager
    from services.redis_status_tracker import redis_status_tracker

    await redis_status_tracker.close()
    await celery_db_manager.close()


def shutdown_celery_event_loop(*, close_resources=True):
    global _loop_thread

    loop = _loop
    loop_thread = _loop_thread
    if loop is None or loop.is_closed():
        _loop_thread = None
        return

    if close_resources and loop.is_running():
        cleanup = asyncio.run_coroutine_threadsafe(_close_worker_async_resources(), loop)
        try:
            cleanup.result(timeout=30)
        except Exception as exc:
            logger.warning("Celery async resource cleanup failed: %s", exc)

    if loop.is_running():
        loop.call_soon_threadsafe(loop.stop)
    if loop_thread is not None and loop_thread is not threading.current_thread():
        loop_thread.join(timeout=10)
        if loop_thread.is_alive():
            logger.warning(
                "Celery async event loop thread did not stop process_id=%s loop_id=%s",
                os.getpid(),
                id(loop),
            )
    _loop_thread = None


async def init_ai_processor():
    global _ai_processor

    if _ai_processor is None:
        from services.smart_ai_processor import smart_ai_processor

        _ai_processor = smart_ai_processor
        print("SmartAIProcessor initialized in Celery worker")

    return _ai_processor


async def init_xbrl_generator():
    global _xbrl_generator

    if _xbrl_generator is None:
        from services.xbrl_generator import XBRLGenerator

        _xbrl_generator = XBRLGenerator()
        print("XBRLGenerator initialized in Celery worker")

    return _xbrl_generator


@worker_ready.connect
def worker_ready_handler(**kwargs):
    print("Celery worker is ready")

    try:
        from services.xbrl_template_service import get_xbrl_template_service

        xbrl_service = get_xbrl_template_service()
        if xbrl_service.templates:
            stats = xbrl_service.get_statistics()
            print(
                f"Loaded {stats['total_templates']} XBRL templates with "
                f"{stats['total_concepts']} unique concepts"
            )
        else:
            print("CRITICAL: XBRL templates failed to load in Celery worker.")
    except Exception as exc:
        print(f"Error loading XBRL templates in Celery worker: {exc}")

    try:
        from celery_db_manager import celery_db_manager

        run_async_in_celery(celery_db_manager.initialize())
        if settings.extraction_pipeline == "legacy" or settings.extraction_allow_legacy_fallback:
            run_async_in_celery(init_ai_processor())
        else:
            print("Azure DI extraction pipeline configured; legacy SmartAIProcessor not initialized")
        run_async_in_celery(init_xbrl_generator())
        print(f"Worker initialization complete (pipeline={settings.extraction_pipeline})")
    except Exception as exc:
        print(f"Worker initialization warning: {exc}")


@worker_shutdown.connect
def worker_shutdown_handler(**kwargs):
    print("Celery worker shutting down")
    shutdown_celery_event_loop(close_resources=True)


def run_async_in_celery(coro):
    loop = get_or_create_event_loop()

    try:
        if threading.current_thread() is _loop_thread:
            raise RuntimeError("Cannot synchronously submit Celery work from its async loop thread")
        return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=600)
    except Exception as exc:
        print(f"Error running async coroutine: {exc}")
        traceback.print_exc()
        raise


async def mark_pdf_job_failed(
    job_id,
    *,
    error_code,
    safe_message,
    session_manager=None,
):
    """Best-effort fatal cleanup on the Celery-owned async resource loop."""
    from celery_db_manager import celery_db_manager
    from database import FilingJob
    from services.redis_status_tracker import redis_status_tracker
    from sqlalchemy import select
    from schemas import ProgressUpdate

    manager = session_manager or celery_db_manager
    error_text = f"[{error_code}] {_safe_task_error_message(safe_message)}"
    marked_error = False
    redis_failure_needed = False

    try:
        async with manager.get_session() as db:
            try:
                await db.rollback()
            except Exception:
                pass
            result = await db.execute(select(FilingJob).where(FilingJob.id == job_id))
            job = result.scalar_one_or_none()
            if job is not None and job.status == JobStatus.PROCESSING.value:
                job.status = JobStatus.ERROR.value
                if hasattr(job, "progress"):
                    job.progress = 0
                if hasattr(job, "error_message"):
                    job.error_message = error_text
                await db.commit()
                marked_error = True
                redis_failure_needed = True
                logger.error(
                    "Celery fatal cleanup marked filing job ERROR job_id=%s error_code=%s",
                    job_id,
                    error_code,
                )
            elif job is not None:
                redis_failure_needed = job.status == JobStatus.ERROR.value
                logger.info(
                    "Celery fatal cleanup preserved terminal filing status job_id=%s status=%s",
                    job_id,
                    job.status,
                )
    except Exception as exc:
        redis_failure_needed = True
        logger.exception(
            "Celery fatal database cleanup failed job_id=%s error_code=%s: %s",
            job_id,
            error_code,
            exc,
        )

    if redis_failure_needed:
        try:
            await redis_status_tracker.initialize()
            await redis_status_tracker.update_progress(
                ProgressUpdate(
                    job_id=job_id,
                    progress=0,
                    status=JobStatus.ERROR,
                    message=error_text,
                )
            )
        except Exception as exc:
            logger.warning(
                "Celery fatal Redis cleanup failed job_id=%s error_code=%s: %s",
                job_id,
                error_code,
                exc,
            )

    return marked_error


def record_fatal_pdf_task_failure(job_id, error):
    if isinstance(error, PdfProcessingTaskError):
        task_error = error
    else:
        task_error = PdfProcessingTaskError(
            PDF_TASK_EXECUTION_ERROR_CODE,
            "Celery PDF processing failed before completion.",
        )
    try:
        return run_async_in_celery(
            mark_pdf_job_failed(
                job_id,
                error_code=task_error.error_code,
                safe_message=task_error.safe_message,
            )
        )
    except Exception as cleanup_error:
        logger.exception(
            "Could not complete fatal filing cleanup job_id=%s error_code=%s: %s",
            job_id,
            task_error.error_code,
            cleanup_error,
        )
        return False


async def _run_legacy_pdf_processing(
    celery_task_id: str,
    job_id: int,
    db,
    *,
    state_reporter: CeleryTaskStateReporter | None = None,
):
    reporter = state_reporter or CeleryTaskStateReporter(celery_task_id, job_id)
    processor = await init_ai_processor()
    reporter.progress(
        {
            "status": "Starting legacy PDF processing...",
            "progress": 0,
            "job_id": job_id,
        }
    )
    print(f"Starting legacy PDF processing for job {job_id}")
    result = await processor.process_pdf(job_id, db)
    print(f"Legacy PDF processing completed for job {job_id}: {result.status}")
    return result


async def _run_azure_di_pdf_processing(
    celery_task_id: str,
    job_id: int,
    db,
    *,
    state_reporter: CeleryTaskStateReporter | None = None,
):
    from services.azure_di_production_extraction import process_azure_di_filing_job

    reporter = state_reporter or CeleryTaskStateReporter(celery_task_id, job_id)

    def update_celery_progress(
        *,
        progress,
        status,
        message,
        job_id,
        current_page=None,
        total_pages=None,
        items_extracted=None,
    ):
        meta = {
            "status": message,
            "progress": progress,
            "job_id": job_id,
        }
        if current_page is not None:
            meta["current_page"] = current_page
        if total_pages is not None:
            meta["total_pages"] = total_pages
        if items_extracted is not None:
            meta["items_extracted"] = items_extracted
        if status == JobStatus.ERROR:
            meta["error"] = message
        reporter.progress(meta)

    reporter.progress(
        {
            "status": "Processing with Azure Document Intelligence",
            "progress": 0,
            "job_id": job_id,
        }
    )
    print(f"Starting Azure Document Intelligence processing for job {job_id}")
    result = await process_azure_di_filing_job(
        job_id,
        db,
        progress_callback=update_celery_progress,
    )
    print(f"Azure Document Intelligence processing completed for job {job_id}: {result.status}")
    return result


async def process_pdf_job_async(
    job_id: int,
    celery_task_id: str,
    *,
    session_manager=None,
    state_reporter: CeleryTaskStateReporter | None = None,
):
    from celery_db_manager import celery_db_manager

    celery_task_id = _require_celery_task_id(celery_task_id)
    manager = session_manager or celery_db_manager
    reporter = state_reporter or CeleryTaskStateReporter(celery_task_id, job_id)

    async with manager.get_session() as db:
        from services.redis_status_tracker import redis_status_tracker

        await redis_status_tracker.initialize()
        logger.info(
            "Celery PDF task resources ready process_id=%s loop_id=%s db_engine_loop_id=%s "
            "redis_client_loop_id=%s job_id=%s task_id=%s",
            os.getpid(),
            id(asyncio.get_running_loop()),
            getattr(manager, "creation_loop_id", None),
            getattr(redis_status_tracker, "creation_loop_id", None),
            job_id,
            celery_task_id,
        )

        pipeline = settings.extraction_pipeline
        if pipeline == "azure_di":
            result = await _run_azure_di_pdf_processing(
                celery_task_id,
                job_id,
                db,
                state_reporter=reporter,
            )
            if result.status == JobStatus.ERROR and settings.extraction_allow_legacy_fallback:
                print(f"Azure DI failed for job {job_id}; explicit legacy fallback is enabled")
                result = await _run_legacy_pdf_processing(
                    celery_task_id,
                    job_id,
                    db,
                    state_reporter=reporter,
                )
        elif pipeline == "legacy":
            result = await _run_legacy_pdf_processing(
                celery_task_id,
                job_id,
                db,
                state_reporter=reporter,
            )
        else:
            raise ValueError(f"Unsupported EXTRACTION_PIPELINE: {pipeline}")

        if result.status == JobStatus.ERROR:
            raise PdfProcessingTaskError(
                PDF_PROCESSING_ERROR_CODE,
                result.error or result.message or "PDF processing failed.",
            )

        payload = {
            "status": "completed",
            "job_id": job_id,
            "message": result.message or f"{pipeline} PDF processing completed successfully",
            "success": True,
            "filing_status": result.status.value,
            "extracted_row_count": result.extracted_row_count,
            "ai_mapping_status": result.ai_mapping_status,
            "ai_suggestion_count": result.ai_suggestion_count,
            "warnings": list(result.warnings),
            "worker_event_loop_id": id(asyncio.get_running_loop()),
        }
        if result.optional_stage:
            payload.update(
                {
                    "optional_stage": result.optional_stage,
                    "optional_stage_status": result.optional_stage_status,
                    "optional_stage_error_code": result.optional_stage_error_code,
                    "optional_stage_error_message": result.optional_stage_error_message,
                }
            )
        return payload


@celery_app.task(
    bind=True,
    name="app.tasks.process_pdf_task",
    ignore_result=True,
    store_errors_even_if_ignored=False,
)
def process_pdf_task(self, job_id: int):
    celery_task_id = getattr(getattr(self, "request", None), "id", None)
    state_reporter = None
    try:
        celery_task_id = _require_celery_task_id(celery_task_id)
        state_reporter = CeleryTaskStateReporter(celery_task_id, job_id)
        logger.info(
            "Celery PDF task identity captured process_id=%s thread_id=%s job_id=%s task_id=%s",
            os.getpid(),
            threading.get_ident(),
            job_id,
            celery_task_id,
        )
        state_reporter.started()
        result = run_async_in_celery(
            process_pdf_job_async(
                job_id=job_id,
                celery_task_id=celery_task_id,
                state_reporter=state_reporter,
            )
        )
        return state_reporter.success(result)
    except Exception as exc:
        if isinstance(exc, PdfProcessingTaskError):
            task_error = exc
        else:
            task_error = PdfProcessingTaskError(
            PDF_TASK_EXECUTION_ERROR_CODE,
            "Celery PDF processing failed before completion.",
        )
        if state_reporter is not None:
            state_reporter.close_progress_for_failure()
        logger.exception(
            "Fatal PDF task failure job_id=%s task_id=%s error_code=%s: %s",
            job_id,
            celery_task_id,
            task_error.error_code,
            exc,
        )
        record_fatal_pdf_task_failure(job_id, task_error)
        if state_reporter is not None and state_reporter.terminal_state is None:
            try:
                state_reporter.failure(
                    task_error,
                    traceback_text=traceback.format_exc(),
                )
            except Exception as terminal_error:
                logger.exception(
                    "Celery PDF FAILURE terminalization failed job_id=%s task_id=%s error=%s",
                    job_id,
                    celery_task_id,
                    terminal_error,
                )
        if task_error is exc:
            raise
        raise task_error from exc


@celery_app.task(bind=True, name="app.tasks.generate_xbrl_task")
def generate_xbrl_task(self, job_id: int, include_unreviewed: bool = False):
    async def async_generate():
        from celery_db_manager import celery_db_manager

        xbrl_generator = await init_xbrl_generator()

        async with celery_db_manager.get_session() as db:
            try:
                from services.redis_status_tracker import redis_status_tracker

                await redis_status_tracker.initialize()

                self.update_state(
                    state="PROGRESS",
                    meta={
                        "status": "Generating XBRL...",
                        "progress": 50,
                        "job_id": job_id,
                    },
                )
                print(f"Starting XBRL generation for job {job_id}")

                result = await xbrl_generator.generate_xbrl(job_id, db, include_unreviewed)
                print(f"XBRL generation completed for job {job_id}: {result.success}")

                if not result.success:
                    return {
                        "status": "error",
                        "job_id": job_id,
                        "error": result.error,
                        "success": False,
                    }

                return {
                    "status": "completed",
                    "job_id": job_id,
                    "file_path": result.file_path,
                    "success": result.success,
                }
            except Exception as exc:
                error_msg = str(exc)
                print(f"Error in XBRL generation task: {error_msg}")
                traceback.print_exc()
                return {
                    "status": "error",
                    "job_id": job_id,
                    "error": error_msg,
                    "success": False,
                }

    try:
        return run_async_in_celery(async_generate())
    except Exception as exc:
        error_msg = str(exc)
        print(f"Fatal error in generate_xbrl_task: {error_msg}")
        traceback.print_exc()
        return {
            "status": "error",
            "job_id": job_id,
            "error": f"Fatal task error: {error_msg}",
            "success": False,
        }


def get_task_status(task_id: str):
    try:
        result = celery_app.AsyncResult(task_id)
        status_info = {
            "task_id": task_id,
            "state": result.state,
            "ready": result.ready(),
            "successful": None,
            "info": None,
            "error": None,
        }

        if result.ready():
            status_info["successful"] = result.successful()
            if result.successful():
                status_info["info"] = result.result
            else:
                try:
                    status_info["error"] = str(result.result)
                except Exception:
                    status_info["error"] = "Task failed with unknown error"
        else:
            try:
                status_info["info"] = result.info
            except Exception:
                status_info["info"] = {"status": "running"}

        return status_info
    except Exception as exc:
        return {
            "task_id": task_id,
            "state": "UNKNOWN",
            "ready": False,
            "successful": None,
            "info": None,
            "error": f"Error getting task status: {exc}",
        }


def cancel_task(task_id: str):
    try:
        celery_app.control.revoke(task_id, terminate=True)
        return {"status": "cancelled", "task_id": task_id}
    except Exception as exc:
        return {"status": "error", "task_id": task_id, "error": str(exc)}


@celery_app.task
def health_check():
    return {
        "status": "healthy",
        "timestamp": str(time.time()),
        "worker": "ready",
        "processor": settings.extraction_pipeline,
    }


@celery_app.task
def cleanup_old_results():
    try:
        temp_dir = settings.temp_directory
        if os.path.exists(temp_dir):
            for filename in os.listdir(temp_dir):
                file_path = os.path.join(temp_dir, filename)
                try:
                    if os.path.isfile(file_path):
                        file_age = time.time() - os.path.getctime(file_path)
                        if file_age > 3600:
                            os.remove(file_path)
                except Exception as exc:
                    print(f"Error removing temp file {file_path}: {exc}")

        return {"status": "completed", "message": "Cleanup completed"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


celery_app.conf.beat_schedule = {
    "cleanup-temp-files": {
        "task": "tasks.cleanup_old_results",
        "schedule": crontab(minute=0),
    },
}
celery_app.conf.timezone = "UTC"
