# Extraction v2 vs Reference XML/XBRL Comparison

## Executive Summary

- Cases compared: 7
- Reference total facts: 3101
- V2 total candidates: 604
- V2 native candidates: 604
- V2 OpenAI candidates: 0
- V2 OpenAI fallback pages attempted: 0
- V2 OpenAI fallback pages succeeded: 0
- V2 OpenAI fallback pages failed: 0
- Reference numeric facts: 2590
- V2 numeric candidates: 396
- Reference text blocks: 304
- V2 text block candidates: 101
- Missing numeric extraction signal: False
- Missing text-block extraction signal: False
- Numeric extraction signal improved: True
- Text-block extraction signal improved: True
- Remaining numeric gap: 2194
- Remaining text-block gap: 203
- UI upload required: False
- Database mutated: False

## Per Case

| Case | Ref Facts | V2 Candidates | Ref Numeric | V2 Numeric | Ref Text Blocks | V2 Text Blocks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 001-bizaid-synthetic | 552 | 122 | 487 | 40 | 37 | 0 |
| 002-bezlife-marketing | 413 | 115 | 339 | 89 | 43 | 24 |
| 003-fine-batik | 427 | 189 | 352 | 158 | 44 | 28 |
| 004-info-house | 414 | 148 | 338 | 97 | 45 | 34 |
| 005-jconnector | 400 | 30 | 323 | 12 | 46 | 15 |
| 006-Rahsia-Herbal | 421 | 0 | 345 | 0 | 46 | 0 |
| 007-Shield-Plus | 474 | 0 | 406 | 0 | 43 | 0 |

## Recommended Focus

- Expand native/OCR numeric table coverage; v2 now emits numeric candidates but still covers only a small share of reference numeric facts.

## Assessment

Extraction v2 now emits numeric and text-block candidates; remaining gaps should be measured against reference coverage and candidate quality.
