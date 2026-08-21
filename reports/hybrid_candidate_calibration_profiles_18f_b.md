# Hybrid Candidate Calibration Profiles #18F-B

| Profile | Min Score | Lexical Min | Non-Lexical Min | High | Medium | Low | Max Candidates | Ambiguity |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| strict | 0.64 | 0.66 | 0.6 | 0.84 | 0.7 | 0.58 | 3 | 0.07 |
| balanced | 0.44 | 0.44 | 0.44 | 0.78 | 0.62 | 0.45 | 5 | 0.05 |
| recall | 0.43 | 0.44 | 0.42 | 0.74 | 0.58 | 0.42 | 7 | 0.04 |

## Source Weights
- `strict`: `{'deterministic_current_mapper': 1.12, 'statement_dictionary': 1.06, 'statement_role_pack': 1.09, 'section_concept_pack': 1.07, 'concept_playbook_lookup': 1.07, 'cash_flow_movement_pack': 1.03, 'equity_movement_pack': 1.02, 'format_memory_pack': 1.07, 'local_concept_family_pack': 0.99, 'taxonomy_structure_hint': 0.98, 'note_total_candidate': 0.96, 'taxonomy_lexical': 0.9, 'cached_qwen': 0.94}`
- `balanced`: `{'deterministic_current_mapper': 1.09, 'statement_dictionary': 1.05, 'statement_role_pack': 1.08, 'section_concept_pack': 1.06, 'concept_playbook_lookup': 1.07, 'cash_flow_movement_pack': 1.03, 'equity_movement_pack': 1.02, 'format_memory_pack': 1.06, 'local_concept_family_pack': 1.01, 'taxonomy_structure_hint': 0.99, 'note_total_candidate': 0.98, 'taxonomy_lexical': 0.94, 'cached_qwen': 0.97}`
- `recall`: `{'deterministic_current_mapper': 1.06, 'statement_dictionary': 1.03, 'statement_role_pack': 1.05, 'section_concept_pack': 1.04, 'concept_playbook_lookup': 1.04, 'cash_flow_movement_pack': 1.02, 'equity_movement_pack': 1.02, 'format_memory_pack': 1.04, 'local_concept_family_pack': 1.0, 'taxonomy_structure_hint': 1.0, 'note_total_candidate': 1.0, 'taxonomy_lexical': 0.98, 'cached_qwen': 1.0}`
