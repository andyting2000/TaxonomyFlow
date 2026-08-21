# Supervisor-guided remapping - #18F-G-A

Status: implemented; manual revised-mapping quality smoke remains pending.

## Copy changes

- `Run live Supervisor reviews for all` -> `Run Supervisor reviews for all`
- `Run live Supervisor review` -> `Run Supervisor review`

## Workflow

The initial suggestion and completed Supervisor review remain unchanged. An eligible review can expose the explicit `Re-run mapping with Supervisor feedback` action. The result is stored as a separate advisory revision and still requires human review.

There is no automatic Supervisor-to-mapper run and no mapper-to-Supervisor recursion.

## Persistence

Revisions use `supervisor_guided_mapping_revisions`. The dedicated table preserves the initial suggestion and makes the default one-attempt retry limit durable.

## Verification

- Focused correction tests: 14
- Supervisor pattern tests: 117
- Mapper tests: 34
- Ownership tests: 18
- Admin tests: 9
- Frontend tests: 26
- Frontend build: passed
- Full backend tests: 1182

## Next

Run one approved manual correction smoke. If quality is acceptable, proceed to #18F-G-B design. If quality is weak, select #18F-G-A-hotfix-1.
