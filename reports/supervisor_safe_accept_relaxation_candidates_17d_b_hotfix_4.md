# Supervisor Safe Accept Relaxation Candidates #17D-B Hotfix 4

| Metric | Value |
| --- | --- |
| blocked_correct_mapping_count | 4 |
| relaxable_safe_accept_candidates_count | 4 |
| non_relaxable_blocked_correct_count | 0 |
| candidate_not_supported_blocks_relaxation_count | 0 |
| ambiguous_label_blocks_relaxation_count | 0 |
| statement_family_mismatch_blocks_relaxation_count | 0 |

## Candidate Examples

| Case | Label | Concept | Reason |
| --- | --- | --- | --- |
| case_005 | Cash from operating activities | ifrs-smes:CashFlowsFromUsedInOperatingActivities | Mapper prediction is locally correct, has near/exact alias evidence, statement family matches, and only broad_substitute/generic medium-risk blocking remains. |
| case_005 | Net (decrease) / increase in cash and cash equivalents | ifrs-smes:IncreaseDecreaseInCashAndCashEquivalents | Mapper prediction is locally correct, has near/exact alias evidence, statement family matches, and only broad_substitute/generic medium-risk blocking remains. |
| case_005 | Bank balances | ssmt:CashAndBankBalances | Mapper prediction is locally correct, has near/exact alias evidence, statement family matches, and only broad_substitute/generic medium-risk blocking remains. |
| case_006 | CASH AND CASH EQUIVALENTS AT END OF YEAR (NOTE 9) | ifrs-smes:CashAndCashEquivalents | Mapper prediction is locally correct, has near/exact alias evidence, statement family matches, and only broad_substitute/generic medium-risk blocking remains. |

## Recommendation

Relaxation candidates are evaluation-only. Any future production rule must remain deterministic and human-confirmed until separately approved.
