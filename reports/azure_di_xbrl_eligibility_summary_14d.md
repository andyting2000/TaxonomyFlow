# Azure DI XBRL Eligibility Summary - Feature #14D

## Summary

- Total review items: 53
- Simulated approved: 17
- XBRL eligible: 17
- XBRL blocked: 36
- Deferred: 17
- Alias enrichment needed: 0
- Metadata enrichment needed: 0
- Manual taxonomy mapping needed: 15
- Recommended next feature: Feature #14D - Reviewed mapping quality evaluation against reference XML, no DB mutation.

## Why XBRL Generation Is Still Not Allowed

- Every approval is simulated_only=true and human_approved=false.
- No final production mapping approval exists.
- Ambiguous, no-safe, blocked, and default confirmation-required records remain excluded.
- This feature does not generate XBRL or run Arelle validation.

## Top XBRL Blockers

- simulate_confirm_medium_not_enabled: 17
- ambiguous_multiple_suggestions: 15
- section_family_mismatch: 2
- generic_or_weak_label: 1
- blocker:row_type_or_concept_type_mismatch: 1
- concept_type_mismatch_blocks_xbrl: 1
- row_type_or_concept_type_mismatch: 1
- confirmation_candidate_below_medium_confidence: 1
