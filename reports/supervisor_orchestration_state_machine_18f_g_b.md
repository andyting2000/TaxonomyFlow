# Supervisor Orchestration State Machine

The state model separates mapping, Supervisor eligibility/execution, remapping eligibility/execution, and human decision.

The valid path requires an explicit manual event before Supervisor execution, remapping execution, and final human acceptance/rejection.

Hard-invalid transitions include automatic remapping after a completed review, automatic acceptance after a revision, setting `confirmed_tag_id` from pending human review, a second mapper call after retry exhaustion, provider execution for blocked reviews, and remapping after a terminal human decision.

Failures are isolated: the initial suggestion stays available, revisions remain separate, and the filing stays in `REVIEW`.
