# Supervisor Production Integration Design Spec (#17D-C-A)

Date: 2026-06-17

## Status

This is a design-only artifact. It does not implement production Supervisor behavior.

#17D-B live evaluation and #17D-B-hotfix-7 bounded live retest support moving to production integration design, not production auto-apply. The final bounded 29-row live retest recorded:

- `total_reviewed=29`
- `safe_to_accept=15`
- `safe_to_accept_accuracy=1.0`
- `agree_accuracy=1.0`
- `false_safe_accept_count=0`
- `false_agree_count=0`
- `invalid_response_count=0`
- `blocked_correct_mapping_count=4`
- `broad_substitute_total=0`
- `cash_flow_false_safe_accept_count=0`

Production auto-apply remains explicitly not approved.

## Current Flow Summary

The current production flow is:

1. A normal workspace user uploads a PDF through `routers/filings.py`.
2. `FilingJob` is created with `status=PROCESSING`, owned by `filing_jobs.user_id`.
3. `tasks.process_pdf_task` runs in Celery and dispatches the configured extraction pipeline.
4. The Azure DI production extraction path writes `financial_statement_pages` and `extracted_data_items`.
5. Extracted rows may carry deterministic template mapping fields on `extracted_data_items`, including:
   - `template_field_id`
   - `template_position`
   - `is_required_field`
   - `statement_type`
   - `is_reviewed`
   - `confirmed_tag_id`
6. Qwen AI Mapping Suggestions run through the existing suggestion path:
   - `POST /api/v1/filings/jobs/{job_id}/ai-mapping-suggestions/run`
   - `services.llm_taxonomy_mapping.run_llm_mapping_for_job`
   - `apply_high_confidence=False`
   - `persist_suggestions=True`
7. Suggestions are stored in `llm_mapping_suggestions` with the selected template field, confidence, reason, ranked candidates, model id, diagnostic JSON, and lifecycle status.
8. The React Review Workspace fetches suggestion status and suggestions, then displays them as confirmation-required cards.
9. A user explicitly accepts or rejects a suggestion:
   - accept updates `extracted_data_items.template_field_id`, statement metadata, and `is_reviewed`
   - accept marks the suggestion `accepted`
   - reject marks the suggestion `ignored`
   - `confirmed_tag_id` is returned in responses but is not automatically set by AI suggestion acceptance

The Supervisor should fit after mapper suggestion generation and before human acceptance. It reviews mapper output. It is not a mapper, not a replacement candidate generator, and not an XBRL writer.

## Integration Principle

Supervisor review should be persisted as advisory metadata attached to an AI suggestion or extracted row. It must not directly mutate the final mapping.

Required boundary:

- Supervisor can classify a mapper suggestion as safe, review-needed, high-risk, unsupported, ambiguous, or omission-suspected.
- Supervisor cannot accept a mapping.
- Supervisor cannot set `confirmed_tag_id`.
- Supervisor cannot modify `extracted_data_items.template_field_id`.
- Human review remains final.

## Proposed Architecture

Attach Supervisor reviews in three layers:

1. Per AI suggestion:
   - Primary integration point.
   - Review references `llm_mapping_suggestions.id`.
   - Used when Qwen selected a template field or produced a no-safe/rejected result.

2. Per extracted row:
   - Secondary integration point.
   - Review references `extracted_data_items.id`.
   - Supports omission detection where the mapper rejected or omitted a numeric fact-like row.

3. Per job batch:
   - Operational grouping only.
   - A batch run should enqueue or execute one row/suggestion review per selected item.
   - Batch status can be derived from review row counts or stored separately in a future job-status field if needed.

Supervisor review records should be independent from confirmed mapping. They should remain valid historical review metadata even if a user later accepts, rejects, or manually changes a row.

## Proposed DB Schema Design

Future migration: `012_add_mapping_supervisor_reviews.sql`.

Proposed table: `mapping_supervisor_reviews`

Fields:

| Field | Type | Notes |
| --- | --- | --- |
| `id` | `VARCHAR(36) PRIMARY KEY` | UUID string, matching existing app style. |
| `user_id` | `INTEGER NULL REFERENCES users(id) ON DELETE SET NULL` | Mirrors current ownership model through `filing_jobs.user_id`; useful for audit and filtering. |
| `organization_id` | `INTEGER NULL` | Future placeholder only if organization support is added; omit from first migration unless orgs exist. |
| `job_id` | `INTEGER NOT NULL REFERENCES filing_jobs(id) ON DELETE CASCADE` | Job-level ownership and batch lookup. |
| `extracted_data_item_id` | `VARCHAR(36) NOT NULL REFERENCES extracted_data_items(id) ON DELETE CASCADE` | Row under review. |
| `ai_suggestion_id` | `VARCHAR(36) NULL REFERENCES llm_mapping_suggestions(id) ON DELETE SET NULL` | Present for mapper suggestion reviews; null for omission-only row reviews. |
| `mapper_selected_template_field_id` | `VARCHAR(200) NULL` | Snapshot of mapper output at review time. |
| `mapper_selected_qname` | `VARCHAR(300) NULL` | Snapshot of selected qname/template id if available. |
| `mapper_confidence` | `DOUBLE PRECISION NULL` | Snapshot of mapper confidence. |
| `mapper_status` | `VARCHAR(40) NULL` | Suggested/rejected/no-prediction style status. |
| `supervisor_decision` | `VARCHAR(40) NULL` | `agree`, `disagree`, `needs_human_review`. |
| `supervisor_risk_level` | `VARCHAR(20) NULL` | `low`, `medium`, `high`. |
| `supervisor_recommended_action` | `VARCHAR(50) NULL` | `accept`, `reject`, `keep_for_human_review`, `request_better_candidate`. |
| `supervisor_safe_to_accept` | `BOOLEAN NOT NULL DEFAULT FALSE` | Advisory only. |
| `calibrated_safe_to_accept` | `BOOLEAN NOT NULL DEFAULT FALSE` | Advisory calibrated flag; never drives acceptance. |
| `supervisor_confidence_adjustment` | `VARCHAR(20) NULL` | `increase`, `keep`, `decrease`. |
| `supervisor_issues_json` | `TEXT NULL` | JSON array of typed issues. |
| `supervisor_reason` | `TEXT NULL` | Short human-readable reason. |
| `supervisor_model_provider` | `VARCHAR(50) NULL` | Example: `hf`. |
| `supervisor_model_id` | `VARCHAR(200) NULL` | Redacted only in user-facing API if needed. |
| `supervisor_prompt_version` | `VARCHAR(80) NOT NULL` | Example: `17d_c_v1`. |
| `supervisor_schema_version` | `VARCHAR(80) NOT NULL` | Example: `supervisor_review_v1`. |
| `supervisor_payload_hash` | `VARCHAR(64) NOT NULL` | SHA-256 of canonical sanitized payload. |
| `supervisor_response_hash` | `VARCHAR(64) NULL` | SHA-256 of canonical normalized response. |
| `review_input_signature_hash` | `VARCHAR(64) NOT NULL` | Hash of row/suggestion/candidate version fields to detect stale review. |
| `status` | `VARCHAR(20) NOT NULL DEFAULT 'pending'` | `pending`, `running`, `completed`, `failed`, `skipped`. |
| `error_type` | `VARCHAR(80) NULL` | Provider/config/validation/rate-limit category. |
| `error_message_sanitized` | `TEXT NULL` | Sanitized, token-redacted error. |
| `created_at` | `TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP` | Creation timestamp. |
| `updated_at` | `TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP` | Updated by service. |

Recommended indexes:

- `idx_mapping_supervisor_reviews_job_status (job_id, status)`
- `idx_mapping_supervisor_reviews_item (extracted_data_item_id)`
- `idx_mapping_supervisor_reviews_suggestion (ai_suggestion_id)`
- `idx_mapping_supervisor_reviews_safe (job_id, supervisor_safe_to_accept, calibrated_safe_to_accept)`
- `idx_mapping_supervisor_reviews_risk (job_id, supervisor_risk_level)`
- unique partial idempotency index on active/latest review:
  - `(job_id, extracted_data_item_id, ai_suggestion_id, review_input_signature_hash, supervisor_prompt_version, supervisor_schema_version)`

Storage policy:

- Store payload hashes by default, not raw prompts or raw payloads.
- Do not store auditor XML, parsed XML facts, benchmark gold answers, or evaluation labels.
- Raw payload storage should not be part of the first production migration.
- If raw payload storage is later approved for debugging, it must be redacted, encrypted or access-controlled, and have a retention policy.

## Proposed Backend Service Design

Add a future service module:

- `services/supervisor_production_review.py`

Responsibilities:

1. Load an owned job, extracted row, and optional `LLMMappingSuggestion`.
2. Build a production Supervisor payload from:
   - extracted row context
   - mapper suggestion snapshot
   - candidate concepts
   - retrieved concept cards
   - few-shot examples
   - do-not-confuse notes
3. Assert payload safety before any live call.
4. Call the Supervisor LLM using only `SUPERVISOR_LLM_*` configuration.
5. Validate strict JSON using the existing Supervisor schema validator.
6. Apply deterministic post-validation guardrails.
7. Compute advisory calibrated safe accept where the evidence is exact/near-alias and same-family.
8. Persist status and result into `mapping_supervisor_reviews`.
9. Return serialized advisory review metadata.

Explicit non-responsibilities:

- Do not mutate `extracted_data_items.template_field_id`.
- Do not set `confirmed_tag_id`.
- Do not mark suggestions accepted.
- Do not generate XBRL.
- Do not run Arelle.

Candidate function sketch:

```python
async def build_production_supervisor_payload(
    *,
    item: ExtractedDataItem,
    suggestion: LLMMappingSuggestion | None,
    candidate_concepts: Sequence[Mapping[str, Any]],
    concept_cards: Sequence[Mapping[str, Any]],
    fewshot_examples: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    ...

async def run_supervisor_review_for_suggestion(
    *,
    db: AsyncSession,
    job_id: int,
    suggestion_id: str,
    current_user: User,
    mode: Literal["mock", "live"],
) -> MappingSupervisorReview:
    ...

async def run_supervisor_review_batch_for_job(
    *,
    db: AsyncSession,
    job_id: int,
    current_user: User,
    mode: Literal["mock", "live"],
    only_pending: bool = True,
) -> dict[str, Any]:
    ...
```

Existing code to reuse:

- `services.supervisor_mapping_review.build_supervisor_review_payload`
- `services.supervisor_mapping_review.assert_supervisor_payload_is_leakage_safe`
- `services.supervisor_mapping_review.validate_supervisor_response`
- `services.supervisor_llm_client.SupervisorLLMClient`
- #17D-B-hotfix-6 threshold classification logic should be ported into service code only after tests are added.

## Proposed Background Execution Design

First implementation should use mock mode only.

Phased task design:

1. `#17D-C-C`: API can run one mock Supervisor review synchronously for one suggestion.
2. `#17D-C-C` or `#17D-C-E`: add Celery task only for batch review.
3. Suggested Celery task name:
   - `app.tasks.run_supervisor_review_batch_task`
4. Suggested queue:
   - `supervisor_review`
5. Batch behavior:
   - idempotent by `review_input_signature_hash`
   - skip completed reviews with unchanged suggestion/row/candidate signature
   - persist `failed` or `skipped` rows without rolling back successful rows
   - expose counts by status/risk/safe flag

Do not add a new background task in #17D-C-A.

## Proposed API Contract

Place endpoints under existing filing ownership boundaries.

### List reviews

`GET /api/v1/filings/jobs/{job_id}/supervisor-reviews`

Query filters:

- `status`
- `risk_level`
- `safe_to_accept`
- `calibrated_safe_to_accept`
- `ai_suggestion_id`
- `extracted_data_item_id`

Response:

```json
{
  "job_id": 31,
  "reviews": [],
  "counts": {
    "total": 0,
    "pending": 0,
    "running": 0,
    "completed": 0,
    "failed": 0,
    "safe_to_accept": 0,
    "calibrated_safe_to_accept": 0,
    "needs_human_review": 0,
    "high_risk": 0
  }
}
```

### Get one review

`GET /api/v1/filings/supervisor-reviews/{review_id}`

Response fields:

- `id`
- `job_id`
- `extracted_data_item_id`
- `ai_suggestion_id`
- `status`
- `review_decision`
- `risk_level`
- `recommended_action`
- `safe_to_accept`
- `calibrated_safe_to_accept`
- `issues`
- `reason`
- `confidence_adjustment`
- `model_provider`
- `model_id`
- `prompt_version`
- `schema_version`
- `payload_hash`
- `response_hash`
- `created_at`
- `updated_at`
- `stale`

### Run one review

`POST /api/v1/filings/jobs/{job_id}/supervisor-reviews/run`

Request:

```json
{
  "ai_suggestion_id": "suggestion-uuid",
  "extracted_data_item_id": "item-uuid",
  "mode": "mock",
  "force_refresh": false
}
```

Rules:

- `mode=mock` only until live mode is separately approved.
- `ai_suggestion_id` is preferred.
- `extracted_data_item_id` supports omission-only review.
- Do not mutate final mapping.

### Run batch review

`POST /api/v1/filings/jobs/{job_id}/supervisor-reviews/run-batch`

Request:

```json
{
  "mode": "mock",
  "only_pending": true,
  "include_rejected_or_no_prediction": true,
  "force_refresh": false
}
```

Response:

```json
{
  "job_id": 31,
  "queued": false,
  "task_id": null,
  "status": "completed",
  "counts": {
    "created": 0,
    "skipped": 0,
    "completed": 0,
    "failed": 0
  }
}
```

Live batch should be behind a feature flag and initially admin-only or explicitly approved.

## Proposed UI Design

Supervisor UI should be display-only in the first production integration.

Add a Supervisor badge beside each AI suggestion:

- `Safe`
- `Review needed`
- `High risk`
- `Omission suspected`
- `Unsupported candidate`
- `Ambiguous label`

Display behavior:

- Show badge near existing AI suggestion confidence/status chips.
- Show `safe_to_accept` and `calibrated_safe_to_accept` as advisory labels only.
- Show Supervisor reason and issue list in collapsible details.
- Show failed/skipped review status without blocking the existing accept/reject controls.
- Do not hide risky suggestions; surface them clearly.
- Existing Accept and Reject buttons remain the only mapping action controls.
- The Accept button must not auto-click, auto-enable, or auto-promote based on Supervisor output.

Suggested copy:

- Safe: `Supervisor: Safe to accept after human confirmation`
- Review needed: `Supervisor: Human review needed`
- High risk: `Supervisor: High risk`
- Omission suspected: `Supervisor: Possible mapper omission`

## Safety Boundaries

Allowed production Supervisor payload:

- extracted row label/value/statement/page context
- mapper suggestion selected template/qname/confidence/reason
- candidate concepts already generated for mapping
- concept cards
- few-shot examples approved for production use
- do-not-confuse notes
- non-sensitive diagnostics

Forbidden production Supervisor payload:

- auditor XML
- parsed XML facts
- benchmark gold answers
- target correct qnames
- target correct template fields
- evaluation labels
- local scoring fields
- raw benchmark report rows

Result boundaries:

- Supervisor result cannot directly mutate final mapping.
- Supervisor result cannot set `confirmed_tag_id`.
- Supervisor result cannot mark an AI suggestion accepted.
- Supervisor result cannot generate XBRL.
- Supervisor result cannot run validation/Arelle.
- Human review remains final.
- First production version is status/review-only.

## Rollout Plan

### #17D-C-A

Design spec only.

Deliverables:

- design document
- JSON report
- Markdown report
- tracker updates

### #17D-C-B

Backend persistence schema, SQL migration, SQLAlchemy model, serializers, and migration tests only.

No live LLM call.

### #17D-C-C

Backend service and API with mock Supervisor mode only.

No live LLM call.

### #17D-C-D

UI display integration using mock/persisted Supervisor results only.

No auto-apply.

### #17D-C-E

Live Supervisor single-row run and optional batch job behind admin or feature flag.

No auto-apply.

### #17D-C-F

Production monitoring and audit logs:

- review counts
- failed/skipped counts
- rate limits
- model/prompt/schema versions
- stale review counts

No auto-apply in any phase unless explicitly approved in a later feature.

## Test Plan

Backend persistence:

- migration creates `mapping_supervisor_reviews`
- migration is idempotent
- SQLAlchemy model matches migration
- cascade behavior deletes reviews with jobs/items
- `ai_suggestion_id` can be null for omission-only review

Payload safety:

- production payload contains no auditor XML
- production payload contains no parsed XML facts
- production payload contains no gold answers
- production payload contains no evaluation labels
- payload hashes are stored; raw payload is not stored by default

Service behavior:

- mock review persists completed review
- failed provider/config call persists failed or skipped review safely
- deterministic guardrails force unsafe `safe_to_accept` false
- calibrated safe accept is advisory and does not mutate mapping
- stale review detected when suggestion selection or row context changes

Mapping safety:

- Supervisor review does not update `extracted_data_items.template_field_id`
- Supervisor review does not set `confirmed_tag_id`
- Supervisor review does not mark suggestions accepted
- Accept/reject suggestion behavior remains unchanged

API/security:

- user can list/run reviews only for owned jobs
- cross-user job returns 404
- admin policy for live/batch mode is enforced if selected
- status/risk/safe filters work
- idempotent batch does not duplicate reviews

Frontend:

- badge renders for safe/review-needed/high-risk/omission/unsupported/ambiguous states
- reason and issues render in collapsed details
- safe badge does not trigger accept
- risky review does not hide suggestion
- existing accept/reject tests still pass

Background:

- batch task is idempotent
- partial failures persist row-level failure
- rate-limit result does not erase completed reviews

## Risks And Open Questions

Cost and rate limits:

- Batch review could multiply provider calls by suggestion count.
- Initial live mode should be manual, bounded, and feature-flagged.

Latency:

- Single review can be synchronous only in mock mode.
- Live batch should use Celery.

Payload privacy:

- Hash payloads by default.
- Raw payload storage needs separate approval.

Staleness:

- Reviews become stale when a suggestion, row label/value, candidate set, prompt version, or schema version changes.
- API should expose `stale=true` rather than silently reusing old review.

Versioning:

- Store prompt version, schema version, model provider, and model id on every review.

Live execution control:

- Open question: should normal users be allowed to run single live reviews, or should live execution be admin-only initially?
- Recommendation: mock mode first; live mode initially admin or feature-flag only.

Raw response storage:

- Open question: store raw response previews for support?
- Recommendation: store normalized response hash and sanitized error only in first version.

## Recommended Next Feature

#17D-C-B: Backend persistence schema, SQLAlchemy model, serializer helpers, and migration tests only. No live LLM call, no endpoint behavior change, no UI change, and no auto-apply.

