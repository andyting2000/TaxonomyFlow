# Ranked Candidate Frontend Panel 18F-E

The internal `RankedCandidateTestPanel` is placed in `ReviewWorkspace` beneath the existing gated AI Mapping Suggestions area. It is hidden unless `VITE_SHOW_RANKED_CANDIDATE_TEST_PANEL=true`; the template default is false.

The panel consumes only the ranked-candidate capabilities endpoint and the dry-run run endpoint. It renders backend capability metadata, dry-run controls, response summaries, safety counters, and candidate evidence as read-only advisory content.

Recommended next feature: #18F-F - End-to-end dry-run smoke test and UX hardening.
