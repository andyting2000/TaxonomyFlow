# Supervisor Correction UX Cleanup - #18F-G-A-hotfix-1

Status: completed on 2026-07-22.

## Action Layout

Before, `Accept suggestion`, `Reject`, `Run Supervisor review`, and `Re-run mapping with Supervisor feedback` shared one crowded action row.

After:

- Primary right-aligned row: `Accept suggestion`, `Reject`, `Run Supervisor review`.
- Conditional secondary right-aligned row: `Re-run mapping with Supervisor feedback`.
- The secondary row is rendered only for an eligible completed Supervisor review under effective correction feature gates. No empty row or vertical space is emitted when ineligible.
- Both rows retain responsive flex wrapping.

After a completed bounded correction, the large disabled correction button is replaced by the compact status `Correction attempt {n} completed`. The retry limit was not changed.

## Revised Suggestion Copy

- Same qname: `Outcome: Original suggestion retained after Supervisor-guided review.`
- Changed qname: `What changed: {original qname} \u2192 {revised qname}`.
- The card continues to show the revised reason, addressed Supervisor issues, remaining ambiguities, correction attempt, human-review requirement, and not-applied/not-confirmed warning.

## Safety

This hotfix changed presentation and regression coverage only. It did not add automatic remapping, apply, accept, confirmation, `confirmed_tag_id` mutation, final mapping mutation, retries, persistence schema changes, XBRL generation, Arelle execution, or external provider calls.

## Verification

- Frontend `npm run test:auth`: 26 passed.
- Frontend `npm run build`: passed, 1,585 modules transformed.
- Supervisor tests: 118 passed.
- Qwen taxonomy mapping tests: 34 passed.
- Current mapping baseline tests: 8 passed.
- Full backend suite: 1,183 passed in 31.635 seconds.

## Next Feature

After 3-5 manual correction-quality smoke cases: `#18F-G-B - Integrate conditional Supervisor-guided remapping into the production orchestration design`.
