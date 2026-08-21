# Supervisor Omission Calibration #17D-B Hotfix 5

| Metric | Value |
| --- | --- |
| total_reviewed | 29 |
| mapper_omission_count | 10 |
| mapper_outcome_counts | {"mapper_rejected_but_gold_exists": 10, "mapper_selected_correct_concept": 19} |
| supervisor_agreed_with_omission_count | 0 |
| supervisor_caught_omission_count | 10 |
| numeric_fact_like_omission_count | 10 |
| omissions_with_plausible_candidates_count | 8 |

## Recommendation

Prompt future live Supervisor runs to treat rejected/no-predicted numeric fact-like rows with plausible candidates as human-review/request-better-candidate cases.
