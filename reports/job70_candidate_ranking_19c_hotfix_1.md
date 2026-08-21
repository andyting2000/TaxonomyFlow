# job70_candidate_ranking_19c_hotfix_1

Analysis status: **PASS**

This is a deterministic, read-only Job 70 analysis. It made zero provider calls, did not publish a mapping artifact, and did not mutate the database or source document.

## Ranking summary

- Before decisions: `{"abstain": 8, "ambiguous": 15, "mapped": 2, "structural_only": 51}`
- After decisions: `{"abstain": 11, "ambiguous": 1, "mapped": 13, "structural_only": 51}`
- Correct family Top-1/3/5: 13/13/13 of 13
- Contradictory-family Top-1 count: 0
- Expected absent-scope semantics detected: 9 of 9
- Safe abstention fixtures: 9
- Mapped-count growth was not an objective; every result remains advisory and requires human review.
