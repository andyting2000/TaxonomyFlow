# Extraction v2 vs Reference XML/XBRL Comparison

## Executive Summary

- Cases compared: 7
- Reference total facts: 3101
- V2 total candidates: 185
- Reference numeric facts: 2590
- V2 numeric candidates: 0
- Reference text blocks: 304
- V2 text block candidates: 0
- Missing numeric extraction signal: True
- Missing text-block extraction signal: True
- UI upload required: False
- Database mutated: False

## Per Case

| Case | Ref Facts | V2 Candidates | Ref Numeric | V2 Numeric | Ref Text Blocks | V2 Text Blocks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 001-bizaid-synthetic | 552 | 185 | 487 | 0 | 37 | 0 |
| 002-bezlife-marketing | 413 | 0 | 339 | 0 | 43 | 0 |
| 003-fine-batik | 427 | 0 | 352 | 0 | 44 | 0 |
| 004-info-house | 414 | 0 | 338 | 0 | 45 | 0 |
| 005-jconnector | 400 | 0 | 323 | 0 | 46 | 0 |
| 006-Rahsia-Herbal | 421 | 0 | 345 | 0 | 46 | 0 |
| 007-Shield-Plus | 474 | 0 | 406 | 0 | 43 | 0 |

## Recommended Focus

- Prioritize v2 numeric table/fact extraction; reference XML contains numeric facts but v2 emitted none.
- Prioritize v2 text-block/disclosure extraction; reference XML contains text blocks but v2 emitted none.

## Assessment

Extraction v2 has not yet extracted numeric facts or text blocks; reference XML contains facts that can guide v2 development.
