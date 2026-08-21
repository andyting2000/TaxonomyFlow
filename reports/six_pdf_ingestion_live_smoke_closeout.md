# Six-PDF Ingestion Live Smoke Closeout

## Verdict

Phase A **failed**. Phase B was not run, no remapping cases were selected, and no external provider was called.

The six most recent persisted filing jobs all reached `REVIEW` with nonzero extracted rows. That is not enough to pass the strict lifecycle criteria:

- Job 51 retains an optional-mapping error containing `Future ... attached to a different loop`.
- Jobs 55 and 56 are `REVIEW` in PostgreSQL and idle in the worker, but their Celery backend results remain `PROGRESS` at 100 with no `date_done`.
- Celery task UUIDs and completion timestamps for jobs 50 and 51 expired after one hour and are not stored on `FilingJob`, so task-identity and no-restart evidence is incomplete across all six.

## Filing Evidence

| Job | Filing | Uploaded UTC | Filing status | Pages | Rows | AI status | Suggestions | Celery task/result |
| --- | --- | --- | --- | ---: | ---: | --- | ---: | --- |
| 58 | SHIELD PLUS SDN. BHD. | 2026-07-23 01:40:35 | REVIEW | 15 | 32 | completed | 22 | `a5024edf-f999-4fbc-a354-926baa7d2a4b` / SUCCESS |
| 57 | RAHSIA HERBAL SDN. BHD. | 2026-07-23 01:40:07 | REVIEW | 24 | 101 | completed | 50 | `e9759918-d78c-45a1-a944-23027ac39057` / SUCCESS |
| 56 | AGENSI PEKERJAAN JCONNECTOR.COM SDN. BHD. | 2026-07-23 01:39:21 | REVIEW | 22 | 63 | completed | 50 | `da711d85-d699-463e-befe-ae640653bf3c` / PROGRESS 100 |
| 55 | AGENSI PEKERJAAN INFO-HOUSE (M) SDN. BHD. | 2026-07-23 01:32:41 | REVIEW | 23 | 83 | completed | 50 | `d7b1838e-52dd-4220-b39f-bda0366f4212` / PROGRESS 100 |
| 51 | FINE BATIK SDN. BHD. | 2026-07-22 15:36:22 | REVIEW | 25 | 107 | failed | 6 | expired; UUID not persisted |
| 50 | BEZLIFE MARKETING SDN. BHD. | 2026-07-22 15:31:48 | REVIEW | 26 | 76 | completed | 50 | expired; UUID not persisted |

Total persisted evidence: 135 pages, 462 extracted rows, and 228 AI suggestions.

## Azure DI Evidence

Jobs 55 and 56 retain structured timeout fallback metadata:

| Job | Azure pages | Azure tables | Raw table candidates | Normalized candidates | Persisted rows |
| --- | ---: | ---: | ---: | ---: | ---: |
| 55 | 23 | 17 | 93 | 83 | 83 |
| 56 | 22 | 16 | 72 | 63 | 63 |

For jobs 50, 51, 57, and 58, exact provider table and pre-persistence normalized counts were not retained. Persisted provenance represents at least 11, 12, 12, and 8 distinct table indexes respectively. Their persisted Azure-derived page counts are 26, 25, 24, and 15.

All six contain the bounded text-block-timeout/table-candidate warning. Jobs 55 and 56 include the newer structured `azure_di_text_block_normalization_timeout` metadata.

## Lifecycle Checks

| Check | Result | Evidence |
| --- | --- | --- |
| All FilingJob rows terminal | Pass | All six are REVIEW at 100; the database has zero PROCESSING jobs. |
| Extracted rows greater than zero | Pass | Counts are 76, 107, 83, 63, 101, and 32. |
| Task identity | Inconclusive for all six | Jobs 55-58 have nonempty UUIDs; jobs 50-51 expired and UUIDs are not persisted. |
| Cross-event-loop regression | Fail | Job 51 persisted `Future ... attached to a different loop`. |
| Stuck processing | Filing pass, task-result fail | Worker queues are empty, but jobs 55/56 remain PROGRESS in Celery. |
| Duplicate persistence | Pass | Page counts equal distinct page-number counts; zero exact same-page duplicate row groups. |
| Current-worker freshness | Pass | PID 7428 started at 09:31:22 local, after `tasks.py` was modified at 09:09:00. |
| No restart for current tasks | Pass for jobs 55-58 only | One worker PID processed exactly four PDF tasks; all four reached REVIEW. |
| Optional mapping isolation | Pass with caveat | Job 51 kept 107 rows and REVIEW, but later jobs used a later worker. |

The current worker reported no active, reserved, or scheduled tasks. Jobs 57 and 58 have terminal Celery `SUCCESS` results. Redis TTL evidence places the last writes for jobs 55 and 56 at approximately 01:45:13 and 01:49:21 UTC, matching their last suggestion writes, but those result records never became terminal.

No persisted backend or Celery log file was available. The audit therefore used PostgreSQL state, Redis result metadata, Celery inspect output, process start metadata, and row provenance. Historical checks for `unknown protocol state`, old `task_id=None`, and exact event-loop IDs cannot be completed from retained evidence.

## Phase B

Skipped as required because Phase A failed. The following were not performed:

- Supervisor or mapper provider calls
- case selection
- manual UI instructions
- remapping quality reports
- retry-limit testing

## Safety

This audit was read-only. It did not mutate jobs, mappings, suggestions, `confirmed_tag_id`, or final mapping state. It did not call Azure DI, Qwen, Supervisor, or another external provider. It did not generate XBRL or run Arelle.

## Recommended Blocker

`#18F-G-A-quality-smoke-blocker-2 - Finalize successful explicit-ID Celery PDF tasks to a terminal result state`

The next fix should reproduce why explicit backend `PROGRESS` writes for jobs 55/56 were not followed by terminal `SUCCESS`, add a focused same-task-UUID terminal-state regression, and preserve the persistent-loop and fatal-cleanup safeguards. The internal Celery cause is not yet established because worker logs were not persisted.

After that fix, repeat the smoke with six post-hotfix tasks while their task UUIDs and completion timestamps are still retained.
