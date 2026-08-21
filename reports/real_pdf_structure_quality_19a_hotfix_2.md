# Real-PDF structure quality #19A-hotfix-2

Implementation status: **PASS**. Fresh real-PDF smoke status: **PENDING**.

## Job 66 evidence

Job 66 v2 detected all nine TOC entries but selected two cover/generic Tier C/D anchors. Alignment confidence was `0.7047`, review was required, Notes was incorrectly stored at PDF `0-0`, and only 512 of 2,229 evidence items were assigned (`0.229699`); 1,717 were unassigned and none were dropped.

The Job 66 regression fixture now selects five exact and four canonical-prefix anchors, all in the +1 regime. Weighted +1 support is `8.56`, alignment confidence is `0.9884`, review is false, weaker-selection and off-regime counts are zero, all nine ranges resolve, and Notes is PDF `16-23`. Assignment is 40/60 overall and 40/50 after excluding ten TOC items: `0.80`, with zero drops. Nine Notes children occur only on pages 16-23 and none leave the parent range.

A separate read-only projection of the immutable Job 66 v2 evidence through corrected PDF ranges 2-23 assigns an estimated 1,699/2,229 items (`0.762225`), or `0.798027` after excluding 100 TOC items. That is a diagnostic estimate, not a fresh v3 result; it is included only to show that the corrected ranges materially improve body assignment rather than narrowly beating the old 77% unassigned rate.

The evaluator now reports selected exact/prefix/alias/fuzzy/partial counts, stronger-alternative inversions, off-regime anchors, mapping conflicts, explicit/resolved range projections, TOC-excluded assignment, actual Notes range, Notes child-page distribution, out-of-parent children, and dropped evidence. Hard gates require zero inversions, zero unresolved range conflicts, a current classification with zero out-of-parent Notes children, and zero drops.

The structure artifact is versioned `19A-v3` as `structure_19a_v3.json`; v2 cannot masquerade as current, and downstream #19B/#19C source-version/hash checks invalidate stale dependents. Running the evaluator against unchanged Job 66 returns the structured `current_structure_artifact_unavailable` failure with exit code 2, as intended.

Verification passed: 75 focused #19A tests, 68 combined downstream #19B/#19C tests, 113 affected extraction/task/API/ownership tests, and all 1,430 backend tests. Changed Python compiled, the app imported with 89 routes, and the 24-template registry validated with semantic hash `16de7eaeafcdf760c7f4869072a6b0a3925088f6bc260672389b5c502015b7d4`.

No live Azure DI or LLM call, Supervisor action, database/source-row mutation, mapping mutation, template/confirmed-tag/final-state mutation, frontend change, XBRL generation, or Arelle run occurred.

## Fresh-PDF rerun

1. Preserve Job 66 and upload the same PDF as a new authenticated filing through `POST /api/v1/filings/upload`; do not use the legacy protected reprocess route.
2. Run the normal Celery Azure-DI workflow with #19A/#19B/#19C analysis and persistence enabled, deterministic initial mapping, and both live #19B/#19C LLM flags false.
3. Poll `GET /api/v1/filings/jobs/{new_job_id}/status` to terminal success.
4. Confirm `structure_19a_v3.json`, `template_classification_19b_v1.json`, and `initial_mapping_19c_v1.json` exist and have current version/hash linkage.
5. Run `.\.venv\Scripts\python.exe -B scripts\report_toc_aware_real_pdf_smoke.py {new_job_id}` and require every hard gate to pass.

The real-PDF status remains pending until those steps are completed on a new job. #19C-hotfix-1 and #19D have not been started.
