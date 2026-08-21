# Extraction v2 Benchmark Report

## Executive Summary

- Cases processed: 7
- PDFs processed: 7
- Candidate rows: 185
- Numeric facts: 0
- Comparative numeric facts: 0
- Text blocks: 0
- Metadata rows: 0
- Headings: 185
- Unknown rows: 0
- OpenAI used: False
- UI upload required: False
- Database mutated: False

## Cases

| Case | Status | Reference | Pages | Candidates | Numeric | Comparative | Text Blocks | Warnings |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 001-bizaid-synthetic | ok | xml | 3 | 185 | 0 | 0 | 0 | 200 |
| 002-bezlife-marketing | ok | xml | 26 | 0 | 0 | 0 | 0 | 2 |
| 003-fine-batik | ok | xml | 25 | 0 | 0 | 0 | 0 | 2 |
| 004-info-house | ok | xml | 23 | 0 | 0 | 0 | 0 | 2 |
| 005-jconnector | ok | xml | 22 | 0 | 0 | 0 | 0 | 2 |
| 006-Rahsia-Herbal | ok | xml | 24 | 0 | 0 | 0 | 0 | 2 |
| 007-Shield-Plus | ok | xml | 15 | 0 | 0 | 0 | 0 | 2 |

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

- Benchmark-only v2 skeleton; no production cutover.
- Reference XML/XBRL is discovered and recorded but not parsed for ground truth comparison yet.
- No DB writes, XBRL generation, Arelle validation, API calls, UI upload, or production mapping are performed.
