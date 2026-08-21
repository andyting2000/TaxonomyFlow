# Bounded Initial Mapping 19C

- Status: **PASS**
- Generated: `2026-08-05T09:39:46Z`
- Mode: `"deterministic_only"`
- Exact Initial Mapping Accuracy: `0.8333`
- Provider Calls: `0`
- Strict Candidate Only Validation: `true`
- Unknown Qname Rejected: `true`
- Out Of Candidate Rejected: `true`

## Evidence

```json
{
  "feature": "19C",
  "generated_at": "2026-08-05T09:39:46Z",
  "status": "PASS",
  "insertion_point": "Azure DI normalization -> #19A structure -> #19B classification -> #19C advisory artifact; legacy production mapping remains separate",
  "changed_files": [
    "config.py",
    ".env.example",
    ".env.docker.example",
    "schemas.py",
    "services/section_aware_taxonomy_concept_cards.py",
    "services/section_aware_row_mapping_eligibility.py",
    "services/section_aware_mapping_context_builder.py",
    "services/section_aware_taxonomy_candidate_retriever.py",
    "services/section_aware_candidate_scoring.py",
    "services/section_aware_initial_mapping_llm.py",
    "services/section_aware_initial_mapping.py",
    "services/azure_di_production_extraction.py",
    "routers/filings.py",
    "tests/fixtures/section_aware_mapping/fixtures_19c.json",
    "tests/section_aware_mapping_test_support.py",
    "tests/test_section_aware_concept_cards.py",
    "tests/test_section_aware_row_mapping_eligibility.py",
    "tests/test_section_aware_mapping_context_builder.py",
    "tests/test_section_aware_taxonomy_candidate_retriever.py",
    "tests/test_section_aware_initial_mapping_llm.py",
    "tests/test_initial_mapping_payload_boundary.py",
    "tests/test_initial_mapping_artifact.py",
    "tests/test_initial_mapping_api.py",
    "tests/test_toc_aware_initial_mapping_integration.py",
    "tests/test_initial_mapping_quality_report.py",
    "tests/test_auth_backend_foundation.py",
    "scripts/evaluate_section_aware_initial_mapping_19c.py",
    "docs/toc_aware_template_native_pipeline.md",
    "reports/section_aware_candidate_retrieval_19c.json",
    "reports/section_aware_candidate_retrieval_19c.md",
    "reports/bounded_initial_mapping_19c.json",
    "reports/bounded_initial_mapping_19c.md",
    "reports/initial_mapping_quality_19c.json",
    "reports/initial_mapping_quality_19c.md",
    "reports/initial_mapping_safety_19c.json",
    "reports/initial_mapping_safety_19c.md",
    "feature_list.json",
    "PROGRESS.md"
  ],
  "feature_flags": {
    "TOC_AWARE_TAXONOMY_CANDIDATE_RETRIEVAL_ENABLED": false,
    "TOC_AWARE_INITIAL_MAPPING_ENABLED": false,
    "TOC_AWARE_INITIAL_MAPPING_PERSISTENCE_ENABLED": false,
    "TOC_AWARE_INITIAL_MAPPING_LIVE_LLM_ENABLED": false,
    "TOC_AWARE_INITIAL_MAPPING_MODE": "deterministic_only",
    "TOC_AWARE_INITIAL_MAPPING_MAX_CANDIDATES": 8,
    "TOC_AWARE_INITIAL_MAPPING_MAX_ROWS_PER_JOB": 5000,
    "TOC_AWARE_INITIAL_MAPPING_ROW_TIMEOUT_SECONDS": 120,
    "TOC_AWARE_INITIAL_MAPPING_MAX_CONCURRENT_CALLS": 1,
    "TOC_AWARE_INITIAL_MAPPING_MIN_CANDIDATE_SCORE": 0.0
  },
  "registry_hash": "16de7eaeafcdf760c7f4869072a6b0a3925088f6bc260672389b5c502015b7d4",
  "concept_inventory_hash": "5b648a0ac86614dfa8f63c767273a91ae63aad6164e68b9fdcfc849b2a960205",
  "taxonomy_version": "SSMxT_2022v1.0",
  "verification": {
    "focused_19c_tests": 31,
    "full_backend_tests": 1406,
    "live_provider_calls": 0
  },
  "recommended_next_feature": "Feature #19D - Populate advisory #19C mappings directly into editable template draft fields without creating final mappings.",
  "report_type": "bounded_initial_mapping_19c",
  "summary": {
    "mode": "deterministic_only",
    "exact_initial_mapping_accuracy": 0.8333,
    "provider_calls": 0,
    "strict_candidate_only_validation": true,
    "unknown_qname_rejected": true,
    "out_of_candidate_rejected": true
  },
  "contract": {
    "allowed_decisions": [
      "mapped",
      "ambiguous",
      "abstain",
      "no_safe_mapping",
      "structural_only",
      "provider_failed",
      "validation_failed"
    ],
    "requires_human_review": true,
    "maximum_calls_per_eligible_row": 1,
    "recursive_retries": 0,
    "safe_for_auto_apply": false
  },
  "artifact": "uploads/document-structures/job_{job_id}/initial_mapping_19c_v1.json",
  "api": [
    "GET /api/v1/filings/jobs/{job_id}/initial-mapping/capabilities",
    "GET /api/v1/filings/jobs/{job_id}/initial-mapping",
    "GET /api/v1/filings/jobs/{job_id}/initial-mapping/rows/{row_id}"
  ]
}
```
