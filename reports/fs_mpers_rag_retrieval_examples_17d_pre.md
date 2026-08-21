# FS-MPERS RAG Retrieval Examples #17D-pre

| Sample Label | Candidates | Cards | Missing Relevant Card | Missing Reason | Top Concepts |
| --- | --- | --- | --- | --- | --- |
| contributed share capital | 2 | 2 | False |  | ifrs-smes:Equity, ifrs-smes:EquityAndLiabilities |
| bank overdraft | 3 | 2 | True | no_matching_concept_card_available_in_local_playbook | ssmt:CashAndBankBalances, ifrs-smes:CashAndCashEquivalents |
| other receivable | 2 | 2 | False |  | ssmt-mpers:OtherCurrentMiscellaneousNontradeReceivables, ifrs-smes:AdjustmentsForDecreaseIncreaseInTradeAccountReceivable |
| other payable | 6 | 5 | False |  | ssmt-mpers:CurrentNontradePayables, ssmt-mpers:OtherCurrentNontradePayables, ssmt-mpers:OtherNoncurrentNontradePayables, ifrs-smes:AdjustmentsForIncreaseDecreaseInOtherOperatingPayables, ifrs-smes:AdjustmentsForIncreaseDecreaseInTradeAccountPayable |
| accruals | 7 | 5 | False |  | ssmt-mpers:CurrentNontradeAccruals, ifrs-smes:AdjustmentsForIncreaseDecreaseInOtherOperatingPayables, ssmt-mpers:CurrentNontradePayables, ssmt-mpers:OtherCurrentNontradePayables, ssmt-mpers:OtherNoncurrentNontradePayables |
| cash and cash equivalents | 5 | 5 | False |  | ifrs-smes:CashAndCashEquivalents, ssmt:CashAndBankBalances, ifrs-smes:IncreaseDecreaseInCashAndCashEquivalents, ifrs-smes:CashFlowsFromUsedInOperatingActivities, ifrs-smes:CashFlowsFromUsedInFinancingActivities |
| tax expense | 0 | 0 | True | no_matching_concept_card_available_in_local_playbook |  |
| administrative expenses | 4 | 4 | False |  | ifrs-smes:OtherExpenseByFunction, ssmt-mpers:AdjustmentsForDepreciationExpense, ifrs-smes:WagesAndSalaries, ifrs-smes:EmployeeBenefitsExpense |
