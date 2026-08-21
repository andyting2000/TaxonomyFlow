# Extraction and Mapping Benchmark

## Executive Summary

- Jobs analyzed: 7
- Total extracted rows: 938
- Average template-field coverage: 86.7%
- Average confirmed-tag coverage: 0.0%
- Average unmapped rate: 13.3%
- XBRL audits loaded: 0
- Arelle baselines loaded: 0

## Jobs Analyzed

| Job | Role | Status | Company | Rows | Template Coverage | Confirmed Tags | Unmapped | Duplicate Labels | Suspicious Signs |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 13 | benchmark_candidate | REVIEW | BizAid Technologies Sdn. Bhd. | 62 | 75.8% | 0.0% | 15 | 0 | 14 |
| 14 | benchmark_candidate | REVIEW | BEZLIFE MARKETING SDN. BHD. | 169 | 83.4% | 0.0% | 28 | 41 | 18 |
| 15 | benchmark_candidate | REVIEW | FINE BATIK SDN. BHD. | 192 | 82.8% | 0.0% | 33 | 44 | 36 |
| 18 | benchmark_candidate | REVIEW | RAHSIA HERBAL SDN. BHD. | 144 | 84.7% | 0.0% | 22 | 54 | 26 |
| 19 | benchmark_candidate | REVIEW | SHIELD PLUS SDN. BHD. | 101 | 96.0% | 0.0% | 4 | 31 | 31 |
| 20 | benchmark_candidate | REVIEW | AGENSI PEKERJAAN JCONNECTOR.COM SDN. BHD. | 125 | 96.0% | 0.0% | 5 | 31 | 28 |
| 23 | benchmark_candidate | REVIEW | AGENSI PEKERJAAN INFO-HOUSE (M) SDN. BHD. | 145 | 88.3% | 0.0% | 17 | 34 | 15 |

## Key Risks

- jobs_with_high_unmapped_rate: none
- jobs_with_high_duplicate_rate: [18, 19]
- jobs_with_high_suspicious_sign_rate: [13, 14, 15, 18, 19, 20, 23]
- jobs_with_low_template_coverage: none
- jobs_with_missing_blank_statement_types: none
- jobs_that_should_not_be_used_as_benchmark: none

## Benchmark Policy

- The benchmark set should eventually include 3-5 representative PDFs/jobs.
- Job 9 is smoke-test only.
- This report measures system output quality signals; it does not prove extraction correctness without human ground truth.

## Recommended Next Action

Feature #13I Side-by-side text/table-first extraction prototype, no production cutover
