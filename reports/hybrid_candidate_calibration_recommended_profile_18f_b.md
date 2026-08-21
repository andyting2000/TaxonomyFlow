# Hybrid Candidate Recommended Profile #18F-B

- Recommended profile: `balanced`
- Reason: Balanced preserves >=60% coverage, keeps top-1 precision >=0.75, and controls high/critical risk without critical candidates.
- Recommended next feature: `Feature #18F-C - Design backend advisory integration for ranked candidates, no auto-apply`
- Backend advisory integration justified: `True`
- Coverage: `0.6036`
- Top-1 precision: `0.8`
- Top-3 recall: `0.5825`
- Top-5 recall: `0.5825`
- Risk distribution: `{'high': 253, 'low': 336, 'medium': 394}`
- Source contribution: `{'cash_flow_movement_pack': {'candidate_count': 59, 'candidate_share': 0.06, 'row_count': 59}, 'concept_playbook_lookup': {'candidate_count': 485, 'candidate_share': 0.4934, 'row_count': 241}, 'deterministic_current_mapper': {'candidate_count': 300, 'candidate_share': 0.3052, 'row_count': 300}, 'equity_movement_pack': {'candidate_count': 14, 'candidate_share': 0.0142, 'row_count': 14}, 'local_concept_family_pack': {'candidate_count': 58, 'candidate_share': 0.059, 'row_count': 58}, 'section_concept_pack': {'candidate_count': 131, 'candidate_share': 0.1333, 'row_count': 131}, 'statement_dictionary': {'candidate_count': 238, 'candidate_share': 0.2421, 'row_count': 226}, 'statement_role_pack': {'candidate_count': 46, 'candidate_share': 0.0468, 'row_count': 46}, 'taxonomy_lexical': {'candidate_count': 730, 'candidate_share': 0.7426, 'row_count': 419}}`
- Safety: `safe_for_auto_apply=false`, `requires_human_review=true`, no confirmed_tag_id automation.
