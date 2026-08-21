# Supervisor Internal Rollout Safety

**Status:** PASS

## Safe Defaults

Live Supervisor, mapper feedback, orchestration, queue visibility, and mapper
feedback visibility remain off in repository examples. Auto review and auto
remap remain false; the reviewer allowlist is empty and admin-only defaults are
true.

## Bounds

- Initial cohort batch maximum: 5.
- Initial live concurrency: 1 per API process.
- Provider timeout: 120 seconds.
- Guided correction: one durable attempt.
- Batch execution: sequential.
- Suggestion row locks serialize duplicate review/remap actions.
- Terminal suggestions, existing revisions, retry exhaustion, and stale
  frontend requests fail closed against backend predicates.

## Payload Boundary

Auditor XML, parsed auditor facts, benchmark gold mappings, target correct
qnames, and evaluation labels remain prohibited from external payloads.

Expected safety counters remain:

```text
auto_review_calls = 0
auto_remap_calls = 0
auto_apply = 0
orchestration_confirmed_tag_mutations = 0
orchestration_final_mapping_mutations = 0
```

## Kill Switch

Disable backend calls first:

1. `SUPERVISOR_PRODUCTION_LIVE_ENABLED=false`
2. `SUPERVISOR_MAPPER_FEEDBACK_ENABLED=false`
3. `SUPERVISOR_ORCHESTRATION_ENABLED=false`

Hide frontend controls on the next build. Disabling the feature preserves
suggestions, reviews, revisions, human decisions, and ordinary review.

Five focused safety tests, 170 Supervisor tests, 30 frontend tests, and the
1,266-test full backend suite passed. No live provider, production DB, XBRL, or
Arelle action occurred.
