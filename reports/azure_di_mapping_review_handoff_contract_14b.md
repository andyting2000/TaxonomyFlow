# Azure DI Mapping Review Handoff Contract - Feature #14B

## Summary

- Contract status: future_schema_only_no_approved_mappings
- Reviewed mapping records produced: 0

## Reviewed Mapping Fields

- reviewed_mapping_id: Stable reviewed mapping identifier.
- mapping_input_id: Trace to #13Y/#14A handoff mapping input.
- source_candidate_id: Trace to Azure DI normalized extraction candidate.
- case_id: Source case identifier.
- final_concept_qname: Reviewer-approved concept qname.
- final_concept_label: Reviewer-approved concept label.
- final_concept_type: Reviewer-approved concept type.
- final_label: Reviewer-approved source label.
- final_value: Reviewer-approved current value.
- final_previous_value: Reviewer-approved prior value.
- final_text: Reviewer-approved narrative text.
- final_row_type: Reviewer-approved row type.
- final_statement_section: Reviewer-approved statement section.
- reviewer_decision: Structured reviewer decision.
- reviewer_notes: Human notes supporting the decision.
- reviewed_by: Reviewer identifier.
- reviewed_at: Review timestamp.
- approval_status: approved, rejected, context_only, deferred, or needs_more_information.
- requires_confirmation: Whether source gate required confirmation.
- source_suggestion_id: Trace to the selected source suggestion.
- evidence: Source evidence used by reviewer.
- provenance: Azure DI and mapping provenance.
- audit_trail: Full review audit trail.
- xbrl_eligible: True only after reviewer approval and eligibility checks.
- xbrl_blockers: Reasons a reviewed mapping cannot be used for XBRL.

## Eligibility Rules

- Only reviewer-approved mappings can become xbrl_eligible.
- High-confidence suggestions still require approval.
- Suggest-only mappings require confirmation.
- Ambiguous mappings require explicit concept choice.
- No-safe mappings require manual taxonomy mapping or enrichment before approval.
- Rejected, context-only, and deferred mappings are not XBRL eligible.

## Limitations

- This contract defines a future handoff shape only.
- No reviewed mapping record is produced or approved by #14B.
- No XBRL eligibility is granted by this report.
