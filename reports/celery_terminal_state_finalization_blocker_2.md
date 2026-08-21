# Celery Terminal State Finalization Blocker 2

## Result

The code hotfix is complete. PDF tasks now have one explicit-ID result owner for `STARTED`, `PROGRESS`, `SUCCESS`, and `FAILURE`. Terminal writes create `date_done`, return a serializable success payload or exception failure result, and cannot be overwritten by late progress.

The live retest remains pending. Existing jobs 55 and 56 were not rewritten.

## Confirmed Root Cause

Result lifecycle ownership was split:

- Async progress callbacks called the Celery backend directly with the captured task UUID.
- No reporter owned terminalization or blocked a later progress transition.
- Success depended entirely on Celery's separate automatic `mark_as_done` call after the synchronous task returned.
- Jobs 55 and 56 retained `PROGRESS 100` without `date_done`, proving that terminal dependency was not reliable for those tasks.

Celery 5.6.3 was configured with `ignore_result=false`, a Redis backend, and normal automatic success publication. The Azure callbacks were synchronous and awaited, so the repository had no known queued progress writer to drain. The precise internal reason the automatic write was absent or not retained cannot be reconstructed because the old worker console logs were not persisted.

The fix removes that dependency instead of guessing at the unavailable low-level trigger.

## State Sequences

Before:

1. Capture task UUID in Celery task thread.
2. Submit async processing to the persistent worker loop.
3. Write direct explicit-ID `PROGRESS` states.
4. Complete extraction, persistence, and optional mapping.
5. Write `PROGRESS 100`.
6. Return the async result to the task thread.
7. Depend on Celery automatic `mark_as_done` for `SUCCESS`.
8. Jobs 55/56 remained `PROGRESS 100` with no terminal metadata.

After:

1. Capture and validate the task UUID.
2. Create one `CeleryTaskStateReporter`.
3. Publish `STARTED` and all `PROGRESS` states synchronously under one lock.
4. Complete async processing and build the final payload.
5. Establish terminal intent, closing progress and waiting for any lock-owning write to finish.
6. Explicitly store exactly one `SUCCESS` or `FAILURE` with the same UUID.
7. Let the result backend create `date_done`.
8. Return or re-raise only after the terminal write.
9. Reject any later progress attempt.

Celery automatic result storage is disabled only for `app.tasks.process_pdf_task`, so there is no duplicate terminal owner.

## Terminal Guard

`CeleryTaskStateReporter` records safe diagnostics for every requested transition: job ID, task ID, PID, thread ID, loop ID when available, sequence, timestamp, requested state, acceptance, and reason. It never logs document content or credentials.

Progress failures are warning-only. Terminal write failures are not silently treated as success. There is no progress queue and no timing-based drain: the same lock serializes progress, terminal intent, and the terminal backend write.

Forbidden transitions are rejected:

- `SUCCESS -> PROGRESS`
- `FAILURE -> PROGRESS`
- `SUCCESS -> FAILURE`
- `FAILURE -> SUCCESS`
- repeated terminal writes

## Final Payload

Successful tasks store:

- `job_id` and `celery_task_id`
- `filing_status`
- `extracted_row_count`
- `ai_mapping_status` and suggestion count
- warnings and optional-stage metadata
- worker PID and persistent event-loop ID
- start/completion timestamps
- `final_celery_state=SUCCESS`

Fatal core failures close progress before cleanup, move only still-`PROCESSING` jobs to `ERROR`, store `FAILURE` with a `PdfProcessingTaskError`, and re-raise. Existing `REVIEW`/`COMPLETED` states remain preserved.

Optional mapping failure remains nonfatal: extraction rows stay persisted, FilingJob remains `REVIEW`, `ai_mapping_status=failed`, and the task ends `SUCCESS` with `optional_stage=mapping`, a stable code, and a safe message.

## Verification

- Changed-file `py_compile`: passed.
- `tests.test_celery_terminal_state_finalization`: 11 passed.
- `tests.test_celery_task_identity_handoff`: 9 passed.
- `tests.test_celery_async_resource_lifecycle`: 5 passed.
- Combined terminal/identity/lifecycle/timeout checks: 30 passed.
- Azure cutover, timeout, mapping, baseline, and ownership checks: 95 passed.
- Full backend discovery: 1,209 passed in 39.332 seconds against the final tree.
- A real in-memory Celery backend test confirmed `date_done` and decoded terminal result data for both `SUCCESS` and `FAILURE`.

## Observability

No database migration was added. `FilingJob` has no suitable task lifecycle fields, and schema expansion was not essential to correctness. Safe transition logs and the final result payload provide immediate evidence, but result metadata still expires after `result_expires=3600`.

## Manual Retest

Pending:

1. Restart the backend and every Celery worker.
2. Upload a fresh PDF through the normal workflow.
3. Inspect the task before the one-hour result expiry.
4. Confirm `REVIEW`, rows greater than zero, Celery `SUCCESS`, non-null `date_done`, and the final payload.
5. Process multiple PDFs under one worker PID and confirm each reaches terminal `SUCCESS` without restart.
6. Resume #18F-G-A-quality-smoke-closeout and select remapping cases only after Phase A passes.

No live service was called and no job, mapping, `confirmed_tag_id`, XBRL, or Arelle state was changed while implementing this hotfix.
