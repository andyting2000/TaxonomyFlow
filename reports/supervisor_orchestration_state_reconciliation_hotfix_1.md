# Supervisor Orchestration State Reconciliation Hotfix 1

- Result: **pass**
- `rejected` is mapper abstention and is not human terminal.
- `accepted` and `ignored` are the only human-terminal statuses.
- Backend plan fields now drive frontend filters, actions, and batch selection.

## Replayed Jobs

| Job | Policy eligible | Review executable | Batch executable | High | Medium | Not eligible | Reviewed | Remap executable | Revisions | Differences |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 59 | 16 | 16 | 16 | 4 | 12 | 24 | 10 | 0 | 3 | 0 |
| 60 | 15 | 15 | 15 | 5 | 10 | 32 | 3 | 0 | 1 | 0 |
| 61 | 15 | 15 | 15 | 4 | 11 | 25 | 10 | 1 | 1 | 0 |

All 150 per-suggestion state/action invariants passed: **True**.
