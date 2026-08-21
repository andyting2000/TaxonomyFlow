# Extraction v2 Benchmark Report

## Executive Summary

- Cases processed: 7
- PDFs processed: 7
- Candidate rows: 143
- Numeric facts: 40
- Comparative numeric facts: 5
- Text blocks: 15
- Metadata rows: 0
- Headings: 82
- Unknown rows: 0
- Vision fallback used: True
- Vision provider: huggingface
- Hugging Face used: True
- OpenAI used: False
- Private PDF OpenAI approval: False
- Reference XML sent to OpenAI: False
- Native candidates: 122
- Hugging Face candidates: 21
- OpenAI candidates: 0
- Hugging Face fallback pages attempted: 10
- Hugging Face fallback pages succeeded: 3
- Hugging Face fallback pages failed: 7
- Hugging Face parser recovered candidates: 21
- Hugging Face parser failed pages: 0
- Hugging Face raw response previews: 10
- OpenAI fallback pages attempted: 0
- OpenAI fallback pages succeeded: 0
- OpenAI fallback pages failed: 0
- OpenAI fallback pages skipped by limit: 0
- UI upload required: False
- Database mutated: False

## Cases

| Case | Status | Reference | Pages | Candidates | Native | Hugging Face | OpenAI | Numeric | Comparative | Text Blocks | Warnings |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 001-bizaid-synthetic | ok | xml | 3 | 122 | 122 | 0 | 0 | 36 | 3 | 0 | 215 |
| 002-bezlife-marketing | ok | xml | 26 | 21 | 0 | 21 | 0 | 4 | 2 | 15 | 69 |
| 003-fine-batik | ok | xml | 25 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 28 |
| 004-info-house | ok | xml | 23 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 26 |
| 005-jconnector | ok | xml | 22 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 25 |
| 006-Rahsia-Herbal | ok | xml | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 27 |
| 007-Shield-Plus | ok | xml | 15 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 18 |

## Pipeline Stages

- document_ingestion
- native_text_extraction
- layout_or_table_heuristics
- row_type_classification
- numeric_fact_normalization
- text_block_grouping
- provenance_capture
- report_generation

## Limitations

- Benchmark-only v2 extraction; no production cutover.
- Native text/table heuristics are deterministic and intentionally conservative.
- Hugging Face vision fallback is opt-in only and benchmark-scoped when enabled.
- OpenAI fallback metrics may appear only for historical/legacy reports.
- No DB writes, XBRL generation, Arelle validation, UI upload, or production mapping are performed.
