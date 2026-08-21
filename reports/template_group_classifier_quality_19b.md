# Template Group Classifier Quality #19B

- Status: `PASS`
- Feature: `19B-resume`
- Registry: `mpers-2022-v1`
- Registry hash: `16de7eaeafcdf760c7f4869072a6b0a3925088f6bc260672389b5c502015b7d4`

## Evidence

- `metrics`: {"ambiguous_or_unassigned_fixture_rate": 0.05555555555555555, "deterministic_coverage": 0.9444444444444444, "dropped_content_count": 0, "exact_template_group_accuracy": 1.0, "invalid_response_rejection": 1, "llm_fallback_fixture_coverage": 1, "mapping_mutations": 0, "multiple_template_detection": 1, "narrative_false_positives": 0, "notes_content_conservation": 1, "notes_parent_container_accuracy": 1, "obvious_primary_accuracy": 1.0, "presentation_variant_accuracy": 1.0, "unknown_id_rejection": 1}
- `required_gates`: {"730000_not_notes_container": true, "740000_issued_capital": true, "750000_related_party_transactions": true, "dropped_content_zero": true, "invalid_structured_responses_accepted_zero": true, "mapping_mutations_zero": true, "narrative_false_positives_zero": true, "notes_content_conservation_100_percent": true, "notes_parent_container_only_100_percent": true, "obvious_primary_accuracy_100_percent": true, "presentation_variant_accuracy_100_percent": true, "unknown_template_ids_accepted_zero": true}
- `note_semantic_cases`: [{"expected_code": "730000", "fixture": "R", "passed": true, "predicted_code": "730000"}, {"expected_code": "740000", "fixture": "S", "passed": true, "predicted_code": "740000"}, {"expected_code": "750000", "fixture": "T", "passed": true, "predicted_code": "750000"}]
- `contextual_note_passed`: True
- `multiple_template_passed`: True
- `unknown_note_outcome`: unassigned
- `llm_fixture_only`: True
- `live_provider_calls`: 0

## Decision

All fixture quality gates pass.
