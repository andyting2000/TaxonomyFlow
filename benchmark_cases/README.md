# Representative Benchmark Cases

Feature #13I is a planning and runbook step. It does not upload PDFs, mutate the database, change extraction, change mapping, generate XBRL, run Arelle, or modify production behavior.

The user has seven PDFs available, and most are OCR/scanned or OCR-heavy. Use this directory to plan the representative benchmark set and to keep private local notes outside version control.

## Required 7-PDF Layout

| Case ID | Category | Purpose | Benchmark Role |
| --- | --- | --- | --- |
| `standard_text_native_01` | `standard_text_native` | Clear text-native baseline with normal financial statements. | `primary_benchmark` |
| `ocr_clean_01` | `ocr_clean` | OCR/scanned but readable. | `ocr_benchmark` |
| `ocr_poor_quality_01` | `ocr_poor_quality` | Blurry, skewed, shadowed, small text, or inconsistent OCR. | `ocr_benchmark` |
| `complex_table_01` | `complex_table` | Dense tables, multi-year columns, totals/subtotals, continuation pages. | `primary_benchmark` |
| `notes_heavy_01` | `notes_heavy` | Notes, schedules, company-name-like detail rows, receivables/payables. | `primary_benchmark` |
| `customer_like_01` | `customer_like` | Closest to expected real customer upload. | `holdout` |
| `edge_case_01` | `edge_case` | Unusual formatting, mixed scan/text, mixed language, or messy layout. | `stress_edge` |

Job 11 can remain an existing benchmark candidate. Job 9 is smoke-test-only and must not be used as benchmark ground truth.

## Benchmark vs Few-Shot Policy

Do not use the same PDF pages as both prompt examples and benchmark evaluation targets without explicit labeling. That creates benchmark leakage.

Recommended for the current seven PDFs:

1. Use all seven PDFs as benchmark/holdout first.
2. Record the first benchmark result before using any page as a few-shot example.
3. Later choose only one or two small, manually verified snippets as few-shot candidates.
4. Exclude those exact pages from future holdout scoring.
5. Keep at least three to five PDFs/pages as holdout evaluation cases.

Alternative split:

1. Use five PDFs as benchmark/holdout.
2. Reserve two PDFs or selected pages as future few-shot candidates.
3. Do not evaluate few-shot improvements on the exact examples used in prompts.

Because only seven PDFs are available now, benchmark-first is preferred.

## Start The Local App

Start infrastructure:

```powershell
docker compose up -d db redis
python -B db_init.py --apply
```

Start the backend:

```powershell
uvicorn main:app --host 0.0.0.0 --port 8001
```

Start the worker in a second terminal:

```powershell
python -B start_celery.py
```

Use either the built app or Vite dev app:

```powershell
Set-Location frontend
npm run dev
```

Open:

- Built app: `http://localhost:8001/app`
- Vite app: `http://localhost:5173/`

## Upload Checklist

Upload each of the seven PDFs through `/app`.

For each upload, record:

- `case_id`
- `category`
- `benchmark_role`
- original PDF category
- `job_id`
- company name used
- registration number used
- financial year end used
- whether the PDF is text-native, OCR, scanned, or mixed
- whether the job reached `REVIEW`
- observed page count
- notes about scan quality, table complexity, or known issues

Use `benchmark_manifest.local.example.json` as the local fill-in template. Copy it to `benchmark_manifest.local.json` for private local notes and do not commit private paths, names, or job IDs unless they are safe test data.

## Benchmark Commands

Existing job 11 only:

```powershell
python -B scripts/benchmark_extraction_mapping.py --jobs 11 --markdown
```

Seven-PDF representative set plus job 11:

```powershell
python -B scripts/benchmark_extraction_mapping.py --jobs 11 12 13 14 15 16 17 18 --markdown
```

Seven-PDF set plus Job 9 smoke test:

```powershell
python -B scripts/benchmark_extraction_mapping.py --jobs 9 11 12 13 14 15 16 17 18 --include-job-9 --markdown
```

Optional existing generated-XBRL/Arelle context:

```powershell
python -B scripts/benchmark_extraction_mapping.py --jobs 11 12 13 14 15 16 17 18 --markdown --with-xbrl-audit --with-arelle-baseline
```

The optional command only summarizes existing generated-XBRL/Arelle artifacts. The benchmark harness does not generate XBRL, run Arelle, or mutate the database.

## Acceptance Policy Before Prototype Work

Minimum before a new extraction architecture prototype:

- At least three `benchmark_candidate` jobs, excluding Job 9.

Preferred before a prototype:

- Five `benchmark_candidate` jobs.

For the current seven PDFs:

- Upload and benchmark all seven if possible.
- Keep at least three to five PDFs/pages as holdout.
- Keep Job 9 smoke-test-only.
- Do not optimize extraction/mapping architecture around one PDF.
- Do not evaluate few-shot improvements on the same examples used inside the few-shot prompt.
- Do not cut over any new extraction architecture until current vs new comparison exists on the representative benchmark set.

## Reading Benchmark Metrics

- Rows extracted: high or low alone does not prove correctness.
- `template_field_id` coverage: useful, but wrong mappings can still look covered.
- `confirmed_tag_id` coverage: usually zero before human review.
- Blank `statement_type`: should be near zero for fresh jobs.
- Unmapped rate: high values mean mapping or candidate generation needs work.
- Duplicate labels: can mean extraction duplication or legitimate repeated financial rows.
- Suspicious signed values: manual-review signal, not automatic error.
- Company-name-like rows: important for receivable/payable guardrails.
- Arelle baseline: structural signal only, not submission-ready proof.

## Future Ground Truth

Ground truth is not required in Feature #13I. Add it later after the seven PDFs are uploaded and manually reviewed.

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

Few-shot examples are not the same as ground truth. Few-shot examples teach output style. Ground truth evaluates correctness.

## Future Few-Shot Examples

Use `few_shot_examples.example.json` as the schema only. Future few-shot examples should be:

- manually verified
- small and high quality
- stripped of unnecessary confidential data
- excluded from benchmark scoring if used in prompts
- row/table snippets with expected JSON output, not entire PDFs
