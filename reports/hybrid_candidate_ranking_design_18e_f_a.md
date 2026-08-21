# Hybrid Candidate Ranking Design #18E-F-A

## Why deterministic-only stalled
Deterministic single-qname mapping stalled around the 40-45% useful coverage range once risky expansions were tightened.

## New target
Candidate coverage: provide one or more ranked plausible taxonomy candidates for at least 80% of rows, with evidence and risk, without final mapping automation.

## Candidate sources
- Current #18E-B-3 deterministic mapper output
- Statement-specific dictionary candidates
- Local taxonomy concept-label lexical search from mpers_templates.json or optional metadata
- Optional cached Qwen suggestions when present locally; no Qwen call is made

## Evidence scoring
- Normalized label similarity
- Statement-family compatibility
- Section context and row-role agreement
- Template, note-link, format-memory, dictionary, and row-order source evidence
- Prior local exact-match evidence from existing offline evaluation reports
- Source reliability weights from current deterministic evidence quality

## Risk scoring
- Note-detail, movement, and reconciliation boundaries
- Generic total/subtotal/component labels
- Balance-sheet versus cash-flow ambiguity
- Tax expense versus tax payable/deferred tax ambiguity
- Receivable/payable detail ambiguity
- Borrowings/loans weak-label ambiguity
- Low context confidence
- Multiple candidates close in score

## Review boundary
Every candidate is review evidence only. Human or future Supervisor review remains final.

## No-auto-apply boundary
The prototype never writes confirmed_tag_id, never auto-accepts, never auto-rejects, and never marks safe_for_auto_apply true.

## Future Qwen/Supervisor role
Qwen and Supervisor may later score or review ranked candidates, but this feature makes no LLM calls and only supports optional cached local suggestions as another candidate source.

## Production phases
- Offline ranking and metrics prototype
- Threshold/risk calibration
- Backend advisory integration design behind feature flag
- UI display of ranked advisory candidates
- Supervisor/human review workflow, still no auto-apply without separate approval

## Recommended next feature
`Feature #18E-F-A-hotfix-2 - Tighten risk scoring and candidate filters` - Candidate coverage is usable but high/critical risk candidates dominate the review burden.
