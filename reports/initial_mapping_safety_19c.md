# Initial Mapping Safety 19C

- Status: **PASS**
- Generated: `2026-08-05T09:39:46Z`
- Safety Gate: `true`
- Template Group Leakage: `0`
- Unknown Qname Acceptance: `0`
- Out Of Candidate Acceptance: `0`
- Narrative Container Mapped Facts: `0`
- Abstract Fact Selection: `0`
- Abstract Candidates Supplied: `0`
- Period Type Incompatibility: `0`
- Payload Boundary Violations: `0`
- Final Mapping Mutations: `0`
- Confirmed Tag Id Mutations: `0`
- Template Field Mutations: `0`
- Existing Suggestion Mutations: `0`
- Dropped Source Rows: `0`
- Live Provider Calls During Tests: `0`
- Maximum Provider Calls Per Eligible Row: `1`
- Recursive Retries: `0`
- Duplicate Groups Detected: `1`
- Competing Groups Detected: `1`

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
  "report_type": "initial_mapping_safety_19c",
  "summary": {
    "safety_gate": true,
    "template_group_leakage": 0,
    "unknown_qname_acceptance": 0,
    "out_of_candidate_acceptance": 0,
    "narrative_container_mapped_facts": 0,
    "abstract_fact_selection": 0,
    "abstract_candidates_supplied": 0,
    "period_type_incompatibility": 0,
    "payload_boundary_violations": 0,
    "final_mapping_mutations": 0,
    "confirmed_tag_id_mutations": 0,
    "template_field_mutations": 0,
    "existing_suggestion_mutations": 0,
    "dropped_source_rows": 0,
    "live_provider_calls_during_tests": 0,
    "maximum_provider_calls_per_eligible_row": 1,
    "recursive_retries": 0,
    "duplicate_groups_detected": 1,
    "competing_groups_detected": 1
  },
  "required_zero_gates": [
    "template_group_leakage",
    "unknown_qname_acceptance",
    "out_of_candidate_acceptance",
    "narrative_container_mapped_facts",
    "abstract_fact_selection",
    "abstract_candidates_supplied",
    "period_type_incompatibility",
    "payload_boundary_violations",
    "final_mapping_mutations",
    "confirmed_tag_id_mutations",
    "template_field_mutations",
    "existing_suggestion_mutations",
    "dropped_source_rows",
    "live_provider_calls_during_tests",
    "recursive_retries"
  ],
  "payload_boundary": {
    "allowed": [
      "one bounded row context",
      "section/subsection metadata",
      "classified group metadata",
      "Top-K concept cards",
      "local score reasons",
      "do-not-confuse notes"
    ],
    "forbidden": [
      "auditor/reference XML",
      "parsed/generated XBRL",
      "benchmark gold",
      "expected/correct qnames",
      "correctness/evaluation labels",
      "hidden decisions",
      "confirmed_tag_id",
      "final mappings",
      "unrelated sections",
      "full taxonomy files"
    ]
  },
  "duplicate_metadata_rows": {
    "d1": {
      "duplicate_group_id": "duplicate-d6ec38dc6856b27c",
      "duplicate_rank": 0,
      "competing_source_row_ids": [
        "d2",
        "d3"
      ]
    },
    "d2": {
      "duplicate_group_id": "duplicate-d6ec38dc6856b27c",
      "duplicate_rank": 1,
      "competing_source_row_ids": [
        "d1",
        "d3"
      ]
    },
    "d3": {
      "competing_source_row_ids": [
        "d1",
        "d2"
      ]
    }
  }
}
```
