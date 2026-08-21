# Extraction v2 Benchmark Report

## Executive Summary

- Cases processed: 7
- PDFs processed: 7
- Candidate rows: 194
- Numeric facts: 48
- Comparative numeric facts: 3
- Text blocks: 38
- Metadata rows: 6
- Headings: 98
- Unknown rows: 0
- OpenAI used: True
- Private PDF OpenAI approval: True
- Reference XML sent to OpenAI: False
- Native candidates: 122
- OpenAI candidates: 72
- OpenAI fallback pages attempted: 10
- OpenAI fallback pages succeeded: 10
- OpenAI fallback pages failed: 0
- OpenAI fallback pages skipped by limit: 125
- UI upload required: False
- Database mutated: False

## Cases

| Case | Status | Reference | Pages | Candidates | Native | OpenAI | Numeric | Comparative | Text Blocks | Warnings |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 001-bizaid-synthetic | ok | xml | 3 | 122 | 122 | 0 | 36 | 3 | 0 | 215 |
| 002-bezlife-marketing | ok | xml | 26 | 72 | 0 | 72 | 12 | 0 | 38 | 172 |
| 003-fine-batik | ok | xml | 25 | 0 | 0 | 0 | 0 | 0 | 0 | 28 |
| 004-info-house | ok | xml | 23 | 0 | 0 | 0 | 0 | 0 | 0 | 26 |
| 005-jconnector | ok | xml | 22 | 0 | 0 | 0 | 0 | 0 | 0 | 25 |
| 006-Rahsia-Herbal | ok | xml | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 27 |
| 007-Shield-Plus | ok | xml | 15 | 0 | 0 | 0 | 0 | 0 | 0 | 18 |

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
- OpenAI vision fallback is opt-in only and benchmark-scoped when enabled.
- No DB writes, XBRL generation, Arelle validation, UI upload, or production mapping are performed.
