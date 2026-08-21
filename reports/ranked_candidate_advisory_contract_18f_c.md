# Ranked Candidate Advisory Contract #18F-C

## Schema Names

- `RankedCandidateAdvisoryRequest`
- `RankedCandidateAdvisoryResponse`
- `RankedCandidateRow`
- `RankedCandidateItem`
- `RankedCandidateEvidence`
- `RankedCandidateSafetySummary`

## Candidate Payload

- `rank`: integer
- `qname`: string
- `concept_label`: string|null
- `namespace`: string|null
- `candidate_sources_combined`: string[]
- `score`: number
- `confidence_bucket`: string
- `risk_level`: string
- `evidence`: RankedCandidateEvidence
- `ambiguity_reasons`: string[]
- `blocking_reasons`: string[]
- `requires_human_review`: boolean
- `safe_for_auto_apply`: boolean
- `recommended_action`: enum
- `profile`: string
- `calibration_version`: string

## Feature Flags

- `RANKED_CANDIDATES_ADVISORY_ENABLED` default `False`
- `RANKED_CANDIDATES_ADVISORY_DEFAULT_MODE` default `dry_run`
- `RANKED_CANDIDATES_ADVISORY_ALLOW_PERSISTENCE` default `False`
- `RANKED_CANDIDATES_ADVISORY_DEFAULT_PROFILE` default `balanced`
- `RANKED_CANDIDATES_ADVISORY_MAX_ROWS` default `1000`
- `RANKED_CANDIDATES_ADVISORY_MAX_CANDIDATES_PER_ROW` default `5`
- `RANKED_CANDIDATES_ADVISORY_ADMIN_ONLY` default `True`

Forbidden action values: `accept`, `apply`, `confirm`.
