# Overblocked Recovery - Feature #18E-D-hotfix-1

- blocked_candidate_opportunities: 178
- recovered_candidate_count: 6
- newly_covered_by_recovery_count: 0
- recovered_true_positive_count: 6
- recovered_false_positive_count: 0
- recovered_precision_on_evaluable: 1.0
- safe_for_auto_apply_count: 0
- recommended_next_feature: Feature #18E-B-3 - Add safer company-format template memory and note-detail boundaries
- recommendation_reason: Recovery stayed quality-stable but did not improve measured coverage or precision; coverage remains the dominant gap.

| Sample | Label | QName | Classification | Status | Reason |
| --- | --- | --- | --- | --- | --- |
| case_001 | Profit after taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_correctly | qname_exists_but_value_mismatch | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_001 | Provision for taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_correctly | qname_exists_but_value_mismatch | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_001 | Provision for taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_high_risk | exact_qname_value_period_match | income_tax_expense_recovery_conditions_not_met |
| case_001 | Other operating costs | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_001 | Other operating costs | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_001 | Other operating costs | ifrs-smes:AdministrativeExpense | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_001 | Other operating costs | ifrs-smes:AdministrativeExpense | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_001 | Profit / (Loss) from operating activities | ssmt-mpers:ProfitLossFromOperatingActivities | still_blocked_correctly | qname_exists_but_value_mismatch | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_001 | Profit / (Loss) from operating activities | ssmt-mpers:ProfitLossFromOperatingActivities | not_recoverable | exact_qname_value_period_match | target_family_not_in_low_risk_recovery_scope |
| case_001 | Add : Other income | ifrs-smes:OtherIncome | recovered_low_risk | exact_qname_value_period_match | other_income_exact_main_statement_recovery |
| case_001 | Add : Other income | ifrs-smes:OtherIncome | recovered_low_risk | exact_qname_value_period_match | other_income_exact_main_statement_recovery |
| case_001 | Total comprehensive profit / (loss) for the year / period | ifrs-smes:ProfitLoss | still_blocked_correctly | qname_exists_but_value_mismatch | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_001 | Total comprehensive profit / (loss) for the year / period | ifrs-smes:ProfitLoss | still_blocked_ambiguous | ambiguous_xbrl_support | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_001 | Comprehensive loss for the period | ifrs-smes:ComprehensiveIncome | not_recoverable | qname_value_match_period_uncertain | target_family_not_in_low_risk_recovery_scope |
| case_001 | Comprehensive loss for the period | ifrs-smes:ComprehensiveIncome | not_recoverable | qname_value_match_period_uncertain | target_family_not_in_low_risk_recovery_scope |
| case_001 | Comprehensive profit for the year | ifrs-smes:ComprehensiveIncome | still_blocked_correctly | qname_exists_but_value_mismatch | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_001 | Comprehensive profit for the year | ifrs-smes:ProfitLoss | still_blocked_correctly | qname_exists_but_value_mismatch | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_001 | Comprehensive profit for the year | ifrs-smes:ComprehensiveIncome | still_blocked_correctly | qname_exists_but_value_mismatch | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_001 | Comprehensive profit for the year | ifrs-smes:ProfitLoss | still_blocked_correctly | qname_exists_but_value_mismatch | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_001 | Cash flows from operating activities Profit / (Loss) before taxation | ifrs-smes:CashFlowsFromUsedInOperatingActivities | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_001 | Cash flows from operating activities Profit / (Loss) before taxation | ifrs-smes:CashFlowsFromUsedInOperatingActivities | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_001 | Cash flows from operating activities Profit / (Loss) before taxation | ifrs-smes:CashFlowsFromUsedInOperatingActivities | still_blocked_correctly | qname_exists_but_value_mismatch | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_001 | Cash flows from operating activities Profit / (Loss) before taxation | ifrs-smes:CashFlowsFromUsedInOperatingActivities | still_blocked_correctly | qname_exists_but_value_mismatch | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_001 | Cash and cash equivalents at beginning of year / period | ifrs-smes:CashAndCashEquivalents | not_recoverable | qname_value_match_period_uncertain | target_family_not_in_low_risk_recovery_scope |
| case_001 | Cash and cash equivalents at beginning of year / period | ifrs-smes:CashAndCashEquivalents | not_recoverable | qname_value_match_period_uncertain | target_family_not_in_low_risk_recovery_scope |
| case_001 | Profit / (Loss) before taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_001 | Profit / (Loss) before taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_001 | Taxation at tax rates of - 15% | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_correctly | qname_exists_but_value_mismatch | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_001 | Taxation at tax rates of - 15% | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_correctly | qname_exists_but_value_mismatch | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_001 | Tax expenses for the year | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_correctly | qname_exists_but_value_mismatch | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_001 | Tax expenses for the year | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_high_risk | exact_qname_value_period_match | income_tax_expense_recovery_conditions_not_met |
| case_001 | Bank charges | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_001 | Bank charges | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_001 | Secretarial fee | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_001 | Secretarial fee | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_001 | TOTAL OPERATING EXPENSES | ifrs-smes:AdministrativeExpense | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_001 | TOTAL OPERATING EXPENSES | ifrs-smes:AdministrativeExpense | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_001 | TOTAL OPERATING EXPENSES | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_001 | TOTAL OPERATING EXPENSES | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | Loss after taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | Term loan R DISCUSSIONE | ifrs-smes:Borrowings | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | Term loan R DISCUSSIONE | ifrs-smes:Borrowings | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | Amount due to director a | ssmt-mpers:OtherCurrentPayablesDueToRelatedParties | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | Amount due to director a | ssmt-mpers:OtherCurrentPayablesDueToRelatedParties | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | Total non - current liabilities w | ifrs-smes:NoncurrentLiabilities | not_recoverable | exact_qname_value_period_match | target_family_not_in_low_risk_recovery_scope |
| case_002 | Total non - current liabilities w | ifrs-smes:NoncurrentLiabilities | not_recoverable | exact_qname_value_period_match | target_family_not_in_low_risk_recovery_scope |
| case_002 | Other payables and accruals fprables | ssmt-mpers:CurrentNontradeAccruals | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | Other payables and accruals fprables | ssmt-mpers:CurrentNontradeAccruals | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | Term loan on | ifrs-smes:Borrowings | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | Term loan on | ifrs-smes:Borrowings | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | Gross profit PL% | ifrs-smes:GrossProfit | not_recoverable | exact_qname_value_period_match | target_family_not_in_low_risk_recovery_scope |
| case_002 | Other operating expenses | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | Other operating expenses | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | Other operating expenses | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | Other operating expenses | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | Loss from operating activities | ssmt-mpers:ProfitLossFromOperatingActivities | still_blocked_correctly | qname_exists_but_value_mismatch | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | Loss from operating activities | ssmt-mpers:ProfitLossFromOperatingActivities | still_blocked_correctly | qname_exists_but_value_mismatch | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | Add : Other income | ifrs-smes:OtherIncome | recovered_low_risk | exact_qname_value_period_match | other_income_exact_main_statement_recovery |
| case_002 | Add : Other income | ifrs-smes:OtherIncome | recovered_low_risk | exact_qname_value_period_match | other_income_exact_main_statement_recovery |
| case_002 | Loss for the financial year | ifrs-smes:ProfitLoss | still_blocked_high_risk | qname_value_match_period_uncertain | profit_loss_recovery_conditions_not_met |
| case_002 | Loss for the financial year | ifrs-smes:ProfitLoss | still_blocked_high_risk | qname_value_match_period_uncertain | profit_loss_recovery_conditions_not_met |
| case_002 | Loss for the financial year | ifrs-smes:ProfitLoss | still_blocked_high_risk | qname_value_match_period_uncertain | profit_loss_recovery_conditions_not_met |
| case_002 | Loss for the financial year | ifrs-smes:ProfitLoss | still_blocked_high_risk | qname_value_match_period_uncertain | profit_loss_recovery_conditions_not_met |
| case_002 | Depreciation of property, plant and equipment | ifrs-smes:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | Depreciation of property, plant and equipment | ifrs-smes:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | Depreciation of property, plant and equipment | ifrs-smes:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | Depreciation of property, plant and equipment | ifrs-smes:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | Net cash to investing activities | ifrs-smes:CashFlowsFromUsedInInvestingActivities | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | Net cash to investing activities | ifrs-smes:CashFlowsFromUsedInInvestingActivities | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | Loss before taxation :selected: (77,641) | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | Taxation at Malaysian rate of 15% | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_correctly | qname_exists_but_value_mismatch | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | Taxation at Malaysian rate of 15% | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_correctly | qname_exists_but_value_mismatch | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | Tax expenses for the year | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_high_risk | exact_qname_value_period_match | income_tax_expense_recovery_conditions_not_met |
| case_002 | Tax expenses for the year | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_high_risk | exact_qname_value_period_match | income_tax_expense_recovery_conditions_not_met |
| case_002 | GROSS PROFIT CLEISION | ifrs-smes:GrossProfit | not_recoverable | exact_qname_value_period_match | target_family_not_in_low_risk_recovery_scope |
| case_002 | GROSS PROFIT CLEISION | ifrs-smes:GrossProfit | not_recoverable | exact_qname_value_period_match | target_family_not_in_low_risk_recovery_scope |
| case_002 | Less : OPERATING EXPENSES (SCHEDULE II) | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | Less : OPERATING EXPENSES (SCHEDULE II) | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | Less : OPERATING EXPENSES (SCHEDULE II) | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | Less : OPERATING EXPENSES (SCHEDULE II) | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | LOSS FROM OPERATING ACTIVITIES DISATTIES | ssmt-mpers:ProfitLossFromOperatingActivities | still_blocked_correctly | qname_exists_but_value_mismatch | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | LOSS FROM OPERATING ACTIVITIES DISATTIES | ssmt-mpers:ProfitLossFromOperatingActivities | still_blocked_correctly | qname_exists_but_value_mismatch | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | Bank charges | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | Bank charges | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | TOTAL OPERATING EXPENSES | ifrs-smes:AdministrativeExpense | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | TOTAL OPERATING EXPENSES | ifrs-smes:AdministrativeExpense | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | TOTAL OPERATING EXPENSES | ifrs-smes:AdministrativeExpense | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_002 | TOTAL OPERATING EXPENSES | ifrs-smes:AdministrativeExpense | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_003 | Loss after taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_correctly | qname_exists_but_value_mismatch | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_003 | Retained profits :unselected: | ifrs-smes:RetainedEarnings | still_blocked_correctly | qname_exists_but_value_mismatch | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_003 | Retained profits :unselected: | ifrs-smes:RetainedEarnings | not_recoverable | exact_qname_value_period_match | target_family_not_in_low_risk_recovery_scope |
| case_003 | Other payables and accruals | ssmt-mpers:CurrentNontradeAccruals | not_recoverable | exact_qname_value_period_match | target_family_not_in_low_risk_recovery_scope |
| case_003 | Other payables and accruals | ssmt-mpers:CurrentNontradeAccruals | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_003 | Other operating expenses | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_003 | Other operating expenses | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_003 | Other operating expenses | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_003 | Other operating expenses | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_003 | Loss from operating activities | ssmt-mpers:ProfitLossFromOperatingActivities | still_blocked_correctly | qname_exists_but_value_mismatch | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_003 | Loss from operating activities | ssmt-mpers:ProfitLossFromOperatingActivities | still_blocked_correctly | qname_exists_but_value_mismatch | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_003 | Add : Other income | ifrs-smes:OtherIncome | recovered_low_risk | exact_qname_value_period_match | other_income_exact_main_statement_recovery |
| case_003 | Add : Other income | ifrs-smes:OtherIncome | still_blocked_correctly | qname_exists_but_value_mismatch | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_003 | Loss for the financial year | ifrs-smes:ProfitLoss | still_blocked_high_risk | qname_value_match_period_uncertain | profit_loss_recovery_conditions_not_met |
| case_003 | Loss for the financial year | ifrs-smes:ProfitLoss | still_blocked_high_risk | qname_value_match_period_uncertain | profit_loss_recovery_conditions_not_met |
| case_003 | Loss for the financial year | ifrs-smes:ProfitLoss | still_blocked_high_risk | qname_value_match_period_uncertain | profit_loss_recovery_conditions_not_met |
| case_003 | Loss for the financial year | ifrs-smes:ProfitLoss | still_blocked_correctly | qname_exists_but_value_mismatch | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_003 | Taxation at statutory tax rate of 15% | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_correctly | qname_exists_but_value_mismatch | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_003 | Taxation at statutory tax rate of 15% | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_correctly | qname_exists_but_value_mismatch | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_003 | Over provision for taxation prior year | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_003 | Over provision for taxation prior year | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_high_risk | exact_qname_value_period_match | income_tax_expense_recovery_conditions_not_met |
| case_003 | Tax expenses for the year | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_003 | Tax expenses for the year | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_high_risk | exact_qname_value_period_match | income_tax_expense_recovery_conditions_not_met |
| case_003 | Bank charges | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_003 | Bank charges | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_003 | TOTAL OPERATING EXPENSES | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_003 | TOTAL OPERATING EXPENSES | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_003 | TOTAL OPERATING EXPENSES | ifrs-smes:AdministrativeExpense | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_003 | TOTAL OPERATING EXPENSES | ifrs-smes:AdministrativeExpense | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_004 | Loss after taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_004 | Other payables and accruals | ssmt-mpers:CurrentNontradeAccruals | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_004 | Other payables and accruals | ssmt-mpers:CurrentNontradeAccruals | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_004 | Loss from operating activities | ssmt-mpers:ProfitLossFromOperatingActivities | not_recoverable | exact_qname_value_period_match | target_family_not_in_low_risk_recovery_scope |
| case_004 | Add : Other income :- .FROS | ifrs-smes:OtherIncome | recovered_low_risk | exact_qname_value_period_match | other_income_exact_main_statement_recovery |
| case_004 | Loss for the financial year | ifrs-smes:ProfitLoss | still_blocked_high_risk | qname_value_match_period_uncertain | profit_loss_recovery_conditions_not_met |
| case_004 | Loss for the financial year | ifrs-smes:ProfitLoss | still_blocked_high_risk | qname_value_match_period_uncertain | profit_loss_recovery_conditions_not_met |
| case_004 | Loss for the financial year | ifrs-smes:ProfitLoss | still_blocked_high_risk | qname_value_match_period_uncertain | profit_loss_recovery_conditions_not_met |
| case_004 | Loss for the financial year | ifrs-smes:ProfitLoss | still_blocked_high_risk | qname_value_match_period_uncertain | profit_loss_recovery_conditions_not_met |
| case_004 | Cash flows from operating activities Loss before taxation | ifrs-smes:CashFlowsFromUsedInOperatingActivities | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_004 | Cash flows from operating activities Loss before taxation | ifrs-smes:CashFlowsFromUsedInOperatingActivities | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_004 | Decrease in property, plant and equipment | ifrs-smes:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_004 | Decrease in property, plant and equipment | ifrs-smes:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_004 | Decrease in property, plant and equipment | ifrs-smes:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_004 | Decrease in property, plant and equipment | ifrs-smes:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_004 | Net cash from / (to) operating activities | ifrs-smes:CashFlowsFromUsedInOperatingActivities | not_recoverable | exact_qname_value_period_match | target_family_not_in_low_risk_recovery_scope |
| case_004 | Net cash from / (to) operating activities | ifrs-smes:CashFlowsFromUsedInOperatingActivities | not_recoverable | exact_qname_value_period_match | target_family_not_in_low_risk_recovery_scope |
| case_004 | Cash and cash equivalents at beginning of the year | ifrs-smes:CashAndCashEquivalents | not_recoverable | qname_value_match_period_uncertain | target_family_not_in_low_risk_recovery_scope |
| case_004 | Cash and cash equivalents at beginning of the year | ifrs-smes:CashAndCashEquivalents | not_recoverable | qname_value_match_period_uncertain | target_family_not_in_low_risk_recovery_scope |
| case_004 | Loss before taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_004 | Loss before taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_004 | Taxation at statutory tax rate of 15% | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_004 | Taxation at statutory tax rate of 15% | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_004 | Tax expenses for the year | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_004 | Tax expenses for the year | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_004 | Taxation fee | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_004 | Taxation fee | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | TOTAL ASSETS DISCUSSION) | ifrs-smes:Assets | not_recoverable | exact_qname_value_period_match | target_family_not_in_low_risk_recovery_scope |
| case_005 | TOTAL ASSETS DISCUSSION) | ifrs-smes:Assets | not_recoverable | exact_qname_value_period_match | target_family_not_in_low_risk_recovery_scope |
| case_005 | Term loan | ifrs-smes:Borrowings | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | Term loan | ifrs-smes:Borrowings | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | Total non current liabilities toachat | ifrs-smes:NoncurrentLiabilities | still_blocked_correctly | qname_exists_but_value_mismatch | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | Total non current liabilities toachat | ifrs-smes:NoncurrentLiabilities | still_blocked_correctly | qname_exists_but_value_mismatch | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | Other payables and accruals clean | ssmt-mpers:CurrentNontradeAccruals | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | Other payables and accruals clean | ssmt-mpers:CurrentNontradeAccruals | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | Term loan | ifrs-smes:Borrowings | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | Term loan | ifrs-smes:Borrowings | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | Other operating expenses | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | Other operating expenses | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | Other operating expenses | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | Other operating expenses | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | Loss from operating activities | ssmt-mpers:ProfitLossFromOperatingActivities | still_blocked_correctly | qname_exists_but_value_mismatch | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | Loss from operating activities | ssmt-mpers:ProfitLossFromOperatingActivities | still_blocked_correctly | qname_exists_but_value_mismatch | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | Cash flows from operating activities Loss before taxation | ifrs-smes:CashFlowsFromUsedInOperatingActivities | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | Cash flows from operating activities Loss before taxation | ifrs-smes:CashFlowsFromUsedInOperatingActivities | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | Adjustments for :- Depreciation of property, plant and equipment | ifrs-smes:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | Adjustments for :- Depreciation of property, plant and equipment | ifrs-smes:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | Adjustments for :- Depreciation of property, plant and equipment | ifrs-smes:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | Adjustments for :- Depreciation of property, plant and equipment | ifrs-smes:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | Loss before taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | Loss before taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | Taxation at statutory tax rate of 15% | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | Taxation at statutory tax rate of 15% | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | Tax expenses for the financial year | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | Tax expenses for the financial year | ifrs-smes:IncomeTaxExpenseContinuingOperations | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | Secretarial fee | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | Secretarial fee | ifrs-smes:AdministrativeExpense | still_blocked_correctly | predicted_qname_not_found_in_xbrl | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | TOTAL OPERATING EXPENSES FOLAViceRal | ifrs-smes:AdministrativeExpense | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | TOTAL OPERATING EXPENSES FOLAViceRal | ifrs-smes:AdministrativeExpense | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | TOTAL OPERATING EXPENSES FOLAViceRal | ifrs-smes:AdministrativeExpense | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
| case_005 | TOTAL OPERATING EXPENSES FOLAViceRal | ifrs-smes:AdministrativeExpense | still_blocked_correctly | value_exists_but_different_qname | candidate_not_in_18e_d_overblocked_true_positive_set |
