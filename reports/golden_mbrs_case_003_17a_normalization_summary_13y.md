# Azure DI Normalization Summary - Feature #13Y

## Summary

- total_candidates: 564 -> 146 (-418)
- comparative_numeric_fact: 60 -> 60 (+0)
- numeric_fact: 9 -> 9 (+0)
- subtotal_or_total: 14 -> 12 (-2)
- text_block: 38 -> 33 (-5)
- heading: 379 -> 19 (-360)
- metadata: 64 -> 13 (-51)
- mapping_handoff_candidates: 63 -> 0 (-63)
- auto_mappable: 49 -> 0 (-49)
- suggest_mapping_only: 14 -> 0 (-14)
- manual_review_required: 15 -> 0 (-15)
- reference_context_only: 239 -> 0 (-239)
- duplicate_label_value_same_case: 135 -> 0 (-135)
- exact_duplicate_same_page: 44 -> 0 (-44)
- too_short_label: 20 -> 0 (-20)
- heading_like_numeric_fact: 9 -> 0 (-9)
- year_only_label: 8 -> 0 (-8)

## Normalization Effects

- Index/TOC rows suppressed: 0
- Header/footer/context rows removed from normalized rows: 413
- Text-block fragments merged: 5
- Downgraded candidates: 138
- Suppressed candidates: 418

## Gate Outputs

- Mapping handoff candidates: 0
- Auto mappable: 0
- Suggest mapping only: 0
- Manual review queue count: 0
- Excluded: 0

## Assessment

- Ready for mapping-candidate generation: False
- Recommended next feature: Feature #13Z - Continue Azure DI table/text-block normalization before mapping candidate generation.
- Database mutated: False
- Production behavior changed: False
- Live provider call: False

## Limitations

- Normalization is heuristic and report-only.
- No live provider call, DB mutation, production behavior change, taxonomy mapping, XBRL generation, or Arelle validation occurred.
- Reference XML is not sent to any provider or model.
