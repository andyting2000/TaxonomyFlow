# Supervisor Production Integration Design Report (#17D-C-A)

Date: 2026-06-17

## Summary

#17D-C-A produced a design-only production integration plan for the Supervisor review layer. No production behavior changed.

The design attaches Supervisor review as advisory metadata to AI mapping suggestions and extracted rows. Supervisor remains a reviewer of mapper output, not a mapper and not an auto-accept engine.

## Evidence Basis

Final bounded 29-row live retest:

- `safe_to_accept=15`
- `safe_to_accept_accuracy=1.0`
- `agree_accuracy=1.0`
- `false_safe_accept_count=0`
- `false_agree_count=0`
- `invalid_response_count=0`
- `blocked_correct_mapping_count=4`
- `broad_substitute_total=0`
- `cash_flow_false_safe_accept_count=0`

## Proposed Architecture

- Persist Supervisor reviews separately in a future `mapping_supervisor_reviews` table.
- Attach reviews primarily to `llm_mapping_suggestions`.
- Also support extracted-row reviews for mapper omissions.
- Use job-level batch execution only as an operational grouping.
- Keep Supervisor metadata independent from confirmed mappings.

## Proposed DB/API/UI Design

DB:

- Future migration `012_add_mapping_supervisor_reviews.sql`.
- Store status, decision, risk, action, advisory safe flags, issues, reason, model metadata, prompt/schema versions, payload/response hashes, and sanitized errors.
- Store hashes by default, not raw payloads.

API:

- `GET /api/v1/filings/jobs/{job_id}/supervisor-reviews`
- `GET /api/v1/filings/supervisor-reviews/{review_id}`
- `POST /api/v1/filings/jobs/{job_id}/supervisor-reviews/run`
- `POST /api/v1/filings/jobs/{job_id}/supervisor-reviews/run-batch`

UI:

- Display Supervisor badges beside AI suggestions.
- Show reason/issues in collapsible detail.
- Keep Accept/Reject human-controlled.
- Treat `safe_to_accept` and `calibrated_safe_to_accept` as advisory only.

## Safety Boundaries

Supervisor may receive:

- production extracted row context
- mapper suggestion
- candidates
- concept cards
- approved few-shot examples
- do-not-confuse notes

Supervisor must not receive:

- auditor XML
- parsed XML facts
- gold answers
- target correct qnames/template fields
- evaluation labels
- local scoring fields

Supervisor results cannot:

- mutate final mapping
- set `confirmed_tag_id`
- mark suggestions accepted
- generate XBRL
- run Arelle

## Rollout

1. #17D-C-A: design spec only.
2. #17D-C-B: persistence schema/model/migration/tests only.
3. #17D-C-C: backend service/API with mock Supervisor mode only.
4. #17D-C-D: UI display with mock/persisted results only.
5. #17D-C-E: live run or batch behind admin/feature flag.
6. #17D-C-F: monitoring and audit logs.

No auto-apply in any phase unless explicitly approved later.

## Verification

Requested JSON validation:

- `python -B -m json.tool reports\supervisor_production_integration_design_17d_c.json`
- `python -B -m json.tool feature_list.json`

No Markdown lint/doc-check command was found in the inspected repo metadata.

## Next Feature

#17D-C-B: Backend persistence schema, SQLAlchemy model, serializer helpers, and migration tests only. No live LLM call, no endpoint behavior change, no UI change, and no auto-apply.

