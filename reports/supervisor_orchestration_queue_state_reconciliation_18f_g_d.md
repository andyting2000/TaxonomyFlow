# Supervisor Orchestration Queue State Reconciliation

## Result

`passed`

## Canonical Model

- `suggested`: concrete mapper suggestion.
- `rejected`: mapper abstention, not human-terminal.
- `accepted`: human acceptance, terminal.
- `ignored`: human rejection/ignore, terminal.
- Option A remapping requires `suggested` plus a concrete original qname.

## Pre-Action State

Backend and frontend reconciled at 150 total, 46 review executable, 13 high,
33 medium, 81 not eligible, 23 reviewed, 1 remapping executable, and 5
revisions. Every per-job summary and filter comparison had difference zero.

Across 150 plan items there were 115 rejected and 35 suggested rows. Every
rejected row was non-terminal, lacked a concrete qname, was not remapping
executable, and reported `concrete_suggestion_required`. No Option A violation
was found.

## Explicit Transitions

The Job 60 `Loss before taxation` review moved:

`supervisor_eligible -> remapping_available`

Review executable changed true to false, Job 60 reviewed count changed 3 to 4,
and remapping executable changed false to true.

The explicit guided remap then moved:

`remapping_available -> revision_created`

Remapping executable changed true to false, Job 60 revisions changed 1 to 2,
and the retry block became `correction_retry_limit_reached`. The initial
suggestion remained immutable.

## Final State

The aggregate now contains 150 total, 45 review executable, 13 high, 32 medium,
81 not eligible, 24 reviewed, 1 remapping executable, and 6 revisions.

Manual queue refresh was GET-only. The refreshed Job 60 summary and all eight
filters matched the live plan with zero differences.

No current accepted or ignored row existed in the three smoke jobs, so no human
decision was manufactured. Targeted terminal-state regressions passed.
