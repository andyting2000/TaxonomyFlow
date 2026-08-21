# Runtime Backend Provenance Blocker 18F-G-D

## Outcome

The mismatch is confirmed as a stale-process/runtime ownership problem, not a local source import problem.

- `127.0.0.1:8001` is owned by the older PID 15212 process started on 2026-07-24.
- The newer `python main.py` process owns a separate `0.0.0.0:8001` listener under PID 9152.
- Requests to the smoke URL reached the older loopback-specific listener, whose OpenAPI remains pre-hotfix.
- Classification: **D, wrong FastAPI process owns the expected port**, and **F, old process was never replaced**.

A separate confirmed startup defect also existed: `python main.py` ran the file as `__main__`, then `uvicorn.run("main:app")` imported it again as `main`. This created distinct module and app objects. That defect has been removed, but it was not the direct cause of the stale endpoint because a separate older process owned the exact URL.

## `main.py` Startup

`main.py` directly creates the FastAPI app. It does not use an app factory or import another backend app.

Before this blocker:

```python
uvicorn.run("main:app", reload=settings.debug, ...)
```

The bounded diagnostic confirmed that `__main__` and imported `main` were different module objects and their `app` values were different objects.

After reconciliation:

```python
uvicorn.run(app, reload=False, ...)
```

No workers are configured. The source does not change cwd or `sys.path`. Dotenv loading does not alter import paths. Script-mode reload is disabled because Uvicorn requires an import string for reload; development reload can use an explicit module-mode Uvicorn command on a non-conflicting port when needed.

## Local Provenance

- cwd: `C:\Users\andyt\Documents\Workspace\taxonomy-flow`
- Python: `C:\Users\andyt\Documents\Workspace\taxonomy-flow\.venv\Scripts\python.exe`
- virtual environment: `C:\Users\andyt\Documents\Workspace\taxonomy-flow\.venv`
- base Python: `C:\Program Files\Python311`
- `PYTHONPATH`: unset

All inspected project modules resolve under the expected workspace:

- `main`: `...\taxonomy-flow\main.py`
- `routers.filings`: `...\taxonomy-flow\routers\filings.py`
- policy: `...\taxonomy-flow\services\supervisor_orchestration_policy.py`
- orchestrator: `...\taxonomy-flow\services\supervisor_mapping_orchestrator.py`
- actionability: `...\taxonomy-flow\services\suggestion_actionability.py`
- schemas: `...\taxonomy-flow\schemas.py`

No duplicate project `main.py`, editable project install, `PYTHONPATH` override, installed project shadow, or unexpected project module path was found.

## Live Processes

Observed listeners:

| Address | PID | Parent | Created | Command |
|---|---:|---:|---|---|
| `0.0.0.0:8001` | 9152 | 5604 | 2026-07-25 22:49:41 +08 | `C:\Program Files\Python311\python.exe main.py` |
| `127.0.0.1:8001` | 15212 | 13972 | 2026-07-24 23:50:06 +08 | `C:\Program Files\Python311\python.exe -B -m uvicorn main:app --host 127.0.0.1 --port 8001` |

Both parent commands use the expected workspace virtual-environment launcher. The child executable being the base Python executable is normal for this Windows venv launcher. The bounded CIM query could not obtain process cwd, so no live cwd claim is made.

## OpenAPI Comparison

Local `main.app.openapi()` contains every canonical field below. Live `http://127.0.0.1:8001/openapi.json` contains none of them:

- `policy_eligible_count`
- `review_executable_count`
- `remapping_eligible_count`
- `remapping_executable_count`
- `revision_completed_count`
- `mapper_status`
- `is_human_terminal`
- `supervisor_review_executable`
- `batch_review_executable`
- `remapping_eligible`
- `remapping_executable`

The live health response also lacks the new runtime marker. This is definitive runtime-code mismatch evidence.

## Source Hardening

- `main.py` now passes the existing app object to Uvicorn.
- Startup logs non-secret PID, cwd, Python executable, and key module paths.
- `/health` exposes `runtime_revision: "18F-G-D-hotfix-1+"`.
- Five focused startup/provenance tests cover import safety, app-object startup, module provenance, route/schema registration, and safe health output.
- No Supervisor orchestration business logic changed.

## User Restart Procedure

1. Recheck current listeners:

   ```powershell
   netstat -ano -p TCP | Select-String ':8001'
   ```

2. Stop both user-managed backend process trees listening on port 8001. At observation time they were parent/child `13972/15212` and `5604/9152`; verify the PIDs before acting.
3. Start exactly one backend from the repository root:

   ```powershell
   cd C:\Users\andyt\Documents\Workspace\taxonomy-flow
   .\.venv\Scripts\python.exe main.py
   ```

4. Do not run a second `python -m uvicorn main:app` process on port 8001.
5. Confirm `/health` returns:

   ```json
   {
     "runtime_revision": "18F-G-D-hotfix-1+"
   }
   ```

## Post-Restart Gate

Before resuming the smoke, live OpenAPI and plan responses must expose all canonical top-level and item fields listed above. Only then should `#18F-G-D-resume` continue.

`#18F-G-D` and `#18F-G-D-resume` remain blocked. The recommended next feature is `#18F-G-D-runtime-preflight`, not `#18F-G-E`.

## Verification

- Runtime provenance tests: 5 passed.
- Focused orchestration regressions: 52 passed.
- Full backend suite: 1,254 passed in 40.746 seconds.
- App import: `app_import_ok 81 18F-G-D-hotfix-1+`.
- The agent did not start, stop, restart, or kill any service.
