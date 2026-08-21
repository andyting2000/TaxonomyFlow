# Supervisor Correction Action Alignment Hotfix 2b

Status: **passed**

## Root Cause

The secondary correction row was outside the summary/primary-action header row. As a full-width sibling, it aligned beneath the complete header instead of beneath the primary controls.

## Corrected Structure

The suggestion header is now an explicit responsive grid:

- `suggestion-card-summary` contains badges, row label, page, and value metadata.
- `suggestion-action-column` contains `suggestion-primary-actions`.
- The conditional `suggestion-secondary-actions` is nested immediately after the primary actions in that same action column.

The rerun button and `Correction attempt 1 completed` badge therefore occupy the same compact position. When neither state applies, no secondary container is rendered.

## Layout Rules

- Header: `grid min-w-0 gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start`
- Action column: `flex min-w-0 max-w-full flex-col items-end gap-2`
- Action rows: wrapping, end-aligned flex containers with `max-w-full`
- Secondary row: `min-h-0`; no `w-full`, full-row grid placement, or added vertical margin

Below the `sm` breakpoint the grid becomes one column, allowing the action column to stack below the summary. Both action rows remain end-aligned and can wrap without overflowing.

## Verification

- `npm run test:auth`: **26 passed**
- `npm run build`: **passed**, 1,585 modules transformed

The first build attempt was blocked by sandbox access to the Vite config. The approved unsandboxed rerun passed.

No Supervisor, mapping, correction eligibility, persistence, retry, auto-apply, or final-mapping behavior changed.
