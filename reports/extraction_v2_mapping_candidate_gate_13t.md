# Feature #13T Mapping Candidate Gate Report

## Summary

- Total original candidates: 940
- Total cleaned candidates: 937
- Auto mappable: 231
- Suggest mapping only: 180
- Manual review required: 336
- Blocked from mapping: 10
- Reference only/context: 183
- Allowed into #13U: 411
- Requires confirmation: 180
- Blocked from #13U: 529
- Database mutated: False

This is not taxonomy mapping, XBRL generation, or production readiness proof.

## Per Case Gate Distribution

| Case | Auto | Suggest | Manual | Blocked | Context |
| --- | ---: | ---: | ---: | ---: | ---: |
| 001-bizaid-synthetic | 0 | 0 | 39 | 3 | 80 |
| 002-bezlife-marketing | 34 | 43 | 36 | 0 | 2 |
| 003-fine-batik | 60 | 42 | 78 | 6 | 3 |
| 004-info-house | 44 | 19 | 66 | 0 | 21 |
| 005-jconnector | 33 | 30 | 41 | 0 | 30 |
| 006-Rahsia-Herbal | 41 | 34 | 38 | 0 | 33 |
| 007-Shield-Plus | 19 | 12 | 38 | 1 | 14 |

## Top Manual Review Reasons

- sign_uncertainty: 251
- heading_like_numeric_fact: 182
- duplicate_conflicting_values: 92
- duplicate_same_label_value: 86
- subtotal_total_uncertainty: 76
- weak_text_block_label: 65
- ambiguous_statement_section: 36
- weak_label: 18
- requires_manual_mapping_confirmation: 12
- text_block_boundary_uncertainty: 9
- section_mismatch: 6

## Top Blocked Reasons

- weak_label: 57
- date_or_year_label: 50
- duplicate_conflicting_values: 49
- cleaned_downgraded_candidate: 47
- year_header_row: 47
- duplicate_same_label_value: 30
- ambiguous_statement_section: 8
- non_numeric_numeric_value: 7
- section_mismatch: 6
- exact_duplicate_suppressed: 3
- suppressed_candidate: 3
- heading_like_numeric_fact: 2
- missing_statement_section: 1
