# Manual Review Queue Data Contract - Feature #13U

## Storage Strategy
- Recommended first step: JSON report-only flow
- Do not extend production extraction rows until report-based handoff behavior is stable.

## Proposed Entities
- `manual_review_batch`: Groups one generated review queue and its source reports.
- `manual_review_item`: Represents one candidate or context row requiring reviewer visibility.
- `conflict_group`: Surfaces related candidates where automatic mapping must be blocked until reviewed.
- `reviewer_decision`: Records user decisions, corrections, and mapping eligibility changes.
- `mapping_handoff_item`: Defines the reviewed candidate payload allowed to enter future mapping candidate generation.

## Validation Rules
- Every review item must belong to exactly one review batch.
- Conflict-group decisions must preserve all candidate options and record any selected candidate.
- Approved mapping handoff items must include final label, row type, section, provenance, and page number.
- Suppressed, downgraded metadata/date/year, blocked, and unresolved conflict candidates must not be auto-mapped.
- Reviewer corrections must be stored as decisions, not by overwriting source extraction evidence.

## Audit Trail Requirements
- Record source report paths and hashes when available.
- Record created_by/reviewed_by and timestamps for every decision.
- Keep original candidate values alongside corrected values.
- Keep conflict group membership stable across exports.
- Make mapping handoff reproducible from batch, item, group, and decision records.

## Mapping Handoff Contract
- Include original and cleaned candidate identifiers, final reviewed fields, warnings, provenance, and conflict status.
- Exclude suppressed, downgraded metadata/date/year, blocked, and unresolved conflict candidates from automatic mapping.
