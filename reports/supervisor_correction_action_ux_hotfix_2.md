# Supervisor Correction Action UX Hotfix 2

## Result

The correction control now occupies a compact, right-aligned secondary action row directly beneath the primary Accept, Reject, and Run Supervisor review controls.

The row renders only when a correction action is relevant or a completed correction status exists. A completed revision displays `Correction attempt N completed` in the same position. No empty secondary row is reserved.

## Confirmations

- Single **Run Supervisor review** starts immediately without `window.confirm`.
- Single **Re-run mapping with Supervisor feedback** starts immediately without `window.confirm`.
- Batch **Run Supervisor reviews for all** still uses `confirmBatchSupervisorRun`.

## Pending Protection

Both single actions use a per-suggestion pending `Set` before the React state update, preventing a rapid repeated click from issuing a duplicate request.

- Supervisor loading label: `Running Supervisor review...`
- Correction loading label: `Re-running mapping...`
- Existing busy states disable the active button.
- `finally` clears both the pending guard and visual busy state after success or failure.
- Backend correction eligibility and the one-attempt durable retry limit are unchanged.

## Safety

No backend, mapping, Supervisor, eligibility, persistence, or retry logic changed. Revisions remain advisory, human-review-required, and never safe for auto-apply. No automatic Accept/Reject or mapping mutation was added.

## Verification

- Frontend source tests: 26 passed
- Frontend production build: passed, 1,585 modules transformed
- Supervisor backend discovery: 118 passed

The initial sandboxed build could not access the Vite/esbuild path; the approved unsandboxed rerun passed.
