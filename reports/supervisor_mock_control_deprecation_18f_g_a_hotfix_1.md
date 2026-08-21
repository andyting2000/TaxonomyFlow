# Supervisor Mock Control Deprecation - #18F-G-A-hotfix-1

Status: completed on 2026-07-22.

## Frontend Decision

The application no longer renders `Run mock Supervisor review` or `Run mock Supervisor reviews for all`. The visible controls are `Run Supervisor review` and `Run Supervisor reviews for all`, gated by the existing live-control frontend flag and authoritative backend checks.

`VITE_SHOW_SUPERVISOR_MOCK_CONTROLS=false` remains in `frontend/.env.example` as a deprecated compatibility setting. It cannot expose a mock control because the mock UI wiring has been removed.

## Backend Mock Retention

Backend mock execution remains available for tests and safe omitted-mode requests. No backend mock service or endpoint behavior was removed.

## Default Mode

`SUPERVISOR_PRODUCTION_LIVE_DEFAULT_MODE=mock` is currently a legacy compatibility setting with no request-selection effect. The HTTP request schemas directly default omitted mode values to `mock`. A regression test proved that an omitted-mode request still used `source=mock` even when the legacy setting was patched to `live`.

A future, separately scoped config cleanup should either rename this concept to `SUPERVISOR_DEFAULT_MODE=mock` and wire it deliberately or remove the unused setting after compatibility review. No broad config migration was performed here.

## Explicit Live Path

- The visible single control calls `onRunSupervisorReview(suggestion, "live")`.
- The visible batch control calls `onRunBatchSupervisorReviews("live")`.
- The handler requires confirmation, normalizes the explicit mode, and passes it to the API helper.
- The API helper serializes the mode in the POST body.
- Backend live feature flags and permissions remain authoritative.

## Verification

- Frontend tests: 26 passed.
- Supervisor tests: 118 passed.
- Full backend suite: 1,183 passed.
- Production frontend build: passed.

No automatic action, mapping mutation, `confirmed_tag_id` change, correction behavior change, or production live-gate change occurred.

## Next Feature

After 3-5 manual correction-quality smoke cases: `#18F-G-B - Integrate conditional Supervisor-guided remapping into the production orchestration design`.
