# PDF-XBRL Deterministic Alignment Summary - Feature #18A

## Metrics

- total_samples_found: 6
- included_sample_count: 5
- excluded_sample_count: 1
- total_pdf_rows_considered: 420
- total_pdf_row_values_considered: 782
- total_xbrl_facts_considered: 1540
- high_confidence_count: 40
- medium_confidence_count: 43
- ambiguous_count: 429
- unmatched_pdf_row_count: 248
- unmatched_xbrl_fact_count: 1457

## Included Samples

| Sample | Company | Status | Reason | PDF rows | PDF rows considered | XBRL facts | XBRL facts considered |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| case_001 | 001-bezlife-marketing | included |  | 148 | 76 | 413 | 306 |
| case_002 | 002-fine-batik | included |  | 171 | 100 | 427 | 321 |
| case_003 | 003-info-house | included |  | 146 | 81 | 414 | 307 |
| case_004 | 004-jconnector | included |  | 127 | 63 | 400 | 293 |
| case_005 | 005-Rahsia-Herbal | included |  | 170 | 100 | 421 | 313 |

## Excluded Samples

| Sample | Company | Status | Reason | PDF rows | PDF rows considered | XBRL facts | XBRL facts considered |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| case_006 | Shield-Plus | excluded | outlier_excluded_by_default | 95 | 32 | 474 | 377 |

## Top Repeated Mapping Patterns

| Label | XBRL QName | Count | Samples |
| --- | --- | ---: | ---: |
| total current assets | ifrs-smes:CurrentAssets | 7 | 4 |
| cash flows from investing activities | ifrs-smes:CashFlowsFromUsedInInvestingActivities | 5 | 3 |
| total operating expenses | ifrs-smes:OtherExpenseByFunction | 4 | 3 |
| trade and other payables | ssmt-mpers:OtherCurrentNontradePayables | 4 | 3 |
| property plant and equipment | ifrs-smes:PropertyPlantAndEquipment | 4 | 2 |
| trade and other receivables | ssmt-mpers:OtherCurrentMiscellaneousNontradeReceivables | 4 | 2 |
| trade and other payables | ifrs-smes:AdjustmentsForIncreaseDecreaseInOtherOperatingPayables | 3 | 2 |
| staff costs | ifrs-smes:EmployeeBenefitsExpense | 3 | 2 |
| gross profit | ifrs-smes:GrossProfit | 3 | 2 |
| total liabilities | ifrs-smes:Liabilities | 3 | 2 |
| add other income | ifrs-smes:OtherIncome | 3 | 2 |
| trade and other payables | ssmt-mpers:CurrentNontradePayables | 3 | 2 |
| term loans repayments | ifrs-smes:CashFlowsFromUsedInFinancingActivities | 2 | 1 |
| total current liabilities | ifrs-smes:CurrentLiabilities | 2 | 1 |
| property plant and equipment | ifrs-smes:DepreciationPropertyPlantAndEquipment | 2 | 1 |
| total non current liabilities w | ifrs-smes:NoncurrentLiabilities | 2 | 1 |
| total operating expenses folaviceral | ifrs-smes:OtherExpenseByFunction | 2 | 1 |
| director s remuneration | ssmt-mpers:DirectorsRemuneration | 2 | 1 |
| directors remuneration | ssmt-mpers:DirectorsRemuneration | 2 | 1 |
| term loan r discussione | ssmt-mpers:NoncurrentPortionOfNoncurrentSecuredBankLoansReceived | 2 | 1 |
| term loan | ssmt-mpers:NoncurrentPortionOfNoncurrentSecuredBankLoansReceived | 2 | 1 |
| utilities deposits | ssmt-mpers:OtherCurrentNontradeDeposits | 2 | 1 |
| other income | ssmt-mpers:OtherMiscellaneousIncome | 2 | 1 |
| amount due to director a | ssmt-mpers:OtherNoncurrentLiabilities | 2 | 1 |
| trade and other payables | ssmt-mpers:OtherNoncurrentNontradePayables | 2 | 1 |
| rental received | ssmt-mpers:OtherRentalIncomeOnLandAndBuildings | 2 | 1 |
| trade and other receivables | ifrs-smes:AdjustmentsForDecreaseIncreaseInOtherOperatingReceivables | 1 | 1 |
| gross profit cleision | ifrs-smes:GrossProfit | 1 | 1 |
| tax expense | ifrs-smes:IncomeTaxExpenseContinuingOperations | 1 | 1 |
| tax expense | ifrs-smes:IncomeTaxesPaidRefundClassifiedAsOperatingActivities | 1 | 1 |

## Recommendation

- #18B justified: True
- Next: Feature #18B - Build reusable mapping rulebook from high-confidence PDF-XBRL alignments.

## Safety

- external_llm_called: False
- external_provider_called: False
- azure_di_live_call_made: False
- database_mutated: False
- production_behavior_changed: False
- api_changed: False
- ui_changed: False
- xbrl_generated: False
- arelle_run: False
