# Template Group Classification Foundation #19B

- Status: `PASS`
- Feature: `19B-resume`
- Registry: `mpers-2022-v1`
- Registry hash: `16de7eaeafcdf760c7f4869072a6b0a3925088f6bc260672389b5c502015b7d4`

## Evidence

- `feature_flags_false_by_default`: ["TOC_AWARE_TEMPLATE_CLASSIFICATION_ENABLED", "TOC_AWARE_TEMPLATE_CLASSIFICATION_PERSISTENCE_ENABLED", "TOC_AWARE_TEMPLATE_CLASSIFICATION_LIVE_LLM_ENABLED"]
- `contracts`: ["TemplateGroupCard", "TemplateGroupAssignment", "SectionClassificationOutcome", "DocumentTemplateClassificationResult"]
- `primary_routing`: [{"expected_code": "610000", "outcome": "matched", "passed": true, "predicted_code": "610000", "title": "Statement of Changes in Equity"}, {"expected_code": "210000", "outcome": "matched", "passed": true, "predicted_code": "210000", "title": "Statement of Financial Position"}, {"expected_code": "310000", "outcome": "matched", "passed": true, "predicted_code": "310000", "title": "Statement of Profit or Loss"}, {"expected_code": "520000", "outcome": "matched", "passed": true, "predicted_code": "520000", "title": "Statement of Cash Flows"}]
- `presentation_variants`: [{"expected_code": "220000", "fixture": "K", "passed": true, "predicted_code": "220000"}, {"expected_code": "420000", "fixture": "L", "passed": true, "predicted_code": "420000"}]
- `narrative_false_positives`: 0
- `notes_parent_outcome`: container_only
- `many_to_many_fixture_passed`: True
- `artifact`: uploads/document-structures/job_{job_id}/template_classification_19b_v1.json
- `api`: ["GET /api/v1/filings/jobs/{job_id}/template-classification/capabilities", "GET /api/v1/filings/jobs/{job_id}/template-classification"]

## Decision

Foundation passes; classification remains disabled by default.
