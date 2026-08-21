# Extraction v2 vs Reference XML/XBRL Comparison

## Executive Summary

- Cases compared: 7
- Reference total facts: 3101
- V2 total candidates: 940
- V2 native-only candidates: 122
- V2 Hugging Face candidates: 818
- V2 OpenAI candidates: 0
- V2 live-model candidates: 818
- V2 Hugging Face fallback pages attempted: 55
- V2 Hugging Face fallback pages succeeded: 28
- V2 Hugging Face fallback pages failed: 27
- V2 Hugging Face empty candidate pages: 27
- V2 Hugging Face parser recovered candidates: 351
- V2 Hugging Face parser failed pages: 0
- V2 Hugging Face raw response previews: 55
- V2 OpenAI fallback pages attempted: 0
- V2 OpenAI fallback pages succeeded: 0
- V2 OpenAI fallback pages failed: 0
- Reference numeric facts: 2590
- V2 numeric candidates: 655
- Reference text blocks: 304
- V2 text block candidates: 146
- Missing numeric extraction signal: False
- Missing text-block extraction signal: False
- Numeric extraction signal improved: True
- Text-block extraction signal improved: True
- Benchmark complete: True
- Cases with numeric signal: 7
- Cases with text-block signal: 6
- Missing numeric cases: []
- Missing text-block cases: ['001-bizaid-synthetic']
- Remaining numeric gap: 1935
- Remaining text-block gap: 158
- UI upload required: False
- Database mutated: False

## Per Case

| Case | Ref Facts | V2 Candidates | Native | Hugging Face | OpenAI | Ref Numeric | V2 Numeric | Ref Text Blocks | V2 Text Blocks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 001-bizaid-synthetic | 552 | 122 | 122 | 0 | 0 | 487 | 40 | 37 | 0 |
| 002-bezlife-marketing | 413 | 115 | 0 | 115 | 0 | 339 | 89 | 43 | 24 |
| 003-fine-batik | 427 | 189 | 0 | 189 | 0 | 352 | 158 | 44 | 28 |
| 004-info-house | 414 | 150 | 0 | 150 | 0 | 338 | 99 | 45 | 34 |
| 005-jconnector | 400 | 134 | 0 | 134 | 0 | 323 | 90 | 46 | 29 |
| 006-Rahsia-Herbal | 421 | 146 | 0 | 146 | 0 | 345 | 126 | 46 | 14 |
| 007-Shield-Plus | 474 | 84 | 0 | 84 | 0 | 406 | 53 | 43 | 17 |

## Recommended Focus

- Use the reference report to refine overlap scoring and candidate classification.

## Assessment

Feature #13Q full Hugging Face Qwen benchmark completed successfully. Extraction v2 now emits numeric and text-block candidates for the OCR-heavy benchmark set. Remaining work is candidate quality, duplicate control, concept mapping readiness, and production cutover planning.
