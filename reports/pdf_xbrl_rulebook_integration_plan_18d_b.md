# Deterministic-First Integration Plan - Feature #18D-B

- Recommended next feature: Feature #18D-C - Deterministic rulebook mapper service, offline/mock only
- #18D-C justified: True
- Production integration now justified: False
- Auto-apply approved: False
- confirmed_tag_id automation approved: False

## Boundaries

- Rulebook output must not set confirmed_tag_id.
- Rulebook output must not auto-accept or auto-apply a mapping.
- Rulebook output must be persisted only as mapping suggestion evidence.
- Human review remains final for accepted mappings.
- Supervisor or LLM review can focus on exceptions, conflicts, and unmapped rows.

## Future Phases

| Feature | Scope | Auto-apply |
| --- | --- | ---: |
| Feature #18D-C | deterministic rulebook mapper service, offline/mock only | False |
| Feature #18D-D | backend API/reporting integration as advisory suggestions only | False |
| Feature #18D-E | UI display of deterministic rulebook suggestions | False |
| Feature #18D-F | production rulebook feature flag and monitoring | False |
| Later explicit approval only | no auto-apply unless a later feature explicitly approves it | False |
