# Azure DI Review Simulation Policy - Feature #14C

## Strategy

- Default behavior: Approve only ready_for_review_approval items with high/strong-medium compatible top suggestions.
- Active policy: {'approve_ready_only': True, 'simulate_confirm_medium': False, 'simulate_choose_top_ambiguous': False, 'strict': True}

## Optional Flags

- approve_ready_only: Default true; limits simulated approvals to ready_for_review_approval items unless explicit scenarios are enabled.
- simulate_confirm_medium: When enabled, medium-or-better needs_confirmation items may be simulated as approved.
- simulate_choose_top_ambiguous: When enabled, ambiguous items may choose the top suggestion for simulation only.
- strict: Default true; blocks low-confidence numeric and type-mismatch approvals.

## Simulated XBRL Eligibility Rules

- Simulated approvals must have a selected concept and compatible row/concept evidence.
- Default simulation excludes ambiguous, no-safe, blocked, context-only, and low-confidence risky records.
- Eligible handoff items remain simulated_only=true and human_approved=false.

## Blocked Rules

- No real human approval is recorded.
- No production mapping approval is produced.
- No XBRL generation is allowed from #14C outputs.
- No Arelle validation is run.
