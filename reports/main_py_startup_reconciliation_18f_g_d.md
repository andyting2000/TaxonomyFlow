# `main.py` Startup Reconciliation 18F-G-D

## Confirmed Defect

The previous script startup loaded `main.py` twice:

1. `python main.py` executed the file under module name `__main__`.
2. `uvicorn.run("main:app")` imported the file again under module name `main`.

A bounded diagnostic confirmed:

- same module: `false`
- same app: `false`
- `__main__` app matches imported `main.app`: `false`

This can create distinct FastAPI apps, repeat module-level initialization, and obscure runtime identity. It did not directly cause the stale endpoint in this incident because an older separate process owned `127.0.0.1:8001`.

## Reconciled Design

The repository keeps its established `python main.py` entrypoint and passes the existing app:

```python
if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8001,
        reload=False,
        access_log=True,
        log_level="info" if not settings.debug else "debug",
    )
```

This removes the self-import. No app factory or worker configuration was added. Reload is disabled for script-mode app-object startup.

## Provenance Marker

`APP_RUNTIME_REVISION` is `18F-G-D-hotfix-1+`.

Startup logs now include non-secret runtime provenance. `/health` exposes only the revision marker, not filesystem paths, Python paths, environment values, credentials, or database URLs.

## Verification

- `tests.test_runtime_startup_provenance`: 5 passed.
- Focused orchestration regressions: 52 passed.
- Full backend discovery: 1,254 passed.
- App import: `app_import_ok 81 18F-G-D-hotfix-1+`.

The canonical restart command is:

```powershell
.\.venv\Scripts\python.exe main.py
```

Service lifecycle remains user-managed. The next bounded preflight must verify the health marker and canonical OpenAPI fields before `#18F-G-D-resume` can continue.
