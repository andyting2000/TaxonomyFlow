# Ranked Candidate Frontend Panel Safety 18F-E

The panel is advisory-only and dry-run-only. It has no Apply, Accept, Confirm, Save Mapping, or Auto-map control. It does not call persistence, AI suggestion, mapping, or `confirmed_tag_id` mutation endpoints.

Returned candidate rows are blocked from rendering if any mutation safety counter is nonzero, if a candidate claims `safe_for_auto_apply=true`, or if a candidate does not require human review.
