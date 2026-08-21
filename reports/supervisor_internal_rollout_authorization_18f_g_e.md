# Supervisor Internal Rollout Authorization

**Status:** PASS

The repository has admin and normal-user roles but no reviewer/staff/analyst
role. The smallest safe boundary is the environment-configured
`SUPERVISOR_ORCHESTRATION_ALLOWED_USER_IDS` allowlist.

## Predicate

Access requires:

1. The relevant feature is enabled.
2. The existing filing ownership check passes.
3. The user is an admin or is explicitly allowlisted.

The allowlist contains comma-separated positive user IDs. Empty permits admins
only. Invalid entries fail closed. Capability APIs expose the authorization
source and allowlist count, not the IDs.

## Isolation

| User/job case | Result |
| --- | --- |
| Allowlisted reviewer, owned job | Allowed |
| Allowlisted reviewer, other user's job | 404 |
| Non-allowlisted normal owner | 403 |
| Normal user, other user's job | 404 |
| Admin, owned job | Existing admin policy |
| Admin cross-user bypass | Not granted |
| Feature disabled | 403 |

The boundary covers orchestration planning, explicit live review, and explicit
guided correction. Seven focused authorization tests, 18 ownership tests, 30
auth tests, 9 admin tests, and the 1,266-test full suite passed.
