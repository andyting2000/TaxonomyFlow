# Extraction v2 Benchmark Report

## Executive Summary

- Cases processed: 7
- PDFs processed: 7
- Candidate rows: 940
- Numeric facts: 542
- Comparative numeric facts: 37
- Text blocks: 146
- Metadata rows: 10
- Headings: 129
- Unknown rows: 0
- Vision fallback used: True
- Vision provider: huggingface
- Resumed from checkpoint: True
- Effective vision max pages: 140
- Additional vision pages attempted after resume: 55
- Hugging Face used: True
- OpenAI used: False
- Private PDF OpenAI approval: False
- Reference XML sent to OpenAI: False
- Native candidates: 122
- Hugging Face candidates: 818
- OpenAI candidates: 0
- Hugging Face fallback pages attempted: 55
- Hugging Face fallback pages succeeded: 28
- Hugging Face fallback pages failed: 27
- Hugging Face parser recovered candidates: 351
- Hugging Face parser failed pages: 0
- Hugging Face raw response previews: 55
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
| 002-bezlife-marketing | ok | xml | 26 | 115 | 0 | 115 | 0 | 78 | 0 | 24 | 165 |
| 003-fine-batik | ok | xml | 25 | 189 | 0 | 189 | 0 | 142 | 0 | 28 | 242 |
| 004-info-house | ok | xml | 23 | 150 | 0 | 150 | 0 | 80 | 0 | 34 | 207 |
| 005-jconnector | ok | xml | 22 | 134 | 0 | 134 | 0 | 67 | 12 | 29 | 192 |
| 006-Rahsia-Herbal | ok | xml | 24 | 146 | 0 | 146 | 0 | 95 | 20 | 14 | 198 |
| 007-Shield-Plus | ok | xml | 15 | 84 | 0 | 84 | 0 | 44 | 2 | 17 | 122 |

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
