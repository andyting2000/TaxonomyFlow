# Manual Review Queue UI/API Plan - Feature #13U

## Scope
Planning only. No DB schema, API route, React UI, mapping, XBRL, Arelle, benchmark rerun, or live model call was implemented.

## Queue Summary
- Auto mappable: 231
- Suggest mapping only: 180
- Manual review required: 336
- Blocked from mapping: 10
- Reference/context only: 183
- Manual review queue items: 709
- Conflict groups: 45

## Future API Design
- `GET /api/v1/extraction-v2/review-batches`: List review batches with summary counts and status filters.
- `POST /api/v1/extraction-v2/review-batches`: Create a review batch from a cleaned candidate report or production extraction job.
- `GET /api/v1/extraction-v2/review-batches/{batch_id}`: Return batch detail, progress, and aggregate review state.
- `GET /api/v1/extraction-v2/review-batches/{batch_id}/items`: List review items with filters for priority, case, row type, gate status, and reason code.
- `GET /api/v1/extraction-v2/review-batches/{batch_id}/conflict-groups`: List conflict groups and all candidate options that block automatic mapping.
- `PATCH /api/v1/extraction-v2/review-items/{item_id}/decision`: Record a reviewer decision or correction for one review item.
- `PATCH /api/v1/extraction-v2/conflict-groups/{group_id}/decision`: Record group-level conflict resolution without discarding candidate evidence.
- `POST /api/v1/extraction-v2/review-batches/{batch_id}/mapping-handoff`: Generate the reviewed mapping input set for future mapping candidate generation.
- `GET /api/v1/extraction-v2/review-batches/{batch_id}/summary`: Return dashboard-ready review progress and blocker counts.
- `GET /api/v1/extraction-v2/review-batches/{batch_id}/export`: Export queue, decisions, and mapping handoff evidence for audit.

## Future React UI Design
- Queue list view: priority, case, row type, gate status, reason-code, conflict-only, and search filters.
- Review detail panel: candidate evidence, reasons, source snippets, and decision controls.
- Conflict group view: all options, value variants, affected pages/sections, and group decisions.
- Mapping handoff preview: allowed, confirmation-required, blocked, and unresolved conflict counts.

## Review State Transitions
- Candidate, conflict group, and batch state machines are defined in the JSON report.

## Mapping Handoff Rules
- Auto mappable candidates may proceed when not conflict-blocked.
- Suggest-only candidates may proceed with `requires_confirmation=true`.
- Manual-review, blocked, reference/context, suppressed, downgraded, and unresolved conflict candidates cannot proceed automatically.

## Non-Goals
- No DB schema or migration implementation.
- No API route implementation.
- No React/frontend implementation.
- No mapping v2 implementation.
- No XBRL generation or Arelle validation.
- No live model calls or benchmark rerun.
