# Azure DI XBRL Eligibility Summary - Feature #14C

## Summary

- Total review items: 53
- Simulated approved: 8
- XBRL eligible: 8
- XBRL blocked: 45
- Deferred: 6
- Alias enrichment needed: 24
- Metadata enrichment needed: 0
- Manual taxonomy mapping needed: 12
- Recommended next feature: Feature #14D - Concept metadata enrichment v2 if simulation approves too few mappings.

## Why XBRL Generation Is Still Not Allowed

- Every approval is simulated_only=true and human_approved=false.
- No final production mapping approval exists.
- Ambiguous, no-safe, blocked, and default confirmation-required records remain excluded.
- This feature does not generate XBRL or run Arelle validation.

## Top XBRL Blockers

- alias_enrichment_needed: 24
- ambiguous_multiple_suggestions: 12
- simulate_confirm_medium_not_enabled: 6
- confirmation_candidate_below_medium_confidence: 2
- generic_or_weak_label: 2
- blocker:row_type_or_concept_type_mismatch: 1
- concept_type_mismatch_blocks_xbrl: 1
- row_type_or_concept_type_mismatch: 1
