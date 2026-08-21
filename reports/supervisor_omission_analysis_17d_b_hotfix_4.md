# Supervisor Omission Analysis #17D-B Hotfix 4

| Metric | Value |
| --- | --- |
| total_reviewed | 29 |
| mapper_selected_correct_concept | 19 |
| mapper_selected_wrong_concept | 0 |
| mapper_rejected_but_gold_exists | 10 |
| mapper_no_prediction_but_gold_exists | 0 |
| mapper_correctly_rejected_non_fact | 0 |
| mapper_no_gold_available_or_not_evaluable | 0 |
| mapper_omission_count | 10 |
| mapper_omission_rate | 0.3448 |
| supervisor_agreed_with_omission_count | 0 |
| supervisor_caught_omission_count | 10 |
| false_agree_on_rejection_count | 0 |
| rejected_rows_with_gold_answer_count | 10 |
| no_prediction_rows_with_gold_answer_count | 0 |

## Recommendation

Improve candidate retrieval and omission detection before production Supervisor integration; safe_to_accept should remain suggestion-only.
