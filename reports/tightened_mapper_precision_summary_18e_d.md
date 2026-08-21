# Tightened Mapper Precision Summary - Feature #18E-D

- total_observations: 782
- candidate_count: 352
- touched_coverage_rate: 0.4501
- precision_on_evaluable: 0.7373
- exact_matches: 200
- false_positive_count: 88
- ambiguous_count: 17
- not_evaluable_count: 17
- blocked_candidate_rows: 148
- recommended_next_feature: Feature #18E-D-hotfix-1 - Recover low-risk overblocked true positives with stricter evidence.
- recommendation_reason: Several blocked candidates would have matched local XBRL facts and should be recovered only through a targeted hotfix.
- boundary: No auto-apply or confirmed_tag_id automation is recommended; human review remains required.

## Candidate Source Risk

| Source | Candidates | Precision | False positives | Risk | Recommendation |
| --- | ---: | ---: | ---: | --- | --- |
| pdf_xbrl_rulebook | 196 | 0.6201 | 68 | critical | tighten |
| context_template | 0 | None | 0 | low | keep_review_required |
| statement_template | 128 | 0.8906 | 14 | medium | keep_review_required |
| note_link_template | 14 | 0.6429 | 5 | critical | needs_note_link |
| combined_rulebook_template | 0 | None | 0 | low | keep_review_required |
| dictionary | 14 | 0.9286 | 1 | medium | tighten |
| row_order | 0 | None | 0 | low | keep_review_required |
| dictionary_row_order | 0 | None | 0 | low | keep_review_required |
| context_dictionary | 0 | None | 0 | low | keep_review_required |
| unknown | 0 | None | 0 | low | keep_review_required |
