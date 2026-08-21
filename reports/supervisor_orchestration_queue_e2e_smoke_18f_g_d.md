# Supervisor Orchestration Queue E2E Smoke

## Result

`passed`

The historical state-semantics and runtime/startup blockers are resolved. The
successful runtime preflight was followed by the resumed browser smoke against
Jobs 59, 60, and 61 as normal owner user 26.

## Runtime

| Check | Result |
| --- | --- |
| Backend health | HTTP 200, healthy |
| Runtime revision | `18F-G-D-hotfix-1+` |
| Database | connected |
| Jobs 59-61 | owned by user 26, `REVIEW` |
| Orchestration | enabled, available, authorized, manual |
| Auto review/remap | false / false |
| Batch maximum | 10 |
| Served frontend | canonical queue bundle |
| Stale contract warning | not visible |

## Initial Reconciliation

The pre-action backend and rendered aggregate both represented 150 suggestions:
46 policy/review executable, 13 high, 33 medium, 81 not eligible, 23 already
reviewed, 1 remapping executable, and 5 revisions. All 24 per-job filter
comparisons across the eight filters had difference zero.

No duplicate suggestion IDs or rendered cards were found.

## Representative Cases

- Job 59 `Accruals`: mapper `rejected`, non-terminal, review executable,
  remapping non-executable, block reason `concrete_suggestion_required`.
- Job 60 `Loss before taxation`: concrete `suggested` mapping with the live
  Supervisor review action visible.
- Job 60 `Cash flows from investing activities`: correction attempt 1 visible,
  retry exhausted, and no second remap action.
- Job 61 `Add : Other income`: concrete `suggested` row with remap action visible.
- No `accepted` or `ignored` rows currently existed in Jobs 59-61. Their
  terminal behavior was covered by the targeted regressions; no artificial
  human decision was created for smoke completeness.

## Live Supervisor Review

One explicit UI click reviewed Job 60 suggestion
`5c5b73fe-a099-41a6-b48b-125cf5e72512`, `Loss before taxation`.

- Request: one POST with `mode=live`.
- Loading state appeared and the duplicate click path was disabled.
- No single-action confirmation dialog appeared.
- Persisted review: `8ae6346b-cac7-461d-aa37-488f2b992ae9`.
- Result: completed, `needs_human_review`.
- Job 60 reviewed count changed 3 to 4 and review-executable count 15 to 14.
- The row became remapping executable; no remap started automatically.
- Suggestion status, confirmed tag, and final mapping remained unchanged.

## Guided Remap

The newly executable Job 60 row was remapped once through the UI.

- Request: one POST to the bounded correction endpoint.
- Loading state appeared and duplicate click was disabled.
- Persisted revision: `7ff47465-09df-422c-8a1d-fae7de36ecbd`.
- Correction attempt: 1, completed.
- Original and revised qname: `ifrs-smes:ProfitLossBeforeTax`.
- Human review required: true.
- Safe for auto-apply: false.
- Job 60 revisions changed 1 to 2 and remapping became non-executable.
- No recursive Supervisor call or final mapping mutation occurred.

## Final State

The final aggregate is total 150, policy/review executable 45, high 13,
medium 32, not eligible 81, already reviewed 24, remapping executable 1,
and revisions 6. The remaining remap is the pre-existing Job 61 row.

Post-action Job 60 summary and all eight filters again matched the backend.
Manual Refresh queue made only capabilities/plan GET requests and produced no
duplicate or stale cards.

## Batch

Each job selected a bounded 10 executable suggestions. All three confirmation
dialogs stated exactly 10 intended live calls and were dismissed. No live batch
was executed.

## Verification

- Targeted backend regressions: 109 passed.
- Frontend `npm run test:auth`: 30 passed.
- Frontend build: not run because frontend code did not change.
- Full backend suite: not run because implementation code did not change.

## Decision

#18F-G-D and #18F-G-D-resume pass. Proceed to #18F-G-E for internal reviewer
rollout readiness and controlled feature enablement.
