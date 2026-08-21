# Supervisor Production Orchestration Design

Status: **scaffold complete, rollout not recommended yet**

## Architecture

The orchestration layer is read-only and disabled by default. It joins existing mapping suggestions, latest Supervisor reviews, and separate guided revisions to derive local eligibility and workflow state.

No new persistence table or background worker was added. Existing manual endpoints remain the only execution paths for single review, confirmed bounded batch review, and single guided remapping.

## HTTP Contract

- `GET /api/v1/filings/jobs/{job_id}/supervisor-orchestration/capabilities`
- `GET /api/v1/filings/jobs/{job_id}/supervisor-orchestration/plan`

Capabilities are visible for an owned job while disabled. The plan endpoint fails closed when disabled, unauthorized, or configured for automatic review/remapping.

## Queue Contract

The job response includes eligibility, blocked/reviewed/remapping/revision counts and a safety summary. Each item carries row and suggestion identity, local reasons, priority, grouped workflow state, existing review/revision IDs, attempts used, manual recommendation, and provenance.

Every item is forced to `requires_human_review=true` and `safe_for_auto_apply=false`.

## Measured Queue Volume

Read-only planning over jobs 59-61 classified 114 of 150 suggestions as eligible (`76%`). The dominant signals were no-safe-candidate status and confidence below `0.85`.

This is excessive for a bounded manual queue. Recommended next: `18F-G-B-hotfix-1` eligibility and priority calibration before `18F-G-C`.
