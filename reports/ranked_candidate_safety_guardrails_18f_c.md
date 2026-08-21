# Ranked Candidate Safety Guardrails #18F-C

- feature_disabled_by_default: `True`
- dry_run_only: `True`
- persistence_forced_false: `True`
- admin_only_by_default: `True`
- balanced_profile_default: `True`
- safe_for_auto_apply_always_false: `True`
- requires_human_review_always_true: `True`
- recommended_action_never_accept_apply_confirm: `True`
- confirmed_tag_id_mutations: `0`
- final_mapping_mutations: `0`
- external_calls: `0`
- xbrl_generation: `0`
- arelle_runs: `0`

## Failure Modes

- feature flag disabled: capabilities show disabled; generation fails closed
- invalid profile: safe RankedCandidateAdvisoryError
- missing local report/input: safe RankedCandidateAdvisoryError
- persistence flag accidentally true: effective allow_persistence remains false
- unsupported mode: effective mode remains dry_run
- candidate with unsafe flags: schema validation rejects or serializer forces safe values
