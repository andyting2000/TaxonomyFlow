# Celery Terminal-State Live Smoke Closeout

## Result

**Pass, with one documented sequence-protocol deviation.**

All three fresh PDF jobs reached `REVIEW`, persisted nonzero extracted rows, and retained explicit Celery `SUCCESS` results with `date_done` and complete final payloads. No successful task remained at `PROGRESS 100`.

The uploads started in the requested Bezlife, Fine Batik, INFO House order, but they overlapped instead of waiting for each preceding task to become terminal. This run therefore validates concurrent reuse of one worker and persistent event loop, not strict serial-upload timing.

## Live Jobs

| Filing | Job | Celery task UUID | Rows | Filing status | AI status | Suggested / persisted | Celery state | `date_done` |
| --- | ---: | --- | ---: | --- | --- | ---: | --- | --- |
| BEZLIFE MARKETING SDN. BHD. | 59 | `a4a27040-c6e1-45f8-8acb-c4bad0ee7d95` | 76 | `REVIEW` | `completed` | 9 / 50 | `SUCCESS` | `2026-07-23T03:11:41.911363+00:00` |
| FINE BATIK SDN. BHD. | 60 | `204ff4ae-9e21-441d-8df3-ebfe5e275a0b` | 107 | `REVIEW` | `completed` | 13 / 50 | `SUCCESS` | `2026-07-23T03:11:49.867850+00:00` |
| AGENSI PEKERJAAN INFO-HOUSE (M) SDN. BHD. | 61 | `050873a6-b198-4d81-bde6-1b03ff63b135` | 83 | `REVIEW` | `completed` | 13 / 50 | `SUCCESS` | `2026-07-23T03:12:14.228989+00:00` |

The payload count is the mapping run's `suggestions_generated` count. Each job has 50 persisted mapping records, including rejected/no-selection records: 9 suggested plus 41 rejected for Bezlife, and 13 suggested plus 37 rejected for each other filing.

## Final Payloads

All three payloads contain:

- `success=true`
- `filing_status=REVIEW`
- the matching extracted-row count
- `ai_mapping_status=completed`
- warnings
- the concrete Celery task UUID
- worker PID and event-loop ID
- `started_at`, `completed_at`, and `final_celery_state=SUCCESS`

Bezlife and INFO House completed without warnings. Fine Batik completed with the stable `azure_di_text_block_normalization_timeout` warning and used table candidates. This was an Azure normalization fallback, not an optional mapping failure; its 107 rows remained persisted, AI mapping completed, and the following INFO House job completed normally.

## Terminal-State Evidence

The three Redis task records were read twice, 47.613 seconds apart. Each remained `SUCCESS` with the same `date_done` and identical raw-record SHA-256 hash:

| Job | Raw record SHA-256 |
| ---: | --- |
| 59 | `e479b57f4604377e942c5ce43015e70b8626d1ac8f6704ed5b8ade3be6557960` |
| 60 | `18b204f79a2c9dd4094fb78b3c2397ce4abf342d7041e4b7ca1b00e2c651403a` |
| 61 | `137e197ef383786b974aa2548d76f65585571099e74c00ee97aaf22ce5d44019` |

No late `PROGRESS` replacement or reversed terminal transition was observed. Redis retains one current record per task UUID, so historical duplicate writes cannot be reconstructed; the retained-record evidence is supplemented by the terminal-guard regression tests.

## Worker And Provenance

- All payloads identify worker PID `15452` and event-loop ID `122218384`.
- The worker started after the current `tasks.py` modification time.
- Celery inspect found one responding node, exactly three processed PDF tasks, and no active, reserved, or scheduled tasks.
- PostgreSQL had zero `PROCESSING` filing jobs.
- Each job's page count equaled its distinct page-number count.
- No exact same-page duplicate extracted-row group was found.
- Filing error fields, AI error fields, and Celery tracebacks were null.
- No persisted backend/Celery worker log was available; cross-loop and protocol-state conclusions use the retained errors/results plus focused regression coverage.

## Sequence Caveat

Fine Batik started about 31 seconds after Bezlife, and INFO House started about 26 seconds after Fine Batik, while the prior jobs were still running. Strict wait-until-terminal sequencing was therefore not followed. All three nevertheless completed on the same worker and persistent loop without restart, and INFO House completed after Fine Batik's fallback without contamination.

## Verification

- `tests.test_celery_terminal_state_finalization`: 11 passed
- `tests.test_celery_task_identity_handoff`: 9 passed
- `tests.test_celery_async_resource_lifecycle`: 5 passed
- Total focused tests: 25 passed
- Full backend discovery was not rerun because no implementation code changed.

## Safety

This closeout made no implementation, extraction, mapping, Supervisor, frontend, database/job, `confirmed_tag_id`, XBRL, or Arelle change. It initiated no external provider call. The audit only read retained PostgreSQL, Redis, process, and Celery inspection evidence and ran local focused tests.

## Conclusion

Explicit Celery terminal-state handling passed live verification. The ingestion/Celery blocker is operationally closed: every fresh PDF task retained `SUCCESS`, `date_done`, and a final payload, while persistent-loop and task-identity safeguards remained stable.

Recommended next feature: **#18F-G-A-quality-smoke-closeout - Validate five Supervisor-guided mapping revisions**.
