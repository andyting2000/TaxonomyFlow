# Supervisor Internal Reviewer Runbook

The detailed source runbook is
`docs/supervisor_internal_reviewer_rollout_18f_g_e.md`.

## Enablement

Configure one or two explicit reviewer IDs. Keep manual mode, auto review false,
auto remap false, correction retries at one, batch maximum at five, and live
concurrency at one per API process. Keep mock controls hidden.

Before enablement, verify runtime provenance, migrations through `013`, current
frontend build, ownership isolation, provider timeout, kill switches, audit
export, and zero safety counters.

After enablement, verify:

1. Authorized reviewer capabilities.
2. Non-allowlisted owner receives 403.
3. Cross-owner request receives 404.
4. One read-only plan makes zero provider calls.
5. One explicit single-row live review persists an audit record.
6. One naturally eligible guided remap remains human-review required.
7. Queue refreshes with zero mapping or confirmed-tag mutation.

## Failure

- Supervisor failure: preserve the original suggestion and continue manual
  review.
- Mapper failure: preserve the original suggestion and Supervisor review; keep
  the failed revision non-executable.
- Timeout: no uncontrolled retry or automatic correction.
- Invalid response: fail closed and preserve human review.

## Reviewer Guidance

Eligibility means a second advisory review is justified, not that a mapping is
wrong. High priority means review first, not definitely wrong. Supervisor and
guided-remap outputs are advisory; never accept solely from confidence or a
safe-looking result.

## Rollback

Disable live review, mapper feedback, then orchestration in the backend. Hide
frontend flags on the next build. Preserve all audit history.

Observe 25-50 reviews or one to two weeks. Require zero automatic mapping
mutations, cross-user incidents, and duplicate revisions, plus at least 98%
structured-response success, before considering broader internal access.
