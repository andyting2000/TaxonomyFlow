# Azure DI Mapping Review Policy - Feature #14B

## Workflow Statuses

- ready_for_review_approval: High or strong medium suggestions that may be approved only by a human reviewer.
- needs_human_concept_choice: Ambiguous suggestions where a reviewer must choose a concept, reject all, or require policy.
- needs_confirmation: Suggest-only or confirmation-required candidates that cannot proceed without explicit reviewer confirmation.
- needs_alias_or_metadata_enrichment: Weak/no-safe candidates where labels are understandable but aliases or concept metadata are insufficient.
- blocked_from_xbrl: Records with weak evidence, unsafe gates, concept type conflicts, or no safe concept; they must not enter XBRL.
- context_only: Useful review context or notes-only evidence, not a mapped fact.

## Priorities

- critical: Concept type mismatch, blocked_from_xbrl, or material numeric ambiguity/no-safe status.
- high: Ambiguous suggestions, low-confidence numeric facts, subtotal/total uncertainty, or confirmation-required numeric candidates.
- medium: Medium suggestions, suggest-only text blocks, or text-block concept uncertainty.
- low: Context-only records, no-safe narrative context, or alias enrichment candidates with low XBRL impact.

## Required Evidence For Approval

- mapping_input_id and source_candidate_id traceability
- source label/text/value evidence
- chosen concept qname and label
- row type and concept type compatibility
- statement section compatibility or reviewer override rationale
- reviewer identity, timestamp, decision, and notes in a future workflow

## Non-Goals

- No final mapping approval in #14B.
- No DB, API, or UI implementation.
- No XBRL generation or Arelle validation.
- No production semantic matcher call.
- No live provider or model calls.
