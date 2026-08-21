# Ranked Candidate Dry-Run Smoke - #18F-F

The default frontend flag remains false, so the panel is absent from normal UI builds. With the flag enabled in a test build, it loads capability metadata. A disabled backend returns capability metadata with `enabled=false`; the UI shows a fail-closed notice and has no run control.

The backend smoke test applies temporary unittest-only flags, calls capabilities, then posts `mode=dry_run`, `profile=balanced`, and a capped candidate count. The response is completed advisory evidence only. Production defaults were not enabled.

Recommended next feature: #18F-G - Decide next path: persistence design vs reviewer UX workflow.
