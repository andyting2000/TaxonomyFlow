# Extraction and Mapping Benchmark

## Executive Summary

- Jobs analyzed: 1
- Total extracted rows: 53
- Average template-field coverage: 69.8%
- Average confirmed-tag coverage: 0.0%
- Average unmapped rate: 30.2%
- XBRL audits loaded: 0
- Arelle baselines loaded: 0

## Jobs Analyzed

| Job | Role | Status | Company | Rows | Template Coverage | Confirmed Tags | Unmapped | Duplicate Labels | Suspicious Signs |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 11 | benchmark_candidate | REVIEW | testing | 53 | 69.8% | 0.0% | 16 | 0 | 7 |

## Key Risks

- jobs_with_high_unmapped_rate: [11]
- jobs_with_high_duplicate_rate: none
- jobs_with_high_suspicious_sign_rate: [11]
- jobs_with_low_template_coverage: none
- jobs_with_missing_blank_statement_types: none
- jobs_that_should_not_be_used_as_benchmark: none

## Benchmark Policy

- The benchmark set should eventually include 3-5 representative PDFs/jobs.
- Job 9 is smoke-test only.
- This report measures system output quality signals; it does not prove extraction correctness without human ground truth.

## Recommended Next Action

Feature #13I Side-by-side text/table-first extraction prototype, no production cutover
