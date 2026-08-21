# Feature #13S Mapping Readiness After Duplicate Control

## Summary

- Overall mapping readiness classification: needs_manual_duplicate_review
- Recommended next feature: Feature #13T - Manual-review policy and conflict surfacing for mapping candidates.
- Before readiness: {'high': 337, 'low': 146, 'medium': 318, 'not_ready': 139}
- After readiness: {'high': 337, 'low': 99, 'medium': 318, 'not_ready': 183}
- Delta: {'high': 0, 'low': -47, 'medium': 0, 'not_ready': 44}
- Database mutated: False

## Issue Comparison

| Issue | Before | After | Delta |
| --- | ---: | ---: | ---: |
| duplicate_label_conflicting_values | 141 | 141 | 0 |
| duplicate_label_value_same_case | 64 | 58 | -6 |
| heading_like_numeric_fact | 120 | 119 | -1 |
| date_only_label | 44 | 44 | 0 |
| year_header_row_extracted_as_fact | 47 | 0 | -47 |
| comparative_value_under_numeric_type | 263 | 0 | -263 |

## Per Case

| Case | Original | Cleaned | Suppressed | Downgraded | Converted | Conflicts | After Status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 001-bizaid-synthetic | 122 | 119 | 3 | 1 | 0 | 0 | needs_label_cleanup |
| 002-bezlife-marketing | 115 | 115 | 0 | 0 | 52 | 6 | needs_manual_duplicate_review |
| 003-fine-batik | 189 | 189 | 0 | 0 | 68 | 28 | needs_manual_duplicate_review |
| 004-info-house | 150 | 150 | 0 | 4 | 36 | 25 | needs_manual_duplicate_review |
| 005-jconnector | 134 | 134 | 0 | 15 | 35 | 3 | needs_manual_duplicate_review |
| 006-Rahsia-Herbal | 146 | 146 | 0 | 27 | 37 | 15 | needs_manual_duplicate_review |
| 007-Shield-Plus | 84 | 84 | 0 | 0 | 10 | 18 | needs_manual_duplicate_review |

## Limitations

- Post-13S readiness is based on cleaned benchmark candidates only.
- Conflicting values remain visible and unresolved by design.
- No taxonomy mapping, XBRL generation, Arelle validation, DB mutation, live model call, or production cutover is performed.
