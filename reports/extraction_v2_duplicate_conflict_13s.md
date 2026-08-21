# Feature #13S Extraction v2 Duplicate and Conflict Report

## Summary

- Total candidates analyzed: 940
- Exact duplicate groups: 3
- Same label/value duplicate groups: 35
- Conflicting duplicate groups: 45
- Heading-like duplicate groups: 0
- Date/year label groups: 9
- Text-block duplicate groups: 0
- Safe suppression count: 3
- Downgrade count: 47
- Converted row type count: 238
- Conflict review count: 95
- Manual review required count: 12
- Database mutated: False
- Live model calls made: False

## Per Case

| Case | Original | Cleaned | Suppressed | Downgraded | Converted | Conflict Groups | Manual Groups |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 001-bizaid-synthetic | 122 | 119 | 3 | 1 | 0 | 0 | 0 |
| 002-bezlife-marketing | 115 | 115 | 0 | 0 | 52 | 3 | 0 |
| 003-fine-batik | 189 | 189 | 0 | 0 | 68 | 11 | 0 |
| 004-info-house | 150 | 150 | 0 | 4 | 36 | 11 | 0 |
| 005-jconnector | 134 | 134 | 0 | 15 | 35 | 4 | 0 |
| 006-Rahsia-Herbal | 146 | 146 | 0 | 27 | 37 | 8 | 0 |
| 007-Shield-Plus | 84 | 84 | 0 | 0 | 10 | 8 | 0 |

## Top Risky Duplicate Labels

- as at 31 12 2023: 21
- as at 31 12 2024: 16
- loss for the financial year: 14
- loss before taxation: 9
- charges for the year: 5
- term loan: 4
- as at 31st december 2022: 3
- as at 31st december 2023: 3
- as at 31st december 2024: 3
- as at 31 december 2022: 3
- as at 31 december 2023: 3
- as at 31 december 2024: 3
- total: 3
- as at 31 12 2022: 3
- accumulated loss rm: 3
- total rm: 3
- epf contribution: 2
- director s fee: 2
- rental of office: 2
- accumulated losses carried forward: 2

## Limitations

- Only exact duplicate evidence is suppressible.
- Conflicting values are preserved and require review.
- This report does not choose values, aggregate detail rows, map taxonomy concepts, flip signs, infer dimensions, or merge text blocks across sections.
