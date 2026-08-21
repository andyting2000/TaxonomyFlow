# Extraction v2 vs Reference XML/XBRL Comparison

## Executive Summary

- Cases compared: 7
- Reference total facts: 3101
- V2 total candidates: 122
- V2 native candidates: 122
- V2 OpenAI candidates: 0
- V2 OpenAI fallback pages attempted: 60
- V2 OpenAI fallback pages succeeded: 0
- V2 OpenAI fallback pages failed: 60
- Reference numeric facts: 2590
- V2 numeric candidates: 40
- Reference text blocks: 304
- V2 text block candidates: 0
- Missing numeric extraction signal: False
- Missing text-block extraction signal: True
- Numeric extraction signal improved: True
- Text-block extraction signal improved: False
- Remaining numeric gap: 2550
- Remaining text-block gap: 304
- UI upload required: False
- Database mutated: False

## Per Case

| Case | Ref Facts | V2 Candidates | Ref Numeric | V2 Numeric | Ref Text Blocks | V2 Text Blocks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 001-bizaid-synthetic | 552 | 122 | 487 | 40 | 37 | 0 |
| 002-bezlife-marketing | 413 | 0 | 339 | 0 | 43 | 0 |
| 003-fine-batik | 427 | 0 | 352 | 0 | 44 | 0 |
| 004-info-house | 414 | 0 | 338 | 0 | 45 | 0 |
| 005-jconnector | 400 | 0 | 323 | 0 | 46 | 0 |
| 006-Rahsia-Herbal | 421 | 0 | 345 | 0 | 46 | 0 |
| 007-Shield-Plus | 474 | 0 | 406 | 0 | 43 | 0 |

## Recommended Focus

- Expand native/OCR numeric table coverage; v2 now emits numeric candidates but still covers only a small share of reference numeric facts.
- Prioritize v2 text-block/disclosure extraction; reference XML contains text blocks but v2 emitted none.

## Assessment

Extraction v2 numeric extraction improved from zero, but text-block extraction remains missing against the reference layer.
