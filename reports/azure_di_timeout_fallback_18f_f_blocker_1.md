# Azure DI Timeout Fallback - #18F-F-blocker-1

## Root Cause

asyncio.wait_for timed out the local normalization coroutine, but its asyncio.to_thread worker could not be cancelled. The worker later logged usable normalized candidates after the coroutine had already entered the fatal timeout handler and marked the job ERROR.

Job 48 confirms Azure DI returned successfully before local normalization failed: pages=23, tables=17, table cells=607, table candidates=96, normalized candidates=83.

## Fallback

A local timeout now triggers one bounded table-only normalization attempt from the cached Azure result. The job reaches `REVIEW` only if persistable candidates exist. Structured warning metadata is stored in existing row validation warnings; no database migration is required.

## Fatal Conditions

- Azure DI configuration, submit, or analyze-result failure
- Azure DI result with no usable pages/table evidence
- Table-only fallback with zero persistable candidates
- Table-only fallback timeout or normalization failure
- Database persistence failure

## Manual Retest

1. Restart backend and Celery workers so the hotfix is loaded.
2. Upload the INFO House PDF once, or reuse a cached raw result if an existing isolated path supports it.
3. Confirm the job reaches REVIEW rather than ERROR when the local text-block timeout occurs.
4. Confirm extracted rows are greater than zero and Review Workspace loads them.
5. Confirm logs and row validation_warnings contain azure_di_text_block_normalization_timeout and table_candidates_only.

Recommended next feature after a successful INFO House retest: #18F-G - Decide next path: persistence design vs reviewer UX workflow.
