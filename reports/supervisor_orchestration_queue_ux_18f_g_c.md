# Supervisor Orchestration Queue UX 18F-G-C

## Feature Id
- `18F-G-C`

## Generated At
- `2026-07-23T14:35:12.926815+00:00`

## Status
- `complete`

## Calibration Sample
- **total suggestions:** `150`
- **eligible:** `47`
- **eligibility rate:** `0.3133`
- **high priority:** `13`
- **medium priority:** `34`

## Default View
- `All suggestions; no non-eligible suggestion is silently hidden`

## Per Card Indicators
- Supervisor eligible with priority
- already reviewed
- remapping available
- correction completed
- blocked
- not eligible

## Expanded Details
- priority
- eligibility reasons
- blocking reasons
- orchestration state
- recommended manual action
- existing Supervisor decision
- remapping eligibility
- correction attempts used

## States
- frontend flag hidden
- capabilities loading
- plan loading
- backend disabled
- backend unauthorized or unavailable
- unsafe contradiction
- endpoint error with manual refresh
- empty eligible queue
- empty selected filter

## Batch Ux
- **targets:** `eligible, unreviewed, nonterminal suggestions only`
- **confirmation includes count:** `True`
- **backend maximum respected:** `True`
- **already reviewed excluded:** `True`
- **revision completed excluded:** `True`

## Wording Guardrail
- `Eligibility indicates structural review priority and does not prove the current mapping is incorrect.`

## Verification
- **frontend tests:** `npm run test:auth passed 30 tests`
- **frontend build:** `npm run build passed; 1,586 modules transformed`
- **focused backend:** `orchestration policy/orchestrator/review API passed 46 tests`
- **supervisor discovery:** `152 tests passed`
- **mapping ownership admin:** `69 tests passed`
- **full backend:** `1,243 tests passed in 32.062 seconds`
- **app import:** `app_import_ok 81`
