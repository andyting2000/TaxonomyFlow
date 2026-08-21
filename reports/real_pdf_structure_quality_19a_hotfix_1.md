# Real-PDF structure quality #19A-hotfix-1

Implementation status: **PASS**. Live Job 65 smoke: **NOT RERUN**.

## What is proven

The deterministic Job 65-style regression now yields nine credible TOC entries, nine trusted anchors, dominant Arabic offset `+1`, `0.98` alignment confidence, and no human-review flag. Printed Notes pages `15-22` map to PDF indexes `16-23` and contain ten evidence references.

All 45 evidence items are conserved: 28 assigned, zero ambiguous, 17 unassigned, and zero dropped. The resulting assignment and unassigned rates are `0.622222` and `0.377778`. No suspicious TOC entry or excessive-unassigned warning is emitted for the fixture.

This is not represented as a fresh real-document result. The workspace contains legacy Job 65 `19A-v1`, `19B-v1`, and `19C-v1` artifacts, but no new `19A-v2` output. The v2 loader intentionally refuses the old structure artifact.

## Artifact and downstream safety

The structure contract is now `19A-v2` in `structure_19a_v2.json`. #19B validates its source structure version/hash and registry hash. #19C validates structure, classification, and registry identities. Processing retries discard #19A, #19B, and #19C artifacts before rebuilding, so dependent results cannot silently survive a changed structure identity.

The read-only evaluator is:

```powershell
.\.venv\Scripts\python.exe -B scripts\report_toc_aware_real_pdf_smoke.py 65
```

It reads validated artifacts, prints JSON to stdout, and makes no provider call, file write, or database write. It reports TOC quality, anchor trust, weighted offsets, conservation rates, Notes evidence, #19B classification/Notes conservation, and #19C linkage/leakage/mutation metrics when current downstream artifacts exist.

## Exact live rerun sequence

1. Use the current deterministic smoke configuration and verify these effective settings before starting/restarting the API and Celery worker: `EXTRACTION_PIPELINE=azure_di`; all of `TOC_AWARE_PIPELINE_ENABLED`, `TOC_AWARE_STRUCTURE_PERSISTENCE_ENABLED`, `TOC_AWARE_TEMPLATE_CLASSIFICATION_ENABLED`, `TOC_AWARE_TEMPLATE_CLASSIFICATION_PERSISTENCE_ENABLED`, `TOC_AWARE_TAXONOMY_CANDIDATE_RETRIEVAL_ENABLED`, `TOC_AWARE_INITIAL_MAPPING_ENABLED`, and `TOC_AWARE_INITIAL_MAPPING_PERSISTENCE_ENABLED` are `true`; `TOC_AWARE_LLM_FALLBACK_ENABLED`, `TOC_AWARE_TEMPLATE_CLASSIFICATION_LIVE_LLM_ENABLED`, and `TOC_AWARE_INITIAL_MAPPING_LIVE_LLM_ENABLED` are `false`; and `TOC_AWARE_INITIAL_MAPPING_MODE=deterministic_only`. No new `.env` values are required by the hotfix.
2. Preserve Job 65 and upload the same source PDF as a fresh job through the normal authenticated Azure-DI/Celery workflow. In PowerShell, after setting `$token`, `$pdfPath`, `$companyName`, `$registrationNumber`, and `$financialYearEnd` to the Job 65 source metadata, run:

   ```powershell
   $response = curl.exe -sS -X POST "http://localhost:8000/api/v1/filings/upload" `
     -H "Authorization: Bearer $token" `
     -F "company_name=$companyName" `
     -F "registration_number=$registrationNumber" `
     -F "financial_year_end=$financialYearEnd" `
     -F "file=@$pdfPath;type=application/pdf"
   $job = $response | ConvertFrom-Json
   $jobId = $job.id
   $job
   ```

   This step makes an authorized live Azure call and creates database rows. It was deliberately not run during automated verification. The existing `POST /api/v1/jobs/65/reprocess` route invokes the legacy background processor, so it is not the correct #19A-v2 smoke path.
3. Poll the owned status endpoint until it reaches the terminal review/completed state:

   ```powershell
   curl.exe -sS "http://localhost:8000/api/v1/filings/jobs/$jobId/status" `
     -H "Authorization: Bearer $token"
   ```

   Confirm `uploads/document-structures/job_$jobId/structure_19a_v2.json` exists with freshly generated dependent #19B/#19C artifacts.
4. Run the read-only evaluator for the new ID and preserve its JSON stdout:

   ```powershell
   .\.venv\Scripts\python.exe -B scripts\report_toc_aware_real_pdf_smoke.py $jobId
   ```

5. Treat the live smoke as passing only when suspicious TOC entries and dropped evidence are zero, Notes has evidence, alignment is not review-required, and the quality gate returns `pass: true`. Investigate `excessive_unassigned_content` rather than suppressing it.

## Verification and scope

Verification passed: 65 focused #19A tests, 61 downstream #19B/#19C tests, 118 affected extraction/task/ownership/API tests, all 1,420 backend tests in 51.574 seconds, changed-file compilation, application import with 89 routes, and the 24-template canonical-registry check with zero errors.

No live Azure DI, LLM, Supervisor, database, mapping, frontend, XBRL, or Arelle action occurred.
