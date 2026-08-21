# job70_candidate_scope_19c_hotfix_1

Analysis status: **PASS**

This is a deterministic, read-only Job 70 analysis. It made zero provider calls, did not publish a mapping artifact, and did not mutate the database or source document.

## Scope summary

- Eligible rows audited: 25
- Template 420000 rows: 10
- Rows with explicit semantic scope limitations: 9
- Abstract/nonselectable candidate exposure: 0
- Candidate scope remains constrained to canonical classified template membership; no cross-template fallback was added.
- Every JSON row includes `complete_candidate_scope` with the complete pre-Top-K pool, metadata, full score breakdown, and exclusion reason.
