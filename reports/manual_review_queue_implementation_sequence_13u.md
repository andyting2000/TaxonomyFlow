# Manual Review Queue Implementation Sequence - Feature #13U

Recommended next feature: Feature #13V - Report-based mapping handoff contract with no DB mutation.

## Staged Roadmap
- `13V-data-contract`: Report-based mapping handoff contract with no DB mutation
- `13W-mapping-v2-sandbox`: Mapping candidate generation v2 sandbox
- `13X-manual-review-db-design`: Manual-review DB schema design before API/UI implementation
- `13Y-manual-review-api`: Manual-review API implementation
- `13Z-manual-review-ui`: Manual-review React queue UI
- `later`: Mapping handoff integration, XBRL sandbox generation, and Arelle validation

## Risks And Mitigations
- reviewer choosing wrong candidate: Require evidence preview, conflict context, and reversible audit decisions.
- blocking too many candidates: Track blocked counts and allow suggest-only review paths before hard rejection.
- allowing too many candidates into mapping: Enforce handoff gates and unresolved-conflict blocks before mapping candidate generation.
- conflict groups delaying mapping: Prioritize critical numeric conflicts and allow case-level progress summaries.
- introducing DB schema too early: Start with report-based handoff before migrations.
- UI complexity: Implement dense MVP queue filters before advanced dashboards.
- mixing benchmark reports with production jobs: Record source type and keep batch import policy explicit.
- missing audit trail: Store reviewer identity, timestamps, original values, corrected values, and decision history.
- mapping before review decisions exist: Block unresolved manual-review and conflict statuses from handoff.

## Future Acceptance Criteria
- Mapping handoff can be regenerated from review batch state.
- No suppressed, blocked, reference/context, or unresolved conflict candidates enter mapping.
- Reviewer decisions are auditable and reversible before production cutover.
- API/UI implementation preserves existing auth and user isolation.
