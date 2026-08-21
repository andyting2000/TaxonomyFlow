# PDF-XBRL Rulebook Hardening - Feature #18D-B

## Readiness

- Active rules: 13
- Production candidates: 0
- Advisory candidates: 10
- Review-only: 0
- Downgraded to review-required: 3
- Excluded: 0

## Replay

- Active precision: 0.9302
- Active coverage: 0.055
- Active false positives: 3

## Recommendation

- Next: Feature #18D-C - Deterministic rulebook mapper service, offline/mock only
- #18D-C justified: True
- Auto-apply approved: False

| Rule | QName | Readiness | Precision | Coverage |
| --- | --- | --- | ---: | ---: |
| amount due to director a | ssmt-mpers:OtherNoncurrentLiabilities | advisory_candidate | None | 0.0 |
| bank balances | ssmt:CashAndBankBalances | advisory_candidate | 1.0 | 0.0102 |
| property plant and equipment | ifrs-smes:PropertyPlantAndEquipment | advisory_candidate | 1.0 | 0.0102 |
| rental received | ssmt-mpers:OtherRentalIncomeOnLandAndBuildings | advisory_candidate | None | 0.0 |
| term loan r discussione | ssmt-mpers:NoncurrentPortionOfNoncurrentSecuredBankLoansReceived | advisory_candidate | None | 0.0 |
| term loans repayments | ifrs-smes:CashFlowsFromUsedInFinancingActivities | advisory_candidate | None | 0.0 |
| total liabilities d por current fral to | ifrs-smes:Liabilities | advisory_candidate | None | 0.0 |
| total non current liabilities w | ifrs-smes:NoncurrentLiabilities | advisory_candidate | None | 0.0 |
| total operating expenses folaviceral | ifrs-smes:OtherExpenseByFunction | advisory_candidate | None | 0.0 |
| utilities deposits | ssmt-mpers:OtherCurrentNontradeDeposits | advisory_candidate | None | 0.0 |
| add other income | ifrs-smes:OtherIncome | downgrade_to_review_required | 0.5 | 0.0026 |
| total current assets | ifrs-smes:CurrentAssets | downgrade_to_review_required | 0.875 | 0.0102 |
| total operating expenses | ifrs-smes:OtherExpenseByFunction | downgrade_to_review_required | 0.8333 | 0.0077 |
