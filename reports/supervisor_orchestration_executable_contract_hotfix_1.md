# Supervisor Orchestration Executable Contract Hotfix 1

- Result: **pass**
- Remapping contract: **Option A**.
- Review and batch execution use the same backend predicate.
- Remapping requires `suggested` plus a concrete original qname.

## Aggregate Actionability

| Policy eligible | Review executable | Batch executable | Remap executable |
| --- | --- | --- | --- |
| 46 | 46 | 46 | 1 |

The two previously misadvertised `rejected` rows now report `remapping_executable=false` with `concrete_suggestion_required`.
