# PDF-XBRL Rulebook Mapper Summary - Feature #18D-C

## Metrics

- total_pdf_row_value_observations: 782
- hardened_rules_loaded: 13
- advisory_suggestions_count: 26
- review_required_suggestions_count: 27
- conflicts_count: 0
- no_match_count: 729
- safe_for_auto_apply_count: 0

## Recommendation

- #18D-D justified: True
- Next: Feature #18D-D - Backend/API integration of deterministic rulebook suggestions as advisory-only evidence, behind feature flag, no auto-apply.

## Per Sample

| Sample | Observations | Advisory | Review-required | Conflicts | No-match |
| --- | ---: | ---: | ---: | ---: | ---: |
| case_001 | 142 | 0 | 6 | 0 | 136 |
| case_002 | 183 | 10 | 8 | 0 | 165 |
| case_003 | 151 | 4 | 6 | 0 | 141 |
| case_004 | 116 | 4 | 2 | 0 | 110 |
| case_005 | 190 | 8 | 5 | 0 | 177 |

## Safety

- external_llm_called: False
- external_provider_called: False
- azure_di_live_call_made: False
- database_mutated: False
- production_behavior_changed: False
- api_changed: False
- ui_changed: False
- xbrl_generated: False
- arelle_run: False
- auto_applied: False
- confirmed_tag_id_mutated: False
