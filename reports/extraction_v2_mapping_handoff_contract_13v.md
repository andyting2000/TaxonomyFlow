# Extraction V2 Mapping Handoff Contract - Feature #13V

## Scope
This is the safe report-based input contract for #13W. It is not taxonomy mapping, semantic matching, XBRL generation, or Arelle validation.

## Allowed Gate Statuses
- `auto_mappable_candidate`
- `suggest_mapping_only`

## Excluded Gate Statuses
- `blocked_from_mapping`
- `manual_review_required`
- `reference_only_or_context`

## Required Fields
- `mapping_input_id`
- `source_candidate_id`
- `case_id`
- `page_number`
- `row_type`
- `label or text`
- `statement_section or warning`
- `gate_status`
- `requires_confirmation`
- `source_provenance`
- `mapping_allowed`
- `audit_trail`

## Downstream #13W Responsibilities
- Consume only handoff_items from this package.
- Preserve requires_confirmation and warning_flags.
- Generate mapping candidates only; do not generate XBRL.
- Do not call semantic matcher for excluded candidates.
- Keep mapping suggestions traceable to mapping_input_id and source_candidate_id.

## Prohibited Downstream Behavior
- Do not treat this as final taxonomy mapping.
- Do not call semantic matcher for candidates outside the handoff package.
- Do not generate XBRL or run Arelle from this contract alone.
- Do not mutate DB from report-based handoff output.
- Do not auto-map suggest-only candidates without confirmation metadata.

## Recommended Next Feature
Feature #13W - Mapping candidate generation v2 with conservative readiness gates.
