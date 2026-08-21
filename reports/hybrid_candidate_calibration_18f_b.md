# Hybrid Candidate Calibration #18F-B

Offline profile comparison only. All candidates remain review-required and unsafe for auto-apply.

| Profile | Coverage | Rows >=1 | Rows >=3 | Candidates | Top-1 | Top-3 | Top-5 | High/Critical Ratio | Quality |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| strict | 0.5102 | 399 | 64 | 605 | 0.7931 | 0.4854 | 0.4854 | 0.205 | 60.5476 |
| balanced | 0.6036 | 472 | 172 | 983 | 0.8 | 0.5825 | 0.5825 | 0.2574 | 65.4744 |
| recall | 0.6087 | 476 | 216 | 1139 | 0.7568 | 0.5922 | 0.6019 | 0.3538 | 63.8308 |

- Recommended profile: `balanced`
- Reason: Balanced preserves >=60% coverage, keeps top-1 precision >=0.75, and controls high/critical risk without critical candidates.
- Backend advisory integration justified: `True`
- No-auto-apply boundary: `safe_for_auto_apply=false`, `requires_human_review=true`.
