# Feature #13I: Representative 7-PDF Benchmark Set Plan

Date: 2026-05-05

## Executive Summary

Feature #13H created the read-only benchmark harness. Feature #13I defines the dataset plan and runbook for using it with seven representative PDFs before any extraction architecture rewrite.

The user has seven PDFs available, and most are OCR/scanned or OCR-heavy. That is useful: the next extraction architecture must be measured against native text, clean OCR, poor OCR, dense tables, notes-heavy filings, customer-like uploads, and edge cases.

No PDFs are uploaded by this feature. No private files or customer data are added to the repository.

## Why We Need Seven PDFs

One benchmark candidate is not enough. Job 11 is useful, but it should not drive the architecture alone. Job 9 is smoke-test-only and must not be treated as benchmark ground truth.

The seven-PDF set should cover:

1. `standard_text_native_01`: clear text-native baseline.
2. `ocr_clean_01`: scanned/OCR-heavy but readable.
3. `ocr_poor_quality_01`: blurry, skewed, shadowed, small text, or inconsistent OCR.
4. `complex_table_01`: dense tables, multi-year columns, subtotals/totals, continuation pages.
5. `notes_heavy_01`: notes, schedules, company-name-like rows, receivables/payables.
6. `customer_like_01`: closest to expected real customer upload.
7. `edge_case_01`: unusual formatting, mixed scan/text, mixed language, or messy layout.

## OCR-Heavy PDF Value

OCR-heavy PDFs are important because the proposed architecture must decide when native text is unreliable and when OpenAI vision or layout reasoning is justified. Clean OCR and poor OCR should be separate cases because they stress different failure modes.

Clean OCR tests whether the pipeline can process readable scanned filings.

Poor OCR tests whether the pipeline fails transparently, avoids inventing rows, and provides enough evidence for review.

## What To Choose

Use the closest available PDF for each category. If a perfect text-native PDF is not available, still keep the category in the manifest and mark it as unavailable or substituted in local notes.

For `customer_like_01`, prefer the PDF most similar to expected production uploads. Keep it as holdout if possible.

For `edge_case_01`, choose the most difficult or unusual PDF, but do not make it the primary success criterion.

## Benchmark vs Few-Shot Separation

The same PDFs or pages should not be used as both prompt examples and benchmark evaluation targets without explicit labeling. That creates benchmark leakage.

Recommended policy for the current seven PDFs:

1. Use all seven PDFs as benchmark/holdout first.
2. Record the initial benchmark result.
3. Later select only one or two small, manually verified snippets as few-shot examples.
4. Exclude those exact pages from future holdout scoring.
5. Keep at least three to five PDFs/pages as holdout evaluation cases.

Alternative policy:

1. Use five PDFs as benchmark/holdout.
2. Reserve two PDFs or selected pages as future few-shot candidates.
3. Do not evaluate few-shot improvements on the exact examples used in prompts.

Since only seven PDFs are available now, benchmark-first is the safer path.

## Upload Runbook

Start infrastructure:

```powershell
docker compose up -d db redis
python -B db_init.py --apply
```

Start the backend:

```powershell
uvicorn main:app --host 0.0.0.0 --port 8001
```

Start the worker:

```powershell
python -B start_celery.py
```

Open `/app`:

```text
http://localhost:8001/app
```

Upload all seven PDFs through the app. For each upload, record:

- case ID
- category
- benchmark role
- job ID
- company name used
- registration number used
- financial year end used
- whether it is text-native, OCR, scanned, or mixed
- whether it reached `REVIEW`
- observed page count
- notes on scan quality, table complexity, or known issues

Use:

- `benchmark_cases/benchmark_manifest.example.json`
- `benchmark_cases/benchmark_manifest.local.example.json`

The local manifest is for private local job IDs and notes. Do not commit real private paths or customer data.

## Commands To Run

Existing job 11:

```powershell
python -B scripts/benchmark_extraction_mapping.py --jobs 11 --markdown
```

Seven-PDF set plus job 11:

```powershell
python -B scripts/benchmark_extraction_mapping.py --jobs 11 12 13 14 15 16 17 18 --markdown
```

Seven-PDF set plus Job 9 smoke test:

```powershell
python -B scripts/benchmark_extraction_mapping.py --jobs 9 11 12 13 14 15 16 17 18 --include-job-9 --markdown
```

Optional existing XBRL/Arelle context:

```powershell
python -B scripts/benchmark_extraction_mapping.py --jobs 11 12 13 14 15 16 17 18 --markdown --with-xbrl-audit --with-arelle-baseline
```

The optional command does not generate XBRL or run Arelle. It only summarizes existing artifacts if present.

## How To Interpret Results

Rows extracted: high or low alone does not prove correctness.

`template_field_id` coverage: useful, but can hide wrong mappings.

`confirmed_tag_id` coverage: usually zero before human review.

Blank `statement_type`: should be near zero for fresh jobs.

Unmapped rate: high means mapping/candidate generation needs work.

Duplicate labels: may indicate extraction duplication or legitimate repeated rows.

Suspicious signed values: manual review signal, not automatic error.

Company-name-like rows: important for receivable/payable guardrails.

Arelle baseline: structural signal only, not submission-ready proof.

## Future Few-Shot Planning

Use `benchmark_cases/few_shot_examples.example.json` as a schema only.

Few-shot examples should be:

- manually verified
- small snippets, not entire PDFs
- stripped of unnecessary confidential data
- excluded from benchmark scoring if used in prompts
- represented as row/table snippets with expected JSON output

Few-shot examples teach output style. Ground truth evaluates correctness. Keep those files and roles separate.

## Future Ground Truth

Ground truth is not required in Feature #13I. Add it later after the representative PDFs are uploaded and reviewed manually.

Proposed path:

```text
benchmark_cases/<case_id>/expected_rows.json
```

Suggested fields:

- `expected_label`
- `expected_value`
- `expected_year`
- `expected_statement_type`
- `expected_row_type`
- `expected_concept_id` if known
- `required`
- `notes`
- `tolerance`

## What Comes After

Manual step: upload the seven PDFs through `/app` and record job IDs.

Recommended next feature after that manual step:

**Feature #13J Run representative 7-PDF benchmark set and analyze results.**

Do not start the side-by-side extraction prototype until at least three non-Job-9 benchmark candidates exist. Prefer five benchmark candidates.
