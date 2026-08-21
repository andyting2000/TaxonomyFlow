# Supervisor Safe Accept Threshold Calibration #17D-B Hotfix 6

| Metric | Value |
| --- | --- |
| total_reviewed | 29 |
| original_safe_to_accept_count | 15 |
| calibrated_safe_to_accept_count | 19 |
| calibrated_safe_to_accept_accuracy | 1.0 |
| calibrated_false_safe_accept_count | 0 |
| additional_safe_accept_count | 4 |
| additional_safe_accept_correct_count | 4 |
| blocked_correct_mapping_count_before | 4 |
| blocked_correct_mapping_count_after_simulation | 0 |
| blocked_correct_reduction | 4 |
| hard_issue_blocked_count | 9 |
| low_confidence_only_relaxed_count | 3 |
| cash_flow_relaxed_count | 4 |
| classification_counts | {"blocked_by_hard_issue": 9, "blocked_by_statement_or_candidate_mismatch": 1, "not_relaxable": 3, "relaxable_cash_flow_same_family": 8, "relaxable_exact_alias_strong_evidence": 8} |
| relaxation_label_counts | {"blocked_by_low_mapper_confidence_only": 3, "relaxable_cash_flow_same_family": 8, "relaxable_exact_alias_strong_evidence": 16} |

## Recommendation

Run a bounded live Supervisor retest before any #17D-C production integration; this report is simulation-only.
