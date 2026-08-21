# Pipeline Side-by-Side Comparison

## Executive Summary

- Jobs compared: 7
- Production rows: 938
- Shadow rows: 0
- Production mapped rows: 814
- Production unmapped rows: 124
- Shadow numeric candidates: 0
- Shadow weak/no-label rows: 0
- Shadow suspicious signs: 0
- Shadow possible prior-year confusion: 0
- Shadow pipeline looks promising: False
- Shadow job statuses: {'missing_pdf': 7}

## Jobs

| Job | Production Rows | Shadow Rows | Prod Mapped | Prod Unmapped | Shadow Numeric | Label Overlap | Label+Value Overlap | Risks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 13 | 62 | 0 | 47 | 15 | 0 | 0 | 0 | none |
| 14 | 169 | 0 | 141 | 28 | 0 | 0 | 0 | none |
| 15 | 192 | 0 | 159 | 33 | 0 | 0 | 0 | none |
| 18 | 144 | 0 | 122 | 22 | 0 | 0 | 0 | none |
| 19 | 101 | 0 | 97 | 4 | 0 | 0 | 0 | none |
| 20 | 125 | 0 | 120 | 5 | 0 | 0 | 0 | none |
| 23 | 145 | 0 | 128 | 17 | 0 | 0 | 0 | none |

## Assessment

Shadow extraction could not evaluate candidates because all selected source PDFs are missing locally.

## Recommended Next Step

Analyze side-by-side results and decide whether to improve shadow heuristics, mapping prompts, or production extraction architecture.

## Limitations

- Comparison is approximate and uses normalized labels/values, not human ground truth.
- Shadow candidates are not mapped to taxonomy concepts and are not written to the database.
- No XBRL generation, Arelle validation, or production extraction cutover is performed.
