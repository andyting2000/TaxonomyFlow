# Supervisor Internal Reviewer Rollout

Feature: `18F-G-E`

This profile is for a controlled internal environment. It is not a general-user
production rollout and does not authorize automatic mapping decisions.

## Access Model

Supervisor rollout authorization is:

```text
feature enabled
AND ordinary filing ownership check passes
AND (user is admin OR user ID is explicitly allowlisted)
```

`SUPERVISOR_ORCHESTRATION_ALLOWED_USER_IDS` is a comma-separated list of
positive user IDs. Empty permits admins only. Invalid entries fail closed for
all users. The IDs are not returned by capability APIs; only authorization
source and allowlist count are exposed.

The allowlist grants no admin role and no access to another user's jobs.
Existing `filing_jobs.user_id` ownership remains authoritative.

## Controlled Profile

Use environment-specific configuration. Do not commit actual reviewer IDs or
provider credentials.

```dotenv
SUPERVISOR_ORCHESTRATION_ENABLED=true
SUPERVISOR_ORCHESTRATION_DEFAULT_MODE=manual
SUPERVISOR_ORCHESTRATION_AUTO_ELIGIBILITY=true
SUPERVISOR_ORCHESTRATION_AUTO_REVIEW=false
SUPERVISOR_ORCHESTRATION_AUTO_REMAP=false
SUPERVISOR_ORCHESTRATION_ADMIN_ONLY=true
SUPERVISOR_ORCHESTRATION_ALLOWED_USER_IDS=<explicit-internal-reviewer-user-ids>
SUPERVISOR_ORCHESTRATION_MAX_BATCH_SIZE=5
SUPERVISOR_ORCHESTRATION_MAX_REMAP_RETRIES=1
SUPERVISOR_ORCHESTRATION_MAX_CONCURRENT_LIVE_CALLS=1
SUPERVISOR_ORCHESTRATION_PER_ROW_TIMEOUT_SECONDS=120

SUPERVISOR_PRODUCTION_LIVE_ENABLED=true
SUPERVISOR_PRODUCTION_LIVE_ADMIN_ONLY=true
SUPERVISOR_PRODUCTION_LIVE_MAX_BATCH_SIZE=5

SUPERVISOR_MAPPER_FEEDBACK_ENABLED=true
SUPERVISOR_MAPPER_FEEDBACK_AUTO_RUN=false
SUPERVISOR_MAPPER_FEEDBACK_MAX_RETRIES=1
SUPERVISOR_MAPPER_FEEDBACK_ADMIN_ONLY=true

VITE_SHOW_SUPERVISOR_ORCHESTRATION_QUEUE=true
VITE_SHOW_SUPERVISOR_LIVE_CONTROLS=true
VITE_SHOW_SUPERVISOR_MAPPER_FEEDBACK=true
VITE_SHOW_SUPERVISOR_MOCK_CONTROLS=false
```

Repository examples remain disabled and restrictive. Frontend flags control
visibility only; backend gates and ownership checks are security controls.

## Execution Limits

- Live review requires explicit `mode=live`.
- Guided remapping requires an explicit endpoint call and confirmation.
- Initial rollout batch maximum is 5; reviewers should begin with single rows.
- Live provider calls are bounded to one concurrent call per API process in the
  Phase 1 profile.
- Existing batch review execution is sequential.
- Provider timeout is 120 seconds.
- Provider transport retries remain bounded by `SUPERVISOR_LLM_MAX_RETRIES`.
- Structured-response repair is bounded by
  `SUPERVISOR_LLM_MAX_REPAIR_RETRIES`.
- Guided correction is limited to one durable attempt.
- Suggestion row locks serialize review and correction actions; persisted
  review reuse, terminal-state checks, and the unique revision-attempt index
  block duplicate/stale actions.

The concurrency bound is process-local, not distributed. Phase 1 should use one
API process or an external provider/account rate limit. Do not multiply API
workers without recalculating the effective provider-call ceiling.

## Observability And Audit

Use:

```powershell
python -B scripts\report_supervisor_internal_rollout_status.py --job-ids 59,60,61
```

The helper is read-only and makes no provider calls. It joins existing
suggestions, Supervisor reviews, guided revisions, and owned jobs. Raw prompts,
raw responses, provider tokens, auditor XML, parsed XBRL facts, benchmark gold,
target qnames, and evaluation labels are excluded.

Monitor:

- API access-log count for `supervisor_orchestration_plan_requested`
- plan eligible, high, medium, and executable counts
- live review attempts, completed, failed, invalid responses, latency, and
  agree/disagree/needs-human-review decisions
- guided remap attempts, completed, failed, no-safe, changed-qname,
  unchanged-qname, revision, and retry-blocked counts
- eventual accepted, ignored, and pending human outcomes
- automatic review, automatic remap, auto-apply, confirmed-tag mutation, and
  final-mapping mutation counters

Expected safety counters are always zero. Reviewer outcomes are operational
evidence, not unquestioned gold labels.

Existing review persistence records user/job/row/suggestion/review IDs,
provider/model/prompt/schema versions, decision, risk, recommendation, hashes,
errors, attempts, and timestamps. Existing revision persistence records
job/suggestion/review/revision IDs, original/revised qnames, attempt, model,
status, human-review requirement, safety, and timestamps. The read-only export
resolves a revision actor from its linked review, then from the owned job, and
labels that provenance source.

## Reviewer Guidance

- `Supervisor eligible` means the risk/context signals justify a second
  advisory review. It does not mean the mapping is wrong.
- `High priority` means review first. It does not mean definitely wrong.
- Supervisor decisions and guided revisions are advisory.
- Every revised mapping still requires human review.
- Never accept a mapping solely because it looks safe or has high confidence.
- Use the ordinary manual review workflow when a provider is unavailable.

## Provider Failure Runbook

Supervisor unavailable or timed out:

1. Preserve the original suggestion.
2. Do not run correction or mutate final mapping.
3. Confirm a failed review audit record exists.
4. Continue manual review.
5. Retry only through a later explicit action after provider recovery.

Mapper correction unavailable or timed out:

1. Preserve the original suggestion and completed Supervisor review.
2. Confirm the failed revision is non-executable and human-review required.
3. Do not change `confirmed_tag_id` or final mapping.
4. Continue manual review.

Invalid structured response:

1. Treat the review as failed/unsafe.
2. Do not produce an executable mapping.
3. Preserve human review.
4. Investigate sanitized error type and model/schema versions; do not inspect or
   export auditor XML or benchmark labels.

## Kill Switch And Rollback

Backend shutdown order:

1. `SUPERVISOR_PRODUCTION_LIVE_ENABLED=false`
2. `SUPERVISOR_MAPPER_FEEDBACK_ENABLED=false`
3. `SUPERVISOR_ORCHESTRATION_ENABLED=false`
4. Restart/reload the externally managed backend using the normal deployment
   procedure.
5. Set `VITE_SHOW_SUPERVISOR_ORCHESTRATION_QUEUE=false`,
   `VITE_SHOW_SUPERVISOR_LIVE_CONTROLS=false`, and
   `VITE_SHOW_SUPERVISOR_MAPPER_FEEDBACK=false` on the next frontend build.

Backend disablement is the safety action; frontend hiding is not. Rollback
preserves suggestions, reviews, revisions, and human decisions and does not
affect the ordinary Review Workspace.

## Rollout Checklist

Before enablement:

- Verify runtime revision and one-listener provenance.
- Verify migrations through `013` are applied.
- Verify current frontend build.
- Configure one or two explicit internal reviewer IDs.
- Verify owned-job and cross-owner authorization.
- Keep auto review and auto remap false.
- Confirm batch maximum 5 and correction maximum 1.
- Configure provider credentials and timeout without logging secrets.
- Verify backend kill switches.
- Verify audit export and zero safety counters.
- Record rollback owner and procedure.

After enablement:

- Check capabilities as one authorized reviewer.
- Confirm one non-allowlisted owner receives 403.
- Confirm an allowlisted reviewer receives 404 for another user's job.
- Request one read-only plan and verify zero provider calls.
- Run one explicit single-row live review.
- Optionally run one naturally eligible guided remap.
- Verify persisted audit events and queue refresh.
- Verify no `confirmed_tag_id` or final mapping mutation.

## Cohort And Quality Gates

Phase 1: one or two internal reviewers, existing `REVIEW` filings, single-row
actions first, no large batch execution. Observe the first 25 to 50 live
reviews or one to two weeks before considering expansion.

Do not expand unless:

- cross-user access incidents = 0
- duplicate revision incidents = 0
- automatic mapping mutations = 0
- confirmed-tag automation = 0
- structured-response success >= 98%
- no persistent stale-state reconciliation defect
- no unrecoverable provider failure

Broader internal expansion requires a separately approved feature. General-user
production rollout and all automatic acceptance/apply behavior remain out of
scope.
