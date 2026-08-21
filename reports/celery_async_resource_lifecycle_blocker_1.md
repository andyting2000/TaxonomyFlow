# Celery Async Resource Lifecycle Blocker 1

## Status

Implemented with automated verification complete. The manual three-PDF worker smoke remains pending.

## Confirmed Root Cause

This was a Celery async resource lifecycle defect, not an Azure Document Intelligence quota or PDF limit.

On Windows, Celery uses a four-thread worker pool. The old `get_or_create_event_loop` ran in each calling task thread, so different threads could create different asyncio loops. The process-global Celery SQLAlchemy `AsyncEngine`/asyncpg pool and global async Redis client survived those task invocations. A later task could therefore reuse a connection or future bound to an earlier loop, producing `Future attached to a different loop` and asyncpg `unknown protocol state 3` failures.

## Selected Strategy

Option A: one worker-scoped persistent event loop.

- One dedicated daemon thread continuously runs one asyncio event loop per Celery worker process.
- Celery task threads submit async work to that loop with `asyncio.run_coroutine_threadsafe`.
- Worker initialization creates the Celery database engine/session factory on that loop.
- Redis initializes on that loop.
- Worker shutdown closes Redis, disposes the Celery engine, and then stops the loop.
- Resource owners record process and loop IDs. The database manager rejects incompatible-loop reuse.

The Windows worker may still accept overlapping tasks. Their coroutines, SQLAlchemy sessions, and Redis operations execute on the same compatible loop, so `worker_concurrency=1` is not used as a substitute for correct ownership.

## Database And Redis

Celery continues using `celery_db_manager`; extraction and mapping services receive its session explicitly. The FastAPI global engine is not selected for Celery extraction, persistence, mapping suggestions, or XBRL tasks.

The Redis tracker records its creation process/loop, returns immediately for the same owner context, and never awaits the old client from an incompatible context. Normal worker shutdown closes it on the persistent loop.

Diagnostic logs now include process ID, event loop ID, engine/client loop IDs, job ID, task ID, and loop-thread ID without database URLs or credentials.

## Mapping Failure Isolation

Successful Azure DI extraction remains in `REVIEW` when advisory mapping suggestions fail. `ai_mapping_status` becomes `failed`, and the existing error-message field receives a stable bracketed code. Cross-loop or asyncpg protocol-state messages use `async_resource_loop_mismatch`.

For the Fine Batik symptom, the 107 persisted rows remain available. A mapping failure no longer changes extraction status or poisons the resources needed by the next filing.

## Automated Evidence

- Focused lifecycle tests: 5 passed. Three sequential task invocations shared one worker loop; each queried a filing, updated Redis, persisted rows, and reached `REVIEW`. Job 2 simulated a mapping failure; Job 3 still completed.
- Azure DI regressions: 213 passed, including timeout fallback.
- Mapping, ranked-candidate, and ownership regressions: 76 passed.
- Critical-path regressions: 10 passed.
- Full backend discovery: 1,189 passed in 35.887 seconds.

No live Azure DI, Redis, PostgreSQL, Qwen, Supervisor, or other external provider was called by these tests.

## Manual Retest Plan

1. Restart backend and Celery once.
2. Process Bezlife, Fine Batik, and INFO House sequentially without restarting Celery.
3. Confirm all reach `REVIEW` and have extracted rows greater than zero.
4. Confirm mapping suggestions complete or fail independently.
5. Confirm the third filing submits to Azure DI normally.
6. Confirm worker logs contain no different-loop or asyncpg protocol-state errors.

`#18F-G-A-quality-smoke-closeout` remains pending until this manual smoke passes.
