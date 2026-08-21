# Azure DI Normalization Summary - Feature #13Y

## Summary

- total_candidates: 317 -> 92 (-225)
- comparative_numeric_fact: 26 -> 22 (-4)
- numeric_fact: 1 -> 1 (+0)
- subtotal_or_total: 5 -> 9 (+4)
- text_block: 46 -> 36 (-10)
- heading: 201 -> 24 (-177)
- metadata: 38 -> 0 (-38)
- mapping_handoff_candidates: 63 -> 53 (-10)
- auto_mappable: 49 -> 42 (-7)
- suggest_mapping_only: 14 -> 11 (-3)
- manual_review_required: 15 -> 15 (+0)
- reference_context_only: 239 -> 24 (-215)
- duplicate_label_value_same_case: 135 -> 2 (-133)
- exact_duplicate_same_page: 44 -> 0 (-44)
- too_short_label: 20 -> 0 (-20)
- heading_like_numeric_fact: 9 -> 9 (+0)
- year_only_label: 8 -> 0 (-8)

## Normalization Effects

- Index/TOC rows suppressed: 18
- Header/footer/context rows removed from normalized rows: 197
- Text-block fragments merged: 10
- Downgraded candidates: 73
- Suppressed candidates: 225

## Gate Outputs

- Mapping handoff candidates: 53
- Auto mappable: 42
- Suggest mapping only: 11
- Manual review queue count: 50
- Excluded: 39

## Assessment

- Ready for mapping-candidate generation: True
- Recommended next feature: Feature #13Z - Azure DI normalized mapping handoff to mapping candidate generation.
- Database mutated: False
- Production behavior changed: False
- Live provider call: False

## Limitations

- Normalization is heuristic and report-only.
- No live provider call, DB mutation, production behavior change, taxonomy mapping, XBRL generation, or Arelle validation occurred.
- Reference XML is not sent to any provider or model.
