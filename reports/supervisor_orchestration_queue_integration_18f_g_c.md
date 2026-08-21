# Supervisor Orchestration Queue Integration 18F-G-C

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

## Frontend Flag
- **name:** `VITE_SHOW_SUPERVISOR_ORCHESTRATION_QUEUE`
- **default:** `False`
- **security control:** `False`
- **backend authoritative:** `True`

## Placement
- `Compact queue summary inside AI Mapping Suggestions`

## Endpoints Consumed
- GET /api/v1/filings/jobs/{job_id}/supervisor-orchestration/capabilities
- GET /api/v1/filings/jobs/{job_id}/supervisor-orchestration/plan

## Summary Fields
- total suggestions
- eligible
- high priority
- medium priority
- already reviewed
- remapping available
- revisions completed
- blocked
- not eligible

## Filters
- all
- eligible unreviewed
- high priority
- medium priority
- already reviewed
- remapping available
- revision completed
- not eligible

## Manual Actions
- **single supervisor review:** `True`
- **bounded batch review:** `True`
- **guided remapping:** `True`
- **automatic action:** `False`

## Verification
- **frontend tests:** `npm run test:auth passed 30 tests`
- **frontend build:** `npm run build passed; 1,586 modules transformed`
- **focused backend:** `orchestration policy/orchestrator/review API passed 46 tests`
- **supervisor discovery:** `152 tests passed`
- **mapping ownership admin:** `69 tests passed`
- **full backend:** `1,243 tests passed in 32.062 seconds`
- **app import:** `app_import_ok 81`

## Recommended Next Feature
- `Feature #18F-G-D - Run end-to-end Supervisor orchestration queue smoke and UX calibration`
