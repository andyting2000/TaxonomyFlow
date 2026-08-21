# Celery Task Identity Handoff Hotfix 1

## Status

Implemented and verified locally. Manual INFO House and three-PDF worker smoke tests remain pending.

## Job 54 Failure

Celery received task `1eb01232-6766-4085-9e73-499b36db976b` for Job 54. The persistent asyncio loop thread then observed `task_id=None`, and `task.update_state` raised `ValueError: task_id must not be empty`. Azure DI was never submitted, the task wrapper returned an error dictionary that Celery recorded as `SUCCESS`, and the FilingJob remained `PROCESSING`.

## Confirmed Root Cause

`Task.request` is a Celery thread/context-local proxy. The persistent-loop fix passed the bound Task object from the Celery task thread to another thread. Reading `Task.request.id` or using `Task.update_state` in that loop thread therefore depended on request context that was not available there.

The persistent event-loop architecture remains correct and was not reverted.

## Identity Handoff

`process_pdf_task` now captures and validates `self.request.id` synchronously before crossing threads. The persistent-loop coroutine receives only primitive immutable context:

- `job_id`
- `celery_task_id`

`process_pdf_job_async`, `_run_azure_di_pdf_processing`, and `_run_legacy_pdf_processing` do not receive a bound Celery Task and do not access `Task.request` or `Task.update_state`.

## Progress Strategy

Celery progress uses `update_celery_task_state`, which calls the configured result backend with the explicit task ID. Backend failures are warnings and cannot abort extraction.

Application progress continues through the existing Redis tracker and FilingJob fields. These resources remain on the persistent owning loop.

## Fatal Cleanup And Final State

Fatal wrapper cleanup runs on the persistent loop with `celery_db_manager`:

- A job still in `PROCESSING` becomes `ERROR`.
- Progress becomes zero.
- `error_message` receives a stable bracketed code and safe message.
- Redis receives an `ERROR` update where possible.
- `REVIEW` or `COMPLETED` is preserved.

Fatal main-processing failures are re-raised as `PdfProcessingTaskError`, so Celery records `FAILURE` rather than normal `SUCCESS` with `success=false` data. Azure DI failures already handled by the extraction service remain `ERROR`; optional mapping failures after persisted extraction remain `REVIEW` with `ai_mapping_status=failed`.

## Automated Evidence

- Task identity handoff: 9 tests passed.
- Persistent loop lifecycle: 5 tests passed.
- Azure DI discovery: 213 tests passed.
- Focused Celery, mapping, ranked-candidate, and critical-path regressions: 71 tests passed.
- Full backend discovery: 1,198 tests passed in 37.740 seconds.

No live Azure DI, LLM, PostgreSQL mutation, or production job mutation occurred.

## Job 54 And Manual Retest

Use the existing application workflow to delete Job 54 or safely mark it `ERROR`; no broad repair tool was added. After deployment:

1. Restart the backend.
2. Stop every Celery worker and start one clean worker.
3. Upload INFO House once.
4. Confirm the captured and loop-thread task IDs are non-null and equal.
5. Confirm Azure DI submission begins, rows persist, and the job reaches `REVIEW`.
6. Confirm no empty-task-ID, cross-loop, or asyncpg protocol-state error occurs.
7. Resume the three-PDF sequential smoke.
