# Feature #13G Revised: Extraction and Mapping Architecture Audit

Date: 2026-05-05

## Executive Summary

The current OpenAI production extraction path works, but the architecture is fragile because extraction and mapping are coupled too early. The Stage 2 prompt asks the model to extract visible financial data and assign `template_code` / `concept_id` in the same response. `SmartAIProcessor` can then accept the model-supplied concept as a high-confidence mapping if it belongs to the selected template and passes narrow guardrails.

That design makes the pipeline hard to debug. A wrong row can be caused by page classification, text extraction, vision fallback, JSON parsing, model concept assignment, string matching, statement propagation, or XBRL generation policy. Those failures currently collapse into the same persisted row shape.

Recommended next step: **Feature #13H Multi-PDF extraction benchmark harness**. Do not switch the semantic matcher to OpenAI embeddings or redesign production extraction until the project can compare results across multiple representative PDFs. Job 9 should remain a smoke-test regression sample only, not the primary benchmark.

## Current Problem

The project now has:

- OpenAI as the active classification/text/vision extraction provider when `MODEL_PROVIDER=openai`.
- A shadow-only `semantic_embeddings` table with OpenAI `text-embedding-3-large` vectors for template-service concepts.
- Legacy Hugging Face embedding calls disabled in OpenAI mode.
- Existing XBRL generation from `confirmed_tag_id` or `template_field_id`.
- Deterministic readiness validation and an Arelle CLI wrapper.

The unstable part is the extraction/mapping boundary. The current page loop classifies a page, supplies one or more templates to the model, asks the model to extract rows and map them to exact concept IDs, then falls back to string/template matching if the model did not provide an accepted concept.

## Current Architecture Summary

Upload and job creation:
`routers/filings.py` creates a `FilingJob`, stores the PDF path, and starts `process_pdf_task`.

Processing:
`tasks.py` delegates to `SmartAIProcessor.process_pdf`.

Classification:
`SmartAIProcessor` first uses native text/layout heuristics. If no classification is found, `Stage1Classifier` calls OpenAI vision in OpenAI mode.

Stage 2 extraction:
`stage2_prompt_builder.py` builds a multi-template prompt. The prompt asks for visible data and exact template/concept assignment. `SmartAIProcessor` tries OpenAI text extraction first, then region VLM, then whole-page VLM.

Mapping:
`SmartAIProcessor._match_from_llm_concept` accepts a model-supplied `concept_id` when it belongs to the selected template and passes guardrails. Otherwise, `_semantic_match_to_template_field` calls `XBRLTemplateService.find_matching_concept_hybrid`. In OpenAI mode, production matching is currently string/template based because the OpenAI embedding store is not yet wired into production matching.

Persistence:
`ExtractedDataItem` stores page linkage, label, value, confidence, `statement_type`, `template_field_id`, `confirmed_tag_id`, review status, and validation flags. It does not store row-level source spans, bounding boxes, table coordinates, or extraction route provenance as first-class review evidence.

XBRL generation:
`xbrl_generator.py` uses `confirmed_tag_id` first, otherwise `template_field_id`, and rechecks guardrails before facts are created.

Validation:
`xbrl_validator.py` performs readiness validation. `arelle_validator.py` wraps deterministic Arelle CLI validation and local schemaRef handling.

## Why The Current Architecture Is Unstable

Key findings:

- Page classification can supply incomplete or wrong template context for pages with mixed statements or continuation sections.
- Text extraction loses table structure when native PDF text does not preserve rows, columns, and year headers.
- Vision fallback can produce rows without persisted source-cell evidence.
- Multi-year column handling is model-provided rather than tied to a deterministic table-column model.
- Negative/bracket sign normalization is prompt-driven rather than a separate evidence-backed normalization stage.
- Extraction and mapping are coupled: the model is asked to both read the document and choose XBRL concepts.
- Broad concept mapping remains possible when labels are short, generic, or company-specific.
- The review UI cannot yet show exact source evidence, bounding regions, top-k mapping suggestions, or guardrail reasons as first-class mapping-decision objects.
- Job 9 is too narrow and arbitrary to serve as the main benchmark.

## What To Keep

Keep:

- React `/app` review workflow.
- `services/openai_provider.py`.
- `semantic_embeddings` provider-versioned table.
- OpenAI template-service-concept embeddings.
- `mpers_templates.json` and `XBRLTemplateService`.
- Existing biological asset and receivables guardrails.
- Arelle wrapper as deterministic validation/reporting.
- Generated XBRL audit and readiness validation where useful.

## What To Replace Or Redesign

Replace or redesign:

- The prompt pattern that combines extraction and exact concept mapping.
- Any VLM-first behavior for text-native PDFs.
- Mapping that auto-accepts broad concepts without enough evidence.
- Persistence that loses row-level evidence, table context, and extraction-route provenance.
- Any future workflow that automatically remaps based on Arelle or LLM feedback without human approval.

## Recommended Modern Architecture

Use a hybrid industrial pipeline:

1. Document ingestion and evidence model
   Store page metadata, native text, rendered image path when needed, source snippets, extraction route, and future bbox/table-cell coordinates.

2. Document structure detection
   Detect statement sections, notes, tables, year columns, titles, and continuation pages. Use OpenAI only for ambiguous structure/classification.

3. Deterministic table candidate extraction
   Extract candidate rows before mapping: raw label, raw value, year, column, page number, statement section, source evidence, and confidence.

4. OpenAI structured normalization
   Normalize labels, values, signs, years, totals/subtotals, and row types with strict JSON schemas. Do not map to taxonomy here.

5. Mapping candidate generation
   Use local template rules, string matching, and OpenAI embeddings to generate top-k candidate concepts. Apply guardrails before any auto-acceptance.

6. Mapping decision policy
   Separate auto-accepted mappings, suggestions for human review, unmapped rows, and guardrail-blocked rows. Store decision reasons.

7. XBRL generation
   Generate final XBRL only from accepted mappings. Keep suggested/unmapped rows out unless manually confirmed or accepted by a clear policy.

8. Validation and audit
   Run readiness validation, Arelle instance baseline, and generated XBRL audit. Produce human-readable issue reports.

9. Human review loop
   Show extracted row, source evidence, top-k suggestions, guardrail reason, confidence, and accept/reject/change controls.

This can be implemented with the OpenAI API key, existing Python PDF/rendering tools, `mpers_templates.json`, `XBRLTemplateService`, the `semantic_embeddings` table, existing database tables, and the existing Arelle wrapper. No external managed service is required.

## OpenAI Usage Position

Use vision models for scanned pages, weak native text, page/section classification ambiguity, and visual layout reasoning.

Use text models for strict JSON extraction from native text evidence, row normalization, sign/year reasoning, row-type classification, and concise review explanations.

Use embeddings for query-to-template top-k mapping suggestions from `semantic_embeddings`. Run this in shadow comparison before production cutover.

Do not use the model to invent missing rows, assign final taxonomy mappings inside extraction prompts, or silently auto-fix Arelle issues.

## Arelle Recommendation

Do **not** let an LLM call Arelle as an agentic auto-fix loop now.

Arelle should remain deterministic validation and reporting. Later, an LLM can summarize Arelle issues and suggest remediation categories, but any DB remapping, XBRL fact deletion, taxonomy substitution, dimension/context synthesis, or generated-XBRL rewrite must require guarded scripts and human approval.

## Architecture Options Compared

Option 1: Keep current VLM+LLM mixed pipeline and patch it.
Low implementation effort, but poor debuggability and weak evidence traceability.

Option 2: Text-first / table-first extraction with OpenAI normalization.
Strong for native PDFs and cheaper, but needs fallback handling for scanned or layout-complex pages.

Option 3: OpenAI vision-first extraction for all pages.
Simple at API level, but expensive and opaque for text-native financial statements.

Option 4: Hybrid industrial pipeline.
Recommended. It gives the best balance of stability, cost control, debuggability, evidence traceability, and MPERS mapping accuracy potential.

## Benchmark Strategy

Do not use Job 9 as the primary benchmark. Job 9 can stay as a smoke-test regression sample only.

Use at least 3-5 representative PDFs:

- standard financial statement PDF
- complex table PDF
- notes-heavy PDF
- scanned or image-heavy PDF if available
- one real or near-real customer-like PDF

Include Job 11 because it has known OpenAI extraction output. Add new real/representative jobs as soon as available.

Track:

- page classification accuracy
- rows extracted
- values extracted correctly
- year/column correctness
- sign correctness
- `statement_type` correctness
- `template_field_id` coverage
- unmapped rows
- duplicate labels and duplicate label+value rows
- mapping top-1 and top-5 agreement
- human review burden
- generated XBRL fact count
- Arelle instance_baseline result
- generated XBRL audit issues

## Migration Roadmap

Phase 0: Architecture approval and benchmark dataset definition.

Phase 1: Multi-PDF benchmark harness.

Phase 2: New extraction prototype side-by-side, no production cutover.

Phase 3: OpenAI structured normalization prototype.

Phase 4: Mapping candidate generation using OpenAI embeddings in shadow mode.

Phase 5: React review suggestions, no auto-commit.

Phase 6: XBRL generation from accepted mappings only.

Phase 7: Gradual production cutover behind a feature flag.

Phase 8: Arelle-assisted issue summarization, not auto-fix.

## What Not To Do Yet

- Do not switch production semantic matching to OpenAI embeddings before shadow comparison.
- Do not redesign the production pipeline without a benchmark harness.
- Do not use Job 9 as ground truth.
- Do not let LLMs automatically remap or mutate DB state from Arelle reports.
- Do not claim MBRS/FS-MPERS submission readiness from readiness checks alone.

## Recommended Next Feature

**Feature #13H Multi-PDF extraction benchmark harness.**

Reason: the next safest step is measurement. The project needs reproducible multi-PDF evidence before implementing side-by-side extraction prototypes or semantic matcher cutover.
