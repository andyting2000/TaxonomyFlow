# Ranked Candidate Backend Integration Design #18F-C

Design-only backend advisory integration path. No route, database, UI, final mapping, or auto-apply behavior is enabled in this feature.

## Calibrated Mapper Summary

- Recommended profile: `balanced`
- Candidate coverage: `0.6036`
- Top-1 precision: `0.8`
- Top-3/Top-5 recall: `0.5825` / `0.5825`
- High-or-critical ratio: `0.2574`
- Critical candidates: `0`
- Safe for auto-apply: `0`

## Service Boundary

- service_module: `services/ranked_candidate_advisory_service.py`
- router_wiring_in_this_feature: `False`
- database_persistence_in_this_feature: `False`
- runtime_candidate_generation_inputs: `['cached extracted rows for a filing/job in a later dry-run API feature', 'local taxonomy metadata', 'local calibrated profile configuration', 'local non-lexical candidate source evidence']`
- forbidden_runtime_inputs: `['auditor XML', 'parsed XML facts', 'gold answers', 'target correct qnames', 'evaluation labels', 'external LLM or provider responses']`

## Future Endpoints

- `GET /api/v1/filings/jobs/{job_id}/ranked-candidates/capabilities`: read capability and safety flags only (design_only)
- `POST /api/v1/filings/jobs/{job_id}/ranked-candidates/run`: future dry-run generation behind disabled feature flag (design_only)
- `GET /api/v1/filings/jobs/{job_id}/ranked-candidates`: future read of persisted advisory candidates after a separate persistence feature (design_only)

## No-Auto-Apply Guarantees

- requires_human_review is always true for every candidate.
- safe_for_auto_apply is always false for every candidate.
- recommended_action is limited to review_candidate, keep_for_human_review, no_candidate, or blocked.
- No response field carries confirmed_tag_id mutation instructions.
- Dry-run service returns payloads only and does not receive a database session.
- Persistence and UI are deferred to later explicitly approved features.

Recommended next feature: Feature #18F-D - Implement dry-run backend ranked-candidate advisory API behind disabled feature flag
