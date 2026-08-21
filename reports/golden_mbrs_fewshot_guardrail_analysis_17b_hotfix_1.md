# Golden MBRS Few-Shot Guardrail Analysis #17B Hotfix 1

- Wrong concept rows: `3`
- Candidate-missing wrong rows: `3`
- Broad-substitution wrong rows: `3`
- External LLM called: `False`

## Wrong Rows

- `case_005` `case_005:candidate:65:65` `Other receivables`
  - correct: `ssmt-mpers:OtherCurrentMiscellaneousNontradeReceivables`
  - selected: `ssmt-mpers:OtherCurrentReceivables`
  - likely source: `candidate_missing_broad_substitution`
- `case_005` `case_005:candidate:72:72` `Other payables`
  - correct: `ssmt-mpers:OtherNoncurrentNontradePayables`
  - selected: `ssmt-mpers:OtherPayables`
  - likely source: `candidate_missing_broad_substitution`
- `case_006` `case_006:candidate:16:16` `Other payable`
  - correct: `ssmt-mpers:CurrentNontradePayables`
  - selected: `ifrs-smes:TradeAndOtherCurrentPayables`
  - likely source: `candidate_missing_broad_substitution`
