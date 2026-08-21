# Supervisor Orchestration Queue Contract 18F-G-C

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

## Capabilities Contract
- **plan only:** `True`
- **mode:** `manual`
- **auto review:** `False`
- **auto remap:** `False`
- **max batch size exposed:** `True`

## Plan Contract
- **priority counts added:**
  - high_priority_count
  - medium_priority_count
- **item provenance preserved:** `True`
- **requires human review:** `True`
- **safe for auto apply:** `False`

## Batch Contract
- **optional field:** `suggestion_ids`
- **legacy omitted behavior preserved:** `True`
- **queue behavior:** `eligible, unreviewed, nonterminal IDs only`
- **duplicates removed:** `True`
- **owned job filtering:** `True`
- **backend live batch limit preserved:** `True`

## Refresh After
- single Supervisor review
- bounded batch review
- guided remapping
- suggestion acceptance
- suggestion rejection
- manual refresh

## Verification
- **frontend tests:** `npm run test:auth passed 30 tests`
- **frontend build:** `npm run build passed; 1,586 modules transformed`
- **focused backend:** `orchestration policy/orchestrator/review API passed 46 tests`
- **supervisor discovery:** `152 tests passed`
- **mapping ownership admin:** `69 tests passed`
- **full backend:** `1,243 tests passed in 32.062 seconds`
- **app import:** `app_import_ok 81`
