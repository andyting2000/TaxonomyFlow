# Tightened Mapper Readiness Matrix - Feature #18E-D

- safe_to_upgrade_to_advisory_medium_count: 3
- should_be_disabled_count: 4
- recommended_next_feature: Feature #18E-D-hotfix-1 - Recover low-risk overblocked true positives with stricter evidence.
- recommendation_reason: Several blocked candidates would have matched local XBRL facts and should be recovered only through a targeted hotfix.
- boundary: No #18E-D readiness entry recommends auto-apply or confirmed_tag_id automation; human review remains required.

## Matrix

| Group | Name | Advisory medium | Disabled | More context | Note link | Auto apply |
| --- | --- | --- | --- | --- | --- | --- |
| candidate_source | pdf_xbrl_rulebook | False | False | True | False | False |
| candidate_source | context_template | False | False | False | False | False |
| candidate_source | statement_template | False | False | False | False | False |
| candidate_source | note_link_template | False | False | True | True | False |
| candidate_source | combined_rulebook_template | False | False | False | False | False |
| candidate_source | dictionary | False | False | False | False | False |
| candidate_source | row_order | False | False | False | False | False |
| candidate_source | dictionary_row_order | False | False | False | False | False |
| candidate_source | context_dictionary | False | False | False | False | False |
| candidate_source | unknown | False | False | False | False | False |
| statement_family | Statement of Financial Position | False | False | True | False | False |
| statement_family | Profit or Loss / Comprehensive Income | False | False | True | False | False |
| statement_family | Cash Flows | False | False | False | False | False |
| statement_family | Changes in Equity | False | False | False | False | False |
| statement_family | Notes | False | False | True | True | False |
| statement_family | Unknown | False | False | True | False | False |
| label_family | revenue | False | False | True | False | False |
| label_family | other income | False | False | True | False | False |
| label_family | expenses | False | False | True | False | False |
| label_family | tax | False | True | True | False | False |
| label_family | profit/loss result | False | False | True | False | False |
| label_family | receivables | False | True | True | False | False |
| label_family | payables | False | True | True | False | False |
| label_family | cash/bank | True | False | False | False | False |
| label_family | PPE | True | False | False | False | False |
| label_family | borrowings/loans | False | True | True | False | False |
| label_family | equity | False | False | True | False | False |
| label_family | totals/subtotals | False | False | True | False | False |
| label_family | cash-flow movement | False | False | False | False | False |
| label_family | note-detail | False | False | True | True | False |
| label_family | unknown | True | False | False | False | False |
