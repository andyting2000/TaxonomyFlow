# TOC-aware structure foundation #19A

Status: **PASS**

## Architecture

The optional analyzer runs in `process_azure_di_filing_job` after usable Azure DI normalization and before existing row persistence/mapping. It uses the transient Azure layout while the current deterministic mapping path continues with the same normalized candidates. Persisted extracted-row UUIDs are attached after the existing commit, and the artifact is published only when the job reaches `REVIEW`.

Azure and existing database page numbers are 1-based. The new `pdf_page_index` is 0-based. Printed page numbers and labels are separate values resolved through heading anchors.

All three flags default to false:

- `TOC_AWARE_PIPELINE_ENABLED`
- `TOC_AWARE_STRUCTURE_PERSISTENCE_ENABLED`
- `TOC_AWARE_LLM_FALLBACK_ENABLED`

The last flag is reserved. #19A has no LLM fallback implementation and makes no model call.

## Contracts and persistence

The typed result includes TOC entries, selected and alternate heading-anchor evidence, Roman/Arabic-aware page mappings, primary sections, explicit ambiguous/unassigned dispositions, and a bounded `DocumentContentEvidence` catalog. The catalog makes every artifact-scoped paragraph, line, table, cell, and normalized-row reference resolvable without copying the complete Azure response.

The artifact path is:

`uploads/document-structures/job_{job_id}/structure_19a_v1.json`

It is limited to 25 MiB, schema/identity validated, written through atomic replace, ignored by Git, included in job/account cleanup, and invalidated at the start of every extraction retry. A fixed job/version path prevents duplicate records. A later phase may replace it with a job-owned database artifact or normalized tables.

## API and compatibility

Owned read-only endpoints:

- `GET /api/v1/filings/jobs/{job_id}/document-structure/capabilities`
- `GET /api/v1/filings/jobs/{job_id}/document-structure`

Only owned jobs in `REVIEW` or `COMPLETED` can expose a valid artifact. There is no frontend route or new normal-user panel.

Disabled mode makes no analyzer or writer call. Retry cleanup may remove an obsolete derived artifact, but existing extraction rows, statement/template assignments, suggestions, Supervisor data, confirmations, and final mappings are unchanged.

## Sample

Fixture D detected its TOC at PDF index 1 and reconciled three anchors to offset `+2` with confidence `0.98`. It produced:

- Directors' Report: printed 1–2 → PDF indexes 3–4
- Statement of Financial Position: printed 3 → PDF index 5
- Notes: printed 4–5 → PDF indexes 6–7

All 9 inventoried content records have evidence and a terminal disposition; dropped content is zero.

## Verification

- #19A focused suites: 51 passed
- Full backend discovery: 1,317 passed
- Changed-file compilation: passed
- App import: passed, 83 routes
- Four report JSON files: validated
- Frontend build: not required; no frontend files changed

Recommended next: **#19B — classify primary sections and note subsections into the 24 internal template groups.**
