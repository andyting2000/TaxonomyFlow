# Dictionary/Row-Order Tightened Mapper - Feature #18E-B-2-hotfix-1

- feature: 18E-B-2-hotfix-1
- generated_at: 2026-06-21T13:37:19Z
- total_pdf_row_value_observations: 782
- hardened_rules_loaded: 13
- advisory_suggestions_count: 20
- review_required_suggestions_count: 332
- conflicts_count: 0
- no_match_count: 430
- safe_for_auto_apply_count: 0
- requires_human_review_count: 782
- no_suggestion_safe_for_auto_apply: True
- explicit_auto_apply_statement: No #18E-B-2-hotfix-1 suggestion is safe for auto-apply; human review remains required.
- newly_covered_count: 14
- blocked_candidate_count: 148

| Sample | Label | QName | Status | Reason |
| --- | --- | --- | --- | --- |
| case_001 | Profit after taxation | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_001 | Accumulated losses brought forward | None | not_evaluable | no matching hardened rule |
| case_001 | Retained profits carried forward | None | not_evaluable | no matching hardened rule |
| case_001 | Dr Ooi Boon Beng | None | not_evaluable | no matching hardened rule |
| case_001 | Dr Ooi Boon Beng | None | not_evaluable | no matching hardened rule |
| case_001 | Ung Ming Xian | None | not_evaluable | no matching hardened rule |
| case_001 | Ung Ming Xian | None | not_evaluable | no matching hardened rule |
| case_001 | Other receivables | ifrs-smes:TradeAndOtherCurrentReceivables | qname_value_match_period_uncertain | context_optimized_candidate_requires_review, context_rule_not_advisory_safe, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_001 | Cash at bank | ssmt:CashAndBankBalances | exact_qname_value_period_match | context_optimized_candidate_requires_review, context_rule_not_advisory_safe, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_001 | Cash at bank | ssmt:CashAndBankBalances | exact_qname_value_period_match | context_optimized_candidate_requires_review, context_rule_not_advisory_safe, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_001 | Total current assets | ifrs-smes:CurrentAssets | exact_qname_value_period_match | hardened_rule_requires_review, generic_label_requires_review, missing_section_context, known_false_positive_risk |
| case_001 | Total current assets | ifrs-smes:CurrentAssets | exact_qname_value_period_match | hardened_rule_requires_review, generic_label_requires_review, missing_section_context, known_false_positive_risk |
| case_001 | TOTAL ASSETS DISCUSSION | None | not_evaluable | no matching hardened rule |
| case_001 | TOTAL ASSETS DISCUSSION | None | not_evaluable | no matching hardened rule |
| case_001 | Share capital | None | not_evaluable | no matching hardened rule |
| case_001 | Share capital | None | not_evaluable | no matching hardened rule |
| case_001 | Retained profits / (Accumulated losses) | None | not_evaluable | no matching hardened rule |
| case_001 | Retained profits / (Accumulated losses) | None | not_evaluable | no matching hardened rule |
| case_001 | Total shareholders' equity | ifrs-smes:Equity | qname_exists_but_value_mismatch | context_optimized_candidate_requires_review, context_rule_not_advisory_safe, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review, total_semantics_required |
| case_001 | Total shareholders' equity | ifrs-smes:Equity | ambiguous_xbrl_support | context_optimized_candidate_requires_review, context_rule_not_advisory_safe, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review, total_semantics_required |
| case_001 | Other payables and accruals | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | context_optimized_candidate_requires_review, context_rule_not_advisory_safe, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_001 | Other payables and accruals | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | context_optimized_candidate_requires_review, context_rule_not_advisory_safe, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_001 | Amount due to director | None | not_evaluable | no matching hardened rule |
| case_001 | Amount due to director | None | not_evaluable | no matching hardened rule |
| case_001 | Provision for taxation | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_001 | Provision for taxation | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_001 | Total current liabilities | ifrs-smes:CurrentLiabilities | qname_exists_but_value_mismatch | context_optimized_candidate_requires_review, context_rule_not_advisory_safe, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review, total_semantics_required |
| case_001 | Total current liabilities | ifrs-smes:CurrentLiabilities | exact_qname_value_period_match | context_optimized_candidate_requires_review, context_rule_not_advisory_safe, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review, total_semantics_required |
| case_001 | TOTAL EQUITY AND LIABILITIES DRAFT WIE | ifrs-smes:EquityAndLiabilities | exact_qname_value_period_match | context_optimized_candidate_requires_review, context_rule_not_advisory_safe, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review, total_semantics_required |
| case_001 | TOTAL EQUITY AND LIABILITIES DRAFT WIE | ifrs-smes:EquityAndLiabilities | exact_qname_value_period_match | context_optimized_candidate_requires_review, context_rule_not_advisory_safe, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review, total_semantics_required |
| case_001 | Turnover | ifrs-smes:Revenue | qname_value_match_period_uncertain | context_optimized_candidate_requires_review |
| case_001 | Less : Cost of sales | ifrs-smes:CostOfSales | qname_value_match_period_uncertain | statement_template_candidate_requires_review |
| case_001 | Gross profit | ifrs-smes:GrossProfit | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_001 | Gross profit | ifrs-smes:GrossProfit | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_001 | Staff costs | ifrs-smes:WagesAndSalaries | value_exists_but_different_qname | statement_template_candidate_requires_review |
| case_001 | Staff costs | ifrs-smes:WagesAndSalaries | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_001 | Other operating costs | None | not_evaluable | administrative_expense_component_dictionary_blocked, administrative_expense_component_row_order_blocked, dictionary_candidate_requires_review, row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_001 | Other operating costs | None | not_evaluable | administrative_expense_component_dictionary_blocked, administrative_expense_component_row_order_blocked, dictionary_candidate_requires_review, row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_001 | Profit / (Loss) from operating activities | None | not_evaluable | operating_result_row_order_requires_total_or_subtotal, row_order_candidate_requires_review |
| case_001 | Profit / (Loss) from operating activities | None | not_evaluable | operating_result_row_order_requires_total_or_subtotal, row_order_candidate_requires_review |
| case_001 | Add : Other income | ifrs-smes:OtherIncome | exact_qname_value_period_match | dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_001 | Add : Other income | ifrs-smes:OtherIncome | exact_qname_value_period_match | dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_001 | Profit / (Loss) before taxation | ifrs-smes:ProfitLossBeforeTax | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_001 | Profit / (Loss) before taxation | ifrs-smes:ProfitLossBeforeTax | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_001 | Less : Taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | context_optimized_candidate_requires_review |
| case_001 | Less : Taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_001 | Total comprehensive profit / (loss) for the year / period | ifrs-smes:ProfitLoss | qname_exists_but_value_mismatch | dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_001 | Total comprehensive profit / (loss) for the year / period | ifrs-smes:ProfitLoss | ambiguous_xbrl_support | dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_001 | Comprehensive loss for the period | ifrs-smes:ComprehensiveIncome | qname_value_match_period_uncertain | row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_001 | Comprehensive loss for the period | ifrs-smes:ComprehensiveIncome | qname_value_match_period_uncertain | row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_001 | Comprehensive profit for the year | None | not_evaluable | dictionary_candidate_requires_review, row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold, unstable_comprehensive_income_equity_alias_blocked |
| case_001 | Comprehensive profit for the year | None | not_evaluable | dictionary_candidate_requires_review, row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold, unstable_comprehensive_income_equity_alias_blocked |
| case_001 | Cash flows from operating activities Profit / (Loss) before taxation | None | not_evaluable | cash_flow_header_or_component_blocked, cash_flow_total_requires_exact_total_label, dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked, row_order_candidate_requires_review |
| case_001 | Cash flows from operating activities Profit / (Loss) before taxation | None | not_evaluable | cash_flow_header_or_component_blocked, cash_flow_total_requires_exact_total_label, dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked, row_order_candidate_requires_review |
| case_001 | Operating profit / ( loss) before working capital changes | None | not_evaluable | no matching hardened rule |
| case_001 | Operating profit / ( loss) before working capital changes | None | not_evaluable | no matching hardened rule |
| case_001 | Increase other receivables | None | not_evaluable | no matching hardened rule |
| case_001 | Increase other receivables | None | not_evaluable | no matching hardened rule |
| case_001 | Increase in amount due to director | None | not_evaluable | no matching hardened rule |
| case_001 | Increase in amount due to director | None | not_evaluable | no matching hardened rule |
| case_001 | Increase in other payables and accruals | None | not_evaluable | no matching hardened rule |
| case_001 | Increase in other payables and accruals | None | not_evaluable | no matching hardened rule |
| case_001 | Net cash from operating activities | ifrs-smes:CashFlowsFromUsedInOperatingActivities | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_001 | Net cash from operating activities | ifrs-smes:CashFlowsFromUsedInOperatingActivities | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_001 | Cash flows from investing activities | ifrs-smes:CashFlowsFromUsedInInvestingActivities | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_001 | Cash flows from investing activities | ifrs-smes:CashFlowsFromUsedInInvestingActivities | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_001 | Net increase in cash and cash equivalents | ifrs-smes:IncreaseDecreaseInCashAndCashEquivalents | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_001 | Net increase in cash and cash equivalents | ifrs-smes:IncreaseDecreaseInCashAndCashEquivalents | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_001 | Cash and cash equivalents at beginning of year / period | ifrs-smes:CashAndCashEquivalents | qname_value_match_period_uncertain | cash_flow_cash_equivalents_requires_review, dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_001 | Cash and cash equivalents at beginning of year / period | ifrs-smes:CashAndCashEquivalents | qname_value_match_period_uncertain | cash_flow_cash_equivalents_requires_review, dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_001 | Cash and cash equivalents at end of year / period | ifrs-smes:CashAndCashEquivalents | qname_value_match_period_uncertain | statement_template_candidate_requires_review |
| case_001 | Cash and cash equivalents at end of year / period | ifrs-smes:CashAndCashEquivalents | qname_value_match_period_uncertain | statement_template_candidate_requires_review |
| case_001 | Profit / (Loss) before taxation | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_001 | Profit / (Loss) before taxation | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_001 | Taxation at tax rates of - 15% | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_001 | Taxation at tax rates of - 15% | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_001 | Expenses not deductible for tax purposes | None | not_evaluable | no matching hardened rule |
| case_001 | Expenses not deductible for tax purposes | None | not_evaluable | no matching hardened rule |
| case_001 | Tax expenses for the year | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_001 | Tax expenses for the year | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_001 | Other payables | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | context_optimized_candidate_requires_review, context_rule_not_advisory_safe, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_001 | Other payables | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | context_optimized_candidate_requires_review, context_rule_not_advisory_safe, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_001 | At beginning and end of the financial year / period | None | not_evaluable | no matching hardened rule |
| case_001 | At beginning and end of the financial year / period | None | not_evaluable | no matching hardened rule |
| case_001 | Accruals | None | not_evaluable | no matching hardened rule |
| case_001 | Accruals | None | not_evaluable | no matching hardened rule |
| case_001 | Audit fee | ssmt-mpers:AuditorsRemuneration | exact_qname_value_period_match | statement_template_candidate_requires_review, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_001 | Audit fee | ssmt-mpers:AuditorsRemuneration | exact_qname_value_period_match | statement_template_candidate_requires_review, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_001 | EPF Contribution | None | not_evaluable | no matching hardened rule |
| case_001 | EPF Contribution | None | not_evaluable | no matching hardened rule |
| case_001 | Director's fee | None | not_evaluable | no matching hardened rule |
| case_001 | Director's fee | None | not_evaluable | no matching hardened rule |
| case_001 | Rental of office | None | not_evaluable | no matching hardened rule |
| case_001 | Rental of office | None | not_evaluable | no matching hardened rule |
| case_001 | EPF Contribution | ifrs-smes:WagesAndSalaries | qname_exists_but_value_mismatch | statement_template_candidate_requires_review |
| case_001 | EPF Contribution | ifrs-smes:WagesAndSalaries | qname_value_match_period_uncertain | statement_template_candidate_requires_review |
| case_001 | EIS Contribution | ifrs-smes:WagesAndSalaries | qname_exists_but_value_mismatch | statement_template_candidate_requires_review, note_linked_candidate_requires_review |
| case_001 | EIS Contribution | ifrs-smes:WagesAndSalaries | qname_value_match_period_uncertain | statement_template_candidate_requires_review, note_linked_candidate_requires_review |
| case_001 | Salaries | ifrs-smes:WagesAndSalaries | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_001 | Salaries | ifrs-smes:WagesAndSalaries | qname_value_match_period_uncertain | statement_template_candidate_requires_review |
| case_001 | SOCSO Contribution | ifrs-smes:WagesAndSalaries | qname_exists_but_value_mismatch | statement_template_candidate_requires_review |
| case_001 | SOCSO Contribution | ifrs-smes:WagesAndSalaries | qname_value_match_period_uncertain | statement_template_candidate_requires_review |
| case_001 | Accounting fee | None | not_evaluable | no matching hardened rule |
| case_001 | Accounting fee | None | not_evaluable | no matching hardened rule |
| case_001 | Auditors' remuneration | ssmt-mpers:AuditorsRemuneration | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_001 | Auditors' remuneration | ssmt-mpers:AuditorsRemuneration | qname_value_match_period_uncertain | statement_template_candidate_requires_review |
| case_001 | Advertisement | None | not_evaluable | no matching hardened rule |
| case_001 | Advertisement | None | not_evaluable | no matching hardened rule |
| case_001 | Bank charges | None | not_evaluable | administrative_expense_component_row_order_blocked, row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_001 | Bank charges | None | not_evaluable | administrative_expense_component_row_order_blocked, row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_001 | Commission paid | None | not_evaluable | no matching hardened rule |
| case_001 | Commission paid | None | not_evaluable | no matching hardened rule |
| case_001 | Computer rental fee | None | not_evaluable | no matching hardened rule |
| case_001 | Computer rental fee | None | not_evaluable | no matching hardened rule |
| case_001 | Commissioner for oaths | None | not_evaluable | no matching hardened rule |
| case_001 | Commissioner for oaths | None | not_evaluable | no matching hardened rule |
| case_001 | Director's fee | ssmt-mpers:DirectorsFees | predicted_qname_not_found_in_xbrl | statement_template_candidate_requires_review |
| case_001 | Director's fee | ssmt-mpers:DirectorsFees | predicted_qname_not_found_in_xbrl | statement_template_candidate_requires_review |
| case_001 | HR table maintenance | None | not_evaluable | no matching hardened rule |
| case_001 | Membership fee | None | not_evaluable | no matching hardened rule |
| case_001 | Membership fee | None | not_evaluable | no matching hardened rule |
| case_001 | Payroll fee | None | not_evaluable | no matching hardened rule |
| case_001 | Payroll fee | None | not_evaluable | no matching hardened rule |
| case_001 | Penalties | None | not_evaluable | no matching hardened rule |
| case_001 | Penalties | None | not_evaluable | no matching hardened rule |
| case_001 | Printing and stationeries FOR DISCUSSION | None | not_evaluable | no matching hardened rule |
| case_001 | Printing and stationeries FOR DISCUSSION | None | not_evaluable | no matching hardened rule |
| case_001 | Rental of office | None | not_evaluable | no matching hardened rule |
| case_001 | Rental of office | None | not_evaluable | no matching hardened rule |
| case_001 | Secretarial fee | None | not_evaluable | administrative_expense_component_row_order_blocked, row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_001 | Secretarial fee | None | not_evaluable | administrative_expense_component_row_order_blocked, row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_001 | Seminar fee | None | not_evaluable | no matching hardened rule |
| case_001 | Taxation fee | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | context_optimized_candidate_requires_review |
| case_001 | Taxation fee | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_value_match_period_uncertain | context_optimized_candidate_requires_review |
| case_001 | Travelling | None | not_evaluable | no matching hardened rule |
| case_001 | Upkeep of office equipment | None | not_evaluable | no matching hardened rule |
| case_001 | Upkeep of office equipment | None | not_evaluable | no matching hardened rule |
| case_001 | Website maintenance fee | None | not_evaluable | no matching hardened rule |
| case_001 | Web building fee | None | not_evaluable | no matching hardened rule |
| case_001 | Web building fee | None | not_evaluable | no matching hardened rule |
| case_001 | TOTAL OPERATING EXPENSES | ifrs-smes:OtherExpenseByFunction | exact_qname_value_period_match | administrative_expense_component_dictionary_blocked, dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked, row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_001 | TOTAL OPERATING EXPENSES | ifrs-smes:OtherExpenseByFunction | qname_value_match_period_uncertain | administrative_expense_component_dictionary_blocked, dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked, row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_002 | Loss after taxation | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_002 | Accumulated losses carried forward | None | not_evaluable | no matching hardened rule |
| case_002 | Accumulated losses carried forward | None | not_evaluable | no matching hardened rule |
| case_002 | Ooi Boon Beng | None | not_evaluable | no matching hardened rule |
| case_002 | Ooi Boon Beng | None | not_evaluable | no matching hardened rule |
| case_002 | Ung Ming Xian (f) MAN kan 5,000 DE THE | None | not_evaluable | no matching hardened rule |
| case_002 | Ung Ming Xian (f) MAN kan 5,000 DE THE | None | not_evaluable | no matching hardened rule |
| case_002 | Property, plant and equipment | ifrs-smes:PropertyPlantAndEquipment | exact_qname_value_period_match |  |
| case_002 | Property, plant and equipment | ifrs-smes:PropertyPlantAndEquipment | exact_qname_value_period_match |  |
| case_002 | Total non-current assets | ifrs-smes:NoncurrentAssets | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_002 | Total non-current assets | ifrs-smes:NoncurrentAssets | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_002 | Trade receivables | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | context_optimized_candidate_requires_review |
| case_002 | Trade receivables | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | context_optimized_candidate_requires_review |
| case_002 | Other receivables and deposits | ifrs-smes:TradeAndOtherCurrentReceivables | exact_qname_value_period_match | context_optimized_candidate_requires_review, statement_template_candidate_requires_review, template_candidate_conflicts_with_existing_prediction |
| case_002 | Other receivables and deposits | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | context_optimized_candidate_requires_review, statement_template_candidate_requires_review, template_candidate_conflicts_with_existing_prediction |
| case_002 | Bank balances | ssmt:CashAndBankBalances | exact_qname_value_period_match |  |
| case_002 | Bank balances | ssmt:CashAndBankBalances | exact_qname_value_period_match |  |
| case_002 | Total current assets | ifrs-smes:CurrentAssets | exact_qname_value_period_match | hardened_rule_requires_review, generic_label_requires_review, known_false_positive_risk |
| case_002 | Total current assets | ifrs-smes:CurrentAssets | exact_qname_value_period_match | hardened_rule_requires_review, generic_label_requires_review, known_false_positive_risk |
| case_002 | TOTAL ASSETS | ifrs-smes:Assets | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_002 | TOTAL ASSETS | ifrs-smes:Assets | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_002 | Accumulated losses | ifrs-smes:RetainedEarnings | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_002 | Accumulated losses | ifrs-smes:RetainedEarnings | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_002 | Total equity | ifrs-smes:Equity | ambiguous_xbrl_support | context_optimized_candidate_requires_review |
| case_002 | Total equity | ifrs-smes:Equity | ambiguous_xbrl_support | context_optimized_candidate_requires_review |
| case_002 | Term loan R DISCUSSIONE | ssmt-mpers:NoncurrentPortionOfNoncurrentSecuredBankLoansReceived | exact_qname_value_period_match | borrowings_specificity_requires_note_or_current_noncurrent_boundary, dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_002 | Term loan R DISCUSSIONE | ssmt-mpers:NoncurrentPortionOfNoncurrentSecuredBankLoansReceived | exact_qname_value_period_match | borrowings_specificity_requires_note_or_current_noncurrent_boundary, dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_002 | Amount due to director a | ssmt-mpers:OtherNoncurrentLiabilities | exact_qname_value_period_match | dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_002 | Amount due to director a | ssmt-mpers:OtherNoncurrentLiabilities | exact_qname_value_period_match | dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_002 | Total non - current liabilities w | ifrs-smes:NoncurrentLiabilities | exact_qname_value_period_match | dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_002 | Total non - current liabilities w | ifrs-smes:NoncurrentLiabilities | exact_qname_value_period_match | dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_002 | Other payables and accruals fprables | ifrs-smes:TradeAndOtherCurrentPayables | exact_qname_value_period_match | dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_002 | Other payables and accruals fprables | ifrs-smes:TradeAndOtherCurrentPayables | exact_qname_value_period_match | dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_002 | Term loan on | None | not_evaluable | borrowings_specificity_requires_note_or_current_noncurrent_boundary, dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_002 | Term loan on | None | not_evaluable | borrowings_specificity_requires_note_or_current_noncurrent_boundary, dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_002 | Provision for taxation | ifrs-smes:CurrentTaxLiabilitiesCurrent | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_002 | Provision for taxation | ifrs-smes:CurrentTaxLiabilitiesCurrent | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_002 | Total current liabilities | ifrs-smes:CurrentLiabilities | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_002 | Total current liabilities | ifrs-smes:CurrentLiabilities | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_002 | Total Liabilities | ifrs-smes:Liabilities | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_002 | Total Liabilities | ifrs-smes:Liabilities | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_002 | TOTAL EQUITY AND LIABILITIES | ifrs-smes:EquityAndLiabilities | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_002 | TOTAL EQUITY AND LIABILITIES | ifrs-smes:EquityAndLiabilities | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_002 | Turnover 56,984 :unselected: | ifrs-smes:Revenue | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_002 | Less : Cost of sales POSE (31,632) | ifrs-smes:CostOfSales | qname_exists_but_value_mismatch | statement_template_candidate_requires_review |
| case_002 | Gross profit PL% | ifrs-smes:GrossProfit | exact_qname_value_period_match | dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_002 | Other operating expenses | None | not_evaluable | administrative_expense_component_dictionary_blocked, administrative_expense_component_row_order_blocked, dictionary_candidate_requires_review, row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_002 | Other operating expenses | None | not_evaluable | administrative_expense_component_dictionary_blocked, administrative_expense_component_row_order_blocked, dictionary_candidate_requires_review, row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_002 | Loss from operating activities | None | not_evaluable | operating_result_row_order_requires_total_or_subtotal, row_order_candidate_requires_review |
| case_002 | Loss from operating activities | None | not_evaluable | operating_result_row_order_requires_total_or_subtotal, row_order_candidate_requires_review |
| case_002 | Add : Other income | ifrs-smes:OtherIncome | exact_qname_value_period_match | dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_002 | Add : Other income | ifrs-smes:OtherIncome | exact_qname_value_period_match | dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_002 | Less : Taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | context_optimized_candidate_requires_review |
| case_002 | Less : Taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_002 | Loss for the financial year DRAFT FOR DISCUSSION | ifrs-smes:ProfitLoss | ambiguous_xbrl_support | context_optimized_candidate_requires_review |
| case_002 | Loss for the financial year DRAFT FOR DISCUSSION | ifrs-smes:ProfitLoss | ambiguous_xbrl_support | context_optimized_candidate_requires_review |
| case_002 | Loss for the financial year | ifrs-smes:ProfitLoss | qname_value_match_period_uncertain | row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_002 | Loss for the financial year | ifrs-smes:ProfitLoss | qname_value_match_period_uncertain | row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_002 | Loss for the financial year | ifrs-smes:ProfitLoss | qname_value_match_period_uncertain | row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_002 | Loss for the financial year | ifrs-smes:ProfitLoss | qname_value_match_period_uncertain | row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_002 | Depreciation of property, plant and equipment | ssmt-mpers:AdjustmentsForDepreciationExpense | exact_qname_value_period_match | cash_flow_ppe_purchase_requires_purchase_or_acquisition_label, dictionary_candidate_requires_review, row_order_candidate_requires_review |
| case_002 | Depreciation of property, plant and equipment | ssmt-mpers:AdjustmentsForDepreciationExpense | exact_qname_value_period_match | cash_flow_ppe_purchase_requires_purchase_or_acquisition_label, dictionary_candidate_requires_review, row_order_candidate_requires_review |
| case_002 | Operating profit / (loss) before working capital changes | None | not_evaluable | no matching hardened rule |
| case_002 | Operating profit / (loss) before working capital changes | None | not_evaluable | no matching hardened rule |
| case_002 | Decrease in trade and other receivables | None | not_evaluable | no matching hardened rule |
| case_002 | Decrease in trade and other receivables | None | not_evaluable | no matching hardened rule |
| case_002 | Increase in other payables and accruals | None | not_evaluable | no matching hardened rule |
| case_002 | Increase in other payables and accruals | None | not_evaluable | no matching hardened rule |
| case_002 | Increase in amount due to director | None | not_evaluable | no matching hardened rule |
| case_002 | Net cash from operating activities | ifrs-smes:CashFlowsFromUsedInOperatingActivities | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_002 | Net cash from operating activities | ifrs-smes:CashFlowsFromUsedInOperatingActivities | value_exists_but_different_qname | statement_template_candidate_requires_review |
| case_002 | Taxation paid | None | not_evaluable | no matching hardened rule |
| case_002 | Taxation paid | None | not_evaluable | no matching hardened rule |
| case_002 | Cash flows from investing activities | ifrs-smes:CashFlowsFromUsedInInvestingActivities | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_002 | Cash flows from investing activities | ifrs-smes:CashFlowsFromUsedInInvestingActivities | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_002 | Repayment of term loan | None | not_evaluable | no matching hardened rule |
| case_002 | Repayment of term loan | None | not_evaluable | no matching hardened rule |
| case_002 | Net cash to investing activities | ifrs-smes:CashFlowsFromUsedInInvestingActivities | value_exists_but_different_qname | cash_flow_total_requires_exact_total_label, row_order_candidate_requires_review |
| case_002 | Net cash to investing activities | ifrs-smes:CashFlowsFromUsedInInvestingActivities | value_exists_but_different_qname | cash_flow_total_requires_exact_total_label, row_order_candidate_requires_review |
| case_002 | Net (decrease) / increase in cash and cash equivalents | ifrs-smes:IncreaseDecreaseInCashAndCashEquivalents | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_002 | Net (decrease) / increase in cash and cash equivalents | ifrs-smes:IncreaseDecreaseInCashAndCashEquivalents | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_002 | Cash and cash equivalents at beginning of year | ifrs-smes:CashAndCashEquivalents | qname_value_match_period_uncertain | statement_template_candidate_requires_review |
| case_002 | Cash and cash equivalents at beginning of year | ifrs-smes:CashAndCashEquivalents | qname_value_match_period_uncertain | statement_template_candidate_requires_review |
| case_002 | Cash and cash equivalents at the end of year | ifrs-smes:CashAndCashEquivalents | qname_value_match_period_uncertain | statement_template_candidate_requires_review |
| case_002 | Cash and cash equivalents at the end of year | ifrs-smes:CashAndCashEquivalents | qname_value_match_period_uncertain | statement_template_candidate_requires_review |
| case_002 | Bank balances | ifrs-smes:CashAndCashEquivalents | qname_value_match_period_uncertain | statement_template_candidate_requires_review |
| case_002 | Bank balances | ifrs-smes:CashAndCashEquivalents | qname_value_match_period_uncertain | statement_template_candidate_requires_review |
| case_002 | Addition | None | not_evaluable | no matching hardened rule |
| case_002 | Addition | None | not_evaluable | no matching hardened rule |
| case_002 | Disposal | None | not_evaluable | no matching hardened rule |
| case_002 | Disposal | None | not_evaluable | no matching hardened rule |
| case_002 | Charges | None | not_evaluable | no matching hardened rule |
| case_002 | Charges | None | not_evaluable | no matching hardened rule |
| case_002 | 1 1 | None | not_evaluable | no matching hardened rule |
| case_002 | 1 1 | None | not_evaluable | no matching hardened rule |
| case_002 | 1 1 | None | not_evaluable | no matching hardened rule |
| case_002 | 1 1 | None | not_evaluable | no matching hardened rule |
| case_002 | Other receivables | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | context_optimized_candidate_requires_review, context_rule_not_advisory_safe, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_002 | Other deposits | None | not_evaluable | no matching hardened rule |
| case_002 | Other deposits | None | not_evaluable | no matching hardened rule |
| case_002 | Tax refundable | None | not_evaluable | no matching hardened rule |
| case_002 | Tax refundable | None | not_evaluable | no matching hardened rule |
| case_002 | At beginning and end of the year | None | not_evaluable | no matching hardened rule |
| case_002 | At beginning and end of the year | None | not_evaluable | no matching hardened rule |
| case_002 | Amount payable | None | not_evaluable | no matching hardened rule |
| case_002 | Amount payable | None | not_evaluable | no matching hardened rule |
| case_002 | Less: Interests in suspense STR | None | not_evaluable | no matching hardened rule |
| case_002 | Less: Interests in suspense STR | None | not_evaluable | no matching hardened rule |
| case_002 | TO Less: Due more than twelve months | None | not_evaluable | no matching hardened rule |
| case_002 | TO Less: Due more than twelve months | None | not_evaluable | no matching hardened rule |
| case_002 | DRATET DUE | None | not_evaluable | no matching hardened rule |
| case_002 | DRATET DUE | None | not_evaluable | no matching hardened rule |
| case_002 | Other payables | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | context_optimized_candidate_requires_review, context_rule_not_advisory_safe, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_002 | Other payables | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | context_optimized_candidate_requires_review, context_rule_not_advisory_safe, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_002 | Accuals | None | not_evaluable | no matching hardened rule |
| case_002 | Accuals | None | not_evaluable | no matching hardened rule |
| case_002 | Depreciation of property, plant equipment | None | not_evaluable | no matching hardened rule |
| case_002 | Depreciation of property, plant equipment | None | not_evaluable | no matching hardened rule |
| case_002 | Directors' remuneration | ssmt-mpers:DirectorsRemuneration | exact_qname_value_period_match | statement_template_candidate_requires_review, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_002 | Directors' remuneration | ssmt-mpers:DirectorsRemuneration | exact_qname_value_period_match | statement_template_candidate_requires_review, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_002 | Term loan interests | None | not_evaluable | no matching hardened rule |
| case_002 | Term loan interests | None | not_evaluable | no matching hardened rule |
| case_002 | and crediting :- Rental received | None | not_evaluable | no matching hardened rule |
| case_002 | Loss before taxation :selected: (77,641) | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_002 | Taxation at Malaysian rate of 15% | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_002 | Taxation at Malaysian rate of 15% | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_002 | Non-taxable income | None | not_evaluable | no matching hardened rule |
| case_002 | Non-taxable income | None | not_evaluable | no matching hardened rule |
| case_002 | Expenses not deductible for tax purposes | None | not_evaluable | no matching hardened rule |
| case_002 | Expenses not deductible for tax purposes | None | not_evaluable | no matching hardened rule |
| case_002 | Effect on unabsorbed losses :selected: | None | not_evaluable | no matching hardened rule |
| case_002 | Tax expenses for the year | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_002 | Tax expenses for the year | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_002 | Sales P& RPOSE | ifrs-smes:Revenue | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_002 | Purchases | None | not_evaluable | no matching hardened rule |
| case_002 | Purchases | None | not_evaluable | no matching hardened rule |
| case_002 | GROSS PROFIT CLEISION | ifrs-smes:GrossProfit | exact_qname_value_period_match | dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_002 | GROSS PROFIT CLEISION | ifrs-smes:GrossProfit | exact_qname_value_period_match | dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_002 | Less : OPERATING EXPENSES (SCHEDULE II) | None | not_evaluable | administrative_expense_component_dictionary_blocked, administrative_expense_component_row_order_blocked, dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked, row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_002 | Less : OPERATING EXPENSES (SCHEDULE II) | None | not_evaluable | administrative_expense_component_dictionary_blocked, administrative_expense_component_row_order_blocked, dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked, row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_002 | LOSS FROM OPERATING ACTIVITIES DISATTIES | None | not_evaluable | operating_result_row_order_requires_total_or_subtotal, row_order_candidate_requires_review |
| case_002 | LOSS FROM OPERATING ACTIVITIES DISATTIES | None | not_evaluable | operating_result_row_order_requires_total_or_subtotal, row_order_candidate_requires_review |
| case_002 | Other income | ifrs-smes:OtherIncome | value_exists_but_different_qname | context_optimized_candidate_requires_review |
| case_002 | Other income | ifrs-smes:OtherIncome | value_exists_but_different_qname | context_optimized_candidate_requires_review |
| case_002 | Rental received | ssmt-mpers:OtherRentalIncomeOnLandAndBuildings | exact_qname_value_period_match | dictionary_candidate_conflicts_with_existing_prediction, dictionary_row_order_candidate_requires_review |
| case_002 | Rental received | ssmt-mpers:OtherRentalIncomeOnLandAndBuildings | exact_qname_value_period_match | dictionary_candidate_conflicts_with_existing_prediction, dictionary_row_order_candidate_requires_review |
| case_002 | LOSS FOR THE FINANCIAL YEAR DRAFT REFINAR | ifrs-smes:ProfitLoss | value_exists_but_different_qname | context_optimized_candidate_requires_review |
| case_002 | LOSS FOR THE FINANCIAL YEAR DRAFT REFINAR | ifrs-smes:ProfitLoss | ambiguous_xbrl_support | context_optimized_candidate_requires_review |
| case_002 | BR&SE 28,203 | None | not_evaluable | no matching hardened rule |
| case_002 | Accounting fee | None | not_evaluable | no matching hardened rule |
| case_002 | Accounting fee | None | not_evaluable | no matching hardened rule |
| case_002 | Bank charges | None | not_evaluable | administrative_expense_component_row_order_blocked, row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_002 | Bank charges | None | not_evaluable | administrative_expense_component_row_order_blocked, row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_002 | Commission paid :unselected: | None | not_evaluable | no matching hardened rule |
| case_002 | Commissioner for oaths :unselected: | None | not_evaluable | no matching hardened rule |
| case_002 | Commissioner for oaths :unselected: | None | not_evaluable | no matching hardened rule |
| case_002 | Computer rental :unselected: | None | not_evaluable | no matching hardened rule |
| case_002 | Director's remuneration | ssmt-mpers:DirectorsRemuneration | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_002 | Director's remuneration | ssmt-mpers:DirectorsRemuneration | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_002 | Insurance | None | not_evaluable | no matching hardened rule |
| case_002 | Insurance | None | not_evaluable | no matching hardened rule |
| case_002 | Legal fee | None | not_evaluable | no matching hardened rule |
| case_002 | Maintenance fees building | None | not_evaluable | no matching hardened rule |
| case_002 | Maintenance fees building | None | not_evaluable | no matching hardened rule |
| case_002 | Penalties R DISCUSSION | None | not_evaluable | no matching hardened rule |
| case_002 | Penalties R DISCUSSION | None | not_evaluable | no matching hardened rule |
| case_002 | Petrol | None | not_evaluable | no matching hardened rule |
| case_002 | Printing and stationeries akescheda | None | not_evaluable | no matching hardened rule |
| case_002 | Printing and stationeries akescheda | None | not_evaluable | no matching hardened rule |
| case_002 | Quit rent and assessment | None | not_evaluable | no matching hardened rule |
| case_002 | Quit rent and assessment | None | not_evaluable | no matching hardened rule |
| case_002 | Taxation fee zaplatilade fel | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | context_optimized_candidate_requires_review |
| case_002 | Taxation fee zaplatilade fel | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | context_optimized_candidate_requires_review |
| case_002 | Taxation processing fee | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | context_optimized_candidate_requires_review |
| case_002 | Taxation processing fee | ifrs-smes:IncomeTaxExpenseContinuingOperations | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_002 | Term loan interests | ifrs-smes:FinanceCosts | qname_exists_but_value_mismatch | context_optimized_candidate_requires_review |
| case_002 | Term loan interests | ifrs-smes:FinanceCosts | qname_exists_but_value_mismatch | context_optimized_candidate_requires_review |
| case_002 | Telephone & fax charges | None | not_evaluable | no matching hardened rule |
| case_002 | Telephone & fax charges | None | not_evaluable | no matching hardened rule |
| case_002 | Web hosting | None | not_evaluable | no matching hardened rule |
| case_002 | Web hosting | None | not_evaluable | no matching hardened rule |
| case_002 | TOTAL OPERATING EXPENSES | ifrs-smes:OtherExpenseByFunction | exact_qname_value_period_match | administrative_expense_component_dictionary_blocked, dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked, row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_002 | TOTAL OPERATING EXPENSES | ifrs-smes:OtherExpenseByFunction | exact_qname_value_period_match | administrative_expense_component_dictionary_blocked, dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked, row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_003 | Loss after taxation | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_003 | Retained profits brought forward | None | not_evaluable | no matching hardened rule |
| case_003 | Retained profits carried forward | None | not_evaluable | no matching hardened rule |
| case_003 | Ooi Boon Beng | None | not_evaluable | no matching hardened rule |
| case_003 | Ooi Boon Beng | None | not_evaluable | no matching hardened rule |
| case_003 | Ung Ming Xin (f) | None | not_evaluable | no matching hardened rule |
| case_003 | Ung Ming Xin (f) | None | not_evaluable | no matching hardened rule |
| case_003 | Property, plant and equipment | ifrs-smes:PropertyPlantAndEquipment | exact_qname_value_period_match |  |
| case_003 | Property, plant and equipment | ifrs-smes:PropertyPlantAndEquipment | exact_qname_value_period_match |  |
| case_003 | Investments | None | not_evaluable | no matching hardened rule |
| case_003 | Investments | None | not_evaluable | no matching hardened rule |
| case_003 | Total non-current assets | ifrs-smes:NoncurrentAssets | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_003 | Total non-current assets | ifrs-smes:NoncurrentAssets | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_003 | Trade receivables | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | context_optimized_candidate_requires_review |
| case_003 | Trade receivables | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | context_optimized_candidate_requires_review |
| case_003 | Other receivables, deposits and prepayments | ifrs-smes:TradeAndOtherCurrentReceivables | qname_exists_but_value_mismatch | context_optimized_candidate_requires_review, statement_template_candidate_requires_review, template_candidate_conflicts_with_existing_prediction |
| case_003 | Other receivables, deposits and prepayments | ifrs-smes:TradeAndOtherCurrentReceivables | qname_exists_but_value_mismatch | context_optimized_candidate_requires_review, statement_template_candidate_requires_review, template_candidate_conflicts_with_existing_prediction |
| case_003 | Amount due from directors | None | not_evaluable | no matching hardened rule |
| case_003 | Amount due from directors | None | not_evaluable | no matching hardened rule |
| case_003 | Bank balances | ssmt:CashAndBankBalances | exact_qname_value_period_match |  |
| case_003 | Bank balances | ssmt:CashAndBankBalances | exact_qname_value_period_match |  |
| case_003 | Total current assets | ifrs-smes:CurrentAssets | qname_exists_but_value_mismatch | hardened_rule_requires_review, generic_label_requires_review, known_false_positive_risk |
| case_003 | Total current assets | ifrs-smes:CurrentAssets | exact_qname_value_period_match | hardened_rule_requires_review, generic_label_requires_review, known_false_positive_risk |
| case_003 | TOTAL ASSETS | ifrs-smes:Assets | qname_exists_but_value_mismatch | context_optimized_candidate_requires_review |
| case_003 | TOTAL ASSETS | ifrs-smes:Assets | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_003 | Retained profits :unselected: | ifrs-smes:RetainedEarnings | qname_exists_but_value_mismatch | dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_003 | Retained profits :unselected: | ifrs-smes:RetainedEarnings | exact_qname_value_period_match | dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_003 | Total equity | ifrs-smes:Equity | qname_exists_but_value_mismatch | context_optimized_candidate_requires_review |
| case_003 | Total equity | ifrs-smes:Equity | ambiguous_xbrl_support | context_optimized_candidate_requires_review |
| case_003 | Amount due to directors | ssmt-mpers:OtherCurrentPayablesDueToRelatedParties | exact_qname_value_period_match | statement_template_candidate_requires_review, note_linked_candidate_requires_review |
| case_003 | Amount due to directors | ssmt-mpers:OtherCurrentPayablesDueToRelatedParties | exact_qname_value_period_match | statement_template_candidate_requires_review, note_linked_candidate_requires_review |
| case_003 | Total non current liabilities | ifrs-smes:NoncurrentLiabilities | value_exists_but_different_qname | context_optimized_candidate_requires_review |
| case_003 | Total non current liabilities | ifrs-smes:NoncurrentLiabilities | value_exists_but_different_qname | context_optimized_candidate_requires_review |
| case_003 | Other payables and accruals | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_003 | Other payables and accruals | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_003 | Total current liabilities | ifrs-smes:CurrentLiabilities | value_exists_but_different_qname | context_optimized_candidate_requires_review |
| case_003 | Total current liabilities | ifrs-smes:CurrentLiabilities | value_exists_but_different_qname | context_optimized_candidate_requires_review |
| case_003 | Total liabilities | ifrs-smes:Liabilities | value_exists_but_different_qname | context_optimized_candidate_requires_review |
| case_003 | Total liabilities | ifrs-smes:Liabilities | value_exists_but_different_qname | context_optimized_candidate_requires_review |
| case_003 | TOTAL EQUITY AND LIABILITIES | ifrs-smes:EquityAndLiabilities | qname_exists_but_value_mismatch | context_optimized_candidate_requires_review |
| case_003 | TOTAL EQUITY AND LIABILITIES | ifrs-smes:EquityAndLiabilities | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_003 | Turnover | ifrs-smes:Revenue | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_003 | Turnover | ifrs-smes:Revenue | value_exists_but_different_qname | context_optimized_candidate_requires_review |
| case_003 | Other operating expenses | None | not_evaluable | administrative_expense_component_dictionary_blocked, administrative_expense_component_row_order_blocked, dictionary_candidate_requires_review, row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_003 | Other operating expenses | None | not_evaluable | administrative_expense_component_dictionary_blocked, administrative_expense_component_row_order_blocked, dictionary_candidate_requires_review, row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_003 | Equipment expenses | None | not_evaluable | no matching hardened rule |
| case_003 | Equipment expenses | None | not_evaluable | no matching hardened rule |
| case_003 | Loss from operating activities | None | not_evaluable | operating_result_row_order_requires_total_or_subtotal, row_order_candidate_requires_review |
| case_003 | Loss from operating activities | None | not_evaluable | operating_result_row_order_requires_total_or_subtotal, row_order_candidate_requires_review |
| case_003 | Add : Other income | ifrs-smes:OtherIncome | exact_qname_value_period_match | dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_003 | Add : Other income | ifrs-smes:OtherIncome | qname_exists_but_value_mismatch | dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_003 | (Less) / Add : Taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | context_optimized_candidate_requires_review |
| case_003 | (Less) / Add : Taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | context_optimized_candidate_requires_review |
| case_003 | Loss for the financial year DRAFT FOR | ifrs-smes:ProfitLoss | qname_exists_but_value_mismatch | context_optimized_candidate_requires_review |
| case_003 | Loss for the financial year DRAFT FOR | ifrs-smes:ProfitLoss | ambiguous_xbrl_support | context_optimized_candidate_requires_review |
| case_003 | Loss for the financial year | ifrs-smes:ProfitLoss | qname_value_match_period_uncertain | row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_003 | Loss for the financial year | ifrs-smes:ProfitLoss | qname_value_match_period_uncertain | row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_003 | Loss for the financial year | ifrs-smes:ProfitLoss | qname_value_match_period_uncertain | row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_003 | Loss for the financial year | ifrs-smes:ProfitLoss | qname_exists_but_value_mismatch | row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_003 | Loss before taxation (8,163) BURROSE | None | not_evaluable | no matching hardened rule |
| case_003 | Operating loss before working capital changes | None | not_evaluable | no matching hardened rule |
| case_003 | Operating loss before working capital changes | None | not_evaluable | no matching hardened rule |
| case_003 | (Decrease)/ Increase in trade and other receivables | None | not_evaluable | no matching hardened rule |
| case_003 | (Increase) / Decrease in trade and other payables GES (11,100) | None | not_evaluable | no matching hardened rule |
| case_003 | Decrease in amount due from Directors | None | not_evaluable | no matching hardened rule |
| case_003 | Decrease in amount due from Directors | None | not_evaluable | no matching hardened rule |
| case_003 | Net cash from operating activities | ifrs-smes:CashFlowsFromUsedInOperatingActivities | exact_qname_value_period_match | statement_template_candidate_requires_review, note_linked_candidate_requires_review |
| case_003 | Net cash from operating activities | ifrs-smes:CashFlowsFromUsedInOperatingActivities | exact_qname_value_period_match | statement_template_candidate_requires_review, note_linked_candidate_requires_review |
| case_003 | Cash flows from investing activities | ifrs-smes:CashFlowsFromUsedInInvestingActivities | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_003 | Cash flows from investing activities | ifrs-smes:CashFlowsFromUsedInInvestingActivities | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_003 | Cash flows from financing activities | ifrs-smes:CashFlowsFromUsedInFinancingActivities | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_003 | Cash flows from financing activities | ifrs-smes:CashFlowsFromUsedInFinancingActivities | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_003 | Net increase in cash and cash equivalent | None | not_evaluable | no matching hardened rule |
| case_003 | Net increase in cash and cash equivalent | None | not_evaluable | no matching hardened rule |
| case_003 | Cash and cash equivalent at beginning of the year | None | not_evaluable | no matching hardened rule |
| case_003 | Cash and cash equivalent at beginning of the year | None | not_evaluable | no matching hardened rule |
| case_003 | Cash and cash equivalent at the end of the year | None | not_evaluable | no matching hardened rule |
| case_003 | Cash and cash equivalent at the end of the year | None | not_evaluable | no matching hardened rule |
| case_003 | Bank balances | ifrs-smes:CashAndCashEquivalents | qname_value_match_period_uncertain | statement_template_candidate_requires_review |
| case_003 | Bank balances | ifrs-smes:CashAndCashEquivalents | qname_value_match_period_uncertain | statement_template_candidate_requires_review |
| case_003 | As at 31/12/23 | None | not_evaluable | no matching hardened rule |
| case_003 | As at 31/12/23 | None | not_evaluable | no matching hardened rule |
| case_003 | Addition | None | not_evaluable | no matching hardened rule |
| case_003 | Addition | None | not_evaluable | no matching hardened rule |
| case_003 | Disposal | None | not_evaluable | no matching hardened rule |
| case_003 | Disposal | None | not_evaluable | no matching hardened rule |
| case_003 | As at 31/12/24 | None | not_evaluable | no matching hardened rule |
| case_003 | As at 31/12/24 | None | not_evaluable | no matching hardened rule |
| case_003 | Current charges | None | not_evaluable | no matching hardened rule |
| case_003 | Current charges | None | not_evaluable | no matching hardened rule |
| case_003 | As at 31/12/23 1 1 | None | not_evaluable | no matching hardened rule |
| case_003 | As at 31/12/23 1 1 | None | not_evaluable | no matching hardened rule |
| case_003 | As at 31/12/24 1 1 PURPOSE | None | not_evaluable | no matching hardened rule |
| case_003 | As at 31/12/24 1 1 PURPOSE | None | not_evaluable | no matching hardened rule |
| case_003 | Unquoted shares at cost | None | not_evaluable | no matching hardened rule |
| case_003 | Unquoted shares at cost | None | not_evaluable | no matching hardened rule |
| case_003 | Other receivables | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | context_optimized_candidate_requires_review, context_rule_not_advisory_safe, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_003 | Other receivables | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | context_optimized_candidate_requires_review, context_rule_not_advisory_safe, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_003 | Other payables | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | context_optimized_candidate_requires_review, context_rule_not_advisory_safe, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_003 | Other payables | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | context_optimized_candidate_requires_review, context_rule_not_advisory_safe, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_003 | Deposits | None | not_evaluable | no matching hardened rule |
| case_003 | At beginning and end of the year | None | not_evaluable | no matching hardened rule |
| case_003 | At beginning and end of the year | None | not_evaluable | no matching hardened rule |
| case_003 | Deposits | None | not_evaluable | no matching hardened rule |
| case_003 | Deposits | None | not_evaluable | no matching hardened rule |
| case_003 | Prepayments | None | not_evaluable | no matching hardened rule |
| case_003 | Prepayments | None | not_evaluable | no matching hardened rule |
| case_003 | Auditors' remuneration | ssmt-mpers:AuditorsRemuneration | exact_qname_value_period_match | statement_template_candidate_requires_review, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_003 | Auditors' remuneration | ssmt-mpers:AuditorsRemuneration | exact_qname_value_period_match | statement_template_candidate_requires_review, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_003 | Taxation at statutory tax rate of 15% | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_003 | Taxation at statutory tax rate of 15% | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_003 | Director's remuneration | ssmt-mpers:DirectorsRemuneration | exact_qname_value_period_match | statement_template_candidate_requires_review, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_003 | Director's remuneration | ssmt-mpers:DirectorsRemuneration | exact_qname_value_period_match | statement_template_candidate_requires_review, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_003 | Expenses not deductible for tax purposes | None | not_evaluable | no matching hardened rule |
| case_003 | Expenses not deductible for tax purposes | None | not_evaluable | no matching hardened rule |
| case_003 | Effect of unabsorbed losses | None | not_evaluable | no matching hardened rule |
| case_003 | Effect of unabsorbed losses | None | not_evaluable | no matching hardened rule |
| case_003 | Interests income | None | not_evaluable | no matching hardened rule |
| case_003 | Over provision for taxation prior year | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_003 | Over provision for taxation prior year | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_003 | Tax expenses for the year | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_003 | Tax expenses for the year | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_003 | Provision based on these financial statements | None | not_evaluable | no matching hardened rule |
| case_003 | Provision based on these financial statements | None | not_evaluable | no matching hardened rule |
| case_003 | Over provision in prior year | None | not_evaluable | no matching hardened rule |
| case_003 | Over provision in prior year | None | not_evaluable | no matching hardened rule |
| case_003 | Professional fees | None | not_evaluable | no matching hardened rule |
| case_003 | Professional fees | None | not_evaluable | no matching hardened rule |
| case_003 | Interests income | None | not_evaluable | no matching hardened rule |
| case_003 | Computer | None | not_evaluable | no matching hardened rule |
| case_003 | Audit fees | ssmt-mpers:AuditorsRemuneration | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_003 | Audit fees | ssmt-mpers:AuditorsRemuneration | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_003 | Bank charges | None | not_evaluable | administrative_expense_component_row_order_blocked, row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_003 | Bank charges | None | not_evaluable | administrative_expense_component_row_order_blocked, row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_003 | Commissioner for oaths | None | not_evaluable | no matching hardened rule |
| case_003 | Commissioner for oaths | None | not_evaluable | no matching hardened rule |
| case_003 | Director's salaries | ssmt-mpers:DirectorsRemuneration | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_003 | Director's salaries | ssmt-mpers:DirectorsRemuneration | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_003 | Printing and stationeries OR DISCUSSIONBROJRP | None | not_evaluable | no matching hardened rule |
| case_003 | Printing and stationeries OR DISCUSSIONBROJRP | None | not_evaluable | no matching hardened rule |
| case_003 | Seminar fee | None | not_evaluable | no matching hardened rule |
| case_003 | Taxation fee | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | context_optimized_candidate_requires_review |
| case_003 | Taxation fee | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | context_optimized_candidate_requires_review |
| case_003 | totalt Telephone, fax and postage | None | not_evaluable | no matching hardened rule |
| case_003 | totalt Telephone, fax and postage | None | not_evaluable | no matching hardened rule |
| case_003 | DRAcione | None | not_evaluable | no matching hardened rule |
| case_003 | DRAcione | None | not_evaluable | no matching hardened rule |
| case_003 | TOTAL OPERATING EXPENSES | ifrs-smes:OtherExpenseByFunction | qname_exists_but_value_mismatch | administrative_expense_component_dictionary_blocked, dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked, row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_003 | TOTAL OPERATING EXPENSES | ifrs-smes:OtherExpenseByFunction | exact_qname_value_period_match | administrative_expense_component_dictionary_blocked, dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked, row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_003 | LOSS FOR THE YEAR | ifrs-smes:ProfitLoss | qname_exists_but_value_mismatch | context_optimized_candidate_requires_review |
| case_003 | LOSS FOR THE YEAR | ifrs-smes:ProfitLoss | value_exists_but_different_qname | context_optimized_candidate_requires_review |
| case_004 | Loss after taxation | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_004 | Accumulated losses brought forward | None | not_evaluable | no matching hardened rule |
| case_004 | Accumulated losses carried forward | None | not_evaluable | no matching hardened rule |
| case_004 | Ooi Boon Beng | None | not_evaluable | no matching hardened rule |
| case_004 | Ooi Boon Beng | None | not_evaluable | no matching hardened rule |
| case_004 | Ung Ming Xian (f) | None | not_evaluable | no matching hardened rule |
| case_004 | Ung Ming Xian (f) | None | not_evaluable | no matching hardened rule |
| case_004 | Property, plant and equipment | ifrs-smes:PropertyPlantAndEquipment | exact_qname_value_period_match |  |
| case_004 | Property, plant and equipment | ifrs-smes:PropertyPlantAndEquipment | exact_qname_value_period_match |  |
| case_004 | Total non-current assets | ifrs-smes:NoncurrentAssets | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_004 | Total non-current assets | ifrs-smes:NoncurrentAssets | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_004 | Other deposits | ssmt-mpers:OtherCurrentNontradeDeposits | exact_qname_value_period_match | dictionary_row_order_candidate_requires_review, row_order_candidate_conflicts_with_existing_prediction, statement_template_candidate_requires_review |
| case_004 | Other deposits | ssmt-mpers:OtherCurrentNontradeDeposits | exact_qname_value_period_match | dictionary_row_order_candidate_requires_review, row_order_candidate_conflicts_with_existing_prediction, statement_template_candidate_requires_review |
| case_004 | Bank balances | ssmt:CashAndBankBalances | exact_qname_value_period_match |  |
| case_004 | Bank balances | ssmt:CashAndBankBalances | exact_qname_value_period_match |  |
| case_004 | Total current assets | ifrs-smes:CurrentAssets | exact_qname_value_period_match | hardened_rule_requires_review, generic_label_requires_review, known_false_positive_risk |
| case_004 | Total current assets | ifrs-smes:CurrentAssets | exact_qname_value_period_match | hardened_rule_requires_review, generic_label_requires_review, known_false_positive_risk |
| case_004 | TOTAL ASSETS | ifrs-smes:Assets | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_004 | TOTAL ASSETS | ifrs-smes:Assets | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_004 | Share capital | ifrs-smes:IssuedCapital | exact_qname_value_period_match | statement_template_candidate_requires_review, note_linked_candidate_requires_review |
| case_004 | Share capital | ifrs-smes:IssuedCapital | exact_qname_value_period_match | statement_template_candidate_requires_review, note_linked_candidate_requires_review |
| case_004 | Accumulated losses | ifrs-smes:RetainedEarnings | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_004 | Accumulated losses | ifrs-smes:RetainedEarnings | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_004 | Total equity | ifrs-smes:Equity | ambiguous_xbrl_support | context_optimized_candidate_requires_review |
| case_004 | Total equity | ifrs-smes:Equity | ambiguous_xbrl_support | context_optimized_candidate_requires_review |
| case_004 | Amount due to directors | ssmt-mpers:OtherCurrentPayablesDueToRelatedParties | value_exists_but_different_qname | statement_template_candidate_requires_review, note_linked_candidate_requires_review |
| case_004 | Amount due to directors | ssmt-mpers:OtherCurrentPayablesDueToRelatedParties | value_exists_but_different_qname | statement_template_candidate_requires_review, note_linked_candidate_requires_review |
| case_004 | Total deferred liabilities | None | not_evaluable | no matching hardened rule |
| case_004 | Total deferred liabilities | None | not_evaluable | no matching hardened rule |
| case_004 | Other payables and accruals | ifrs-smes:TradeAndOtherCurrentPayables | exact_qname_value_period_match | dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_004 | Other payables and accruals | ifrs-smes:TradeAndOtherCurrentPayables | exact_qname_value_period_match | dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_004 | Total current liabilities | ifrs-smes:CurrentLiabilities | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_004 | Total current liabilities | ifrs-smes:CurrentLiabilities | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_004 | Total liabilities | ifrs-smes:Liabilities | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_004 | Total liabilities | ifrs-smes:Liabilities | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_004 | TOTAL EQUITY AND LIABILITIES | ifrs-smes:EquityAndLiabilities | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_004 | TOTAL EQUITY AND LIABILITIES | ifrs-smes:EquityAndLiabilities | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_004 | Turnover | ifrs-smes:Revenue | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_004 | Loss from operating activities | None | not_evaluable | operating_result_row_order_requires_total_or_subtotal, row_order_candidate_requires_review |
| case_004 | Add : Other income :- .FROS | ifrs-smes:OtherIncome | exact_qname_value_period_match | dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_004 | Loss before taxation | ifrs-smes:ProfitLossBeforeTax | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_004 | Loss before taxation | ifrs-smes:ProfitLossBeforeTax | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_004 | Less : Taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | context_optimized_candidate_requires_review |
| case_004 | Less : Taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | context_optimized_candidate_requires_review |
| case_004 | Loss for the financial year | ifrs-smes:ProfitLoss | ambiguous_xbrl_support | context_optimized_candidate_requires_review |
| case_004 | Loss for the financial year | ifrs-smes:ProfitLoss | ambiguous_xbrl_support | context_optimized_candidate_requires_review |
| case_004 | Loss for the financial year | ifrs-smes:ProfitLoss | qname_value_match_period_uncertain | row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_004 | Loss for the financial year | ifrs-smes:ProfitLoss | qname_value_match_period_uncertain | row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_004 | Loss for the financial year | ifrs-smes:ProfitLoss | qname_value_match_period_uncertain | row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_004 | Loss for the financial year | ifrs-smes:ProfitLoss | qname_value_match_period_uncertain | row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_004 | Cash flows from operating activities Loss before taxation | None | not_evaluable | cash_flow_header_or_component_blocked, cash_flow_total_requires_exact_total_label, dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked, row_order_candidate_requires_review |
| case_004 | Decrease in property, plant and equipment | None | not_evaluable | cash_flow_ppe_purchase_requires_purchase_or_acquisition_label, dictionary_candidate_requires_review, row_order_candidate_requires_review |
| case_004 | Decrease in property, plant and equipment | None | not_evaluable | cash_flow_ppe_purchase_requires_purchase_or_acquisition_label, dictionary_candidate_requires_review, row_order_candidate_requires_review |
| case_004 | Operating loss before working capital changes | None | not_evaluable | no matching hardened rule |
| case_004 | Increase / (Decrease) in trade and other payables | None | not_evaluable | no matching hardened rule |
| case_004 | Increase / (Decrease) in trade and other payables | None | not_evaluable | no matching hardened rule |
| case_004 | Increase in amount due to director | None | not_evaluable | no matching hardened rule |
| case_004 | Increase in amount due to director | None | not_evaluable | no matching hardened rule |
| case_004 | Net cash from / (to) operating activities | ifrs-smes:CashFlowsFromUsedInOperatingActivities | exact_qname_value_period_match | cash_flow_total_requires_exact_total_label, row_order_candidate_requires_review |
| case_004 | Net cash from / (to) operating activities | ifrs-smes:CashFlowsFromUsedInOperatingActivities | exact_qname_value_period_match | cash_flow_total_requires_exact_total_label, row_order_candidate_requires_review |
| case_004 | Cash flows from investing activities | ifrs-smes:CashFlowsFromUsedInInvestingActivities | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_004 | Cash flows from investing activities | ifrs-smes:CashFlowsFromUsedInInvestingActivities | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_004 | Cash flows from financing activities | ifrs-smes:CashFlowsFromUsedInFinancingActivities | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_004 | Cash flows from financing activities | ifrs-smes:CashFlowsFromUsedInFinancingActivities | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_004 | Net increase / (decrease) in cash and cash equivalents | ifrs-smes:IncreaseDecreaseInCashAndCashEquivalents | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_004 | Net increase / (decrease) in cash and cash equivalents | ifrs-smes:IncreaseDecreaseInCashAndCashEquivalents | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_004 | Cash and cash equivalents at beginning of the year | ifrs-smes:CashAndCashEquivalents | qname_value_match_period_uncertain | cash_flow_cash_equivalents_requires_review, dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_004 | Cash and cash equivalents at beginning of the year | ifrs-smes:CashAndCashEquivalents | qname_value_match_period_uncertain | cash_flow_cash_equivalents_requires_review, dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_004 | Cash and cash equivalents at end of the year | ifrs-smes:CashAndCashEquivalents | qname_value_match_period_uncertain | statement_template_candidate_requires_review |
| case_004 | Cash and cash equivalents at end of the year | ifrs-smes:CashAndCashEquivalents | qname_value_match_period_uncertain | statement_template_candidate_requires_review |
| case_004 | Bank balances | ifrs-smes:CashAndCashEquivalents | qname_value_match_period_uncertain | statement_template_candidate_requires_review |
| case_004 | Bank balances | ifrs-smes:CashAndCashEquivalents | qname_value_match_period_uncertain | statement_template_candidate_requires_review |
| case_004 | Addition | None | not_evaluable | no matching hardened rule |
| case_004 | Addition | None | not_evaluable | no matching hardened rule |
| case_004 | At beginning and end of the year | None | not_evaluable | no matching hardened rule |
| case_004 | At beginning and end of the year | None | not_evaluable | no matching hardened rule |
| case_004 | Charges for the year | None | not_evaluable | no matching hardened rule |
| case_004 | Charges for the year | None | not_evaluable | no matching hardened rule |
| case_004 | 1 1 | None | not_evaluable | no matching hardened rule |
| case_004 | Loss before taxation | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_004 | Loss before taxation | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_004 | Auditor's remuneration | ssmt-mpers:AuditorsRemuneration | exact_qname_value_period_match | statement_template_candidate_requires_review, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_004 | Auditor's remuneration | ssmt-mpers:AuditorsRemuneration | exact_qname_value_period_match | statement_template_candidate_requires_review, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_004 | Taxation at statutory tax rate of 15% | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_004 | Taxation at statutory tax rate of 15% | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_004 | Directors' fees | ssmt-mpers:DirectorsRemuneration | exact_qname_value_period_match | statement_template_candidate_requires_review, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_004 | Directors' fees | ssmt-mpers:DirectorsRemuneration | exact_qname_value_period_match | statement_template_candidate_requires_review, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_004 | Expenses not deductible for tax purposes | None | not_evaluable | no matching hardened rule |
| case_004 | Expenses not deductible for tax purposes | None | not_evaluable | no matching hardened rule |
| case_004 | Research and development expenditure written off | None | not_evaluable | no matching hardened rule |
| case_004 | Research and development expenditure written off | None | not_evaluable | no matching hardened rule |
| case_004 | Tax expenses for the year | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_004 | Tax expenses for the year | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_004 | TURNOVER | None | not_evaluable | no matching hardened rule |
| case_004 | Auditor's remuneration | ssmt-mpers:AuditorsRemuneration | exact_qname_value_period_match | statement_template_candidate_requires_review, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_004 | Auditor's remuneration | ssmt-mpers:AuditorsRemuneration | exact_qname_value_period_match | statement_template_candidate_requires_review, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_004 | Bank charges | None | not_evaluable | no matching hardened rule |
| case_004 | Bank charges | None | not_evaluable | no matching hardened rule |
| case_004 | Commissioner for Oaths | None | not_evaluable | no matching hardened rule |
| case_004 | Commissioner for Oaths | None | not_evaluable | no matching hardened rule |
| case_004 | Directors' fee | ssmt-mpers:DirectorsRemuneration | exact_qname_value_period_match | statement_template_candidate_requires_review, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_004 | Directors' fee | ssmt-mpers:DirectorsRemuneration | exact_qname_value_period_match | statement_template_candidate_requires_review, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_004 | Printing and Stationery | None | not_evaluable | no matching hardened rule |
| case_004 | Printing and Stationery | None | not_evaluable | no matching hardened rule |
| case_004 | Research and development expenditure written off | None | not_evaluable | no matching hardened rule |
| case_004 | Research and development expenditure written off | None | not_evaluable | no matching hardened rule |
| case_004 | Secretarial fee | None | not_evaluable | no matching hardened rule |
| case_004 | Secretarial fee | None | not_evaluable | no matching hardened rule |
| case_004 | Taxation fee | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_004 | Taxation fee | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_004 | Telephone, fax charges and postage | None | not_evaluable | no matching hardened rule |
| case_004 | Telephone, fax charges and postage | None | not_evaluable | no matching hardened rule |
| case_004 | TOTAL OPERATING EXPENSES | None | not_evaluable | label matched rule but statement family did not match |
| case_004 | TOTAL OPERATING EXPENSES | None | not_evaluable | label matched rule but statement family did not match |
| case_004 | LOSS FOR THE YEAR | None | not_evaluable | no matching hardened rule |
| case_004 | LOSS FOR THE YEAR | None | not_evaluable | no matching hardened rule |
| case_005 | Accumulated losses brought forward | None | not_evaluable | no matching hardened rule |
| case_005 | Accumulated losses carried forward | None | not_evaluable | no matching hardened rule |
| case_005 | Ooi Boon Beng | None | not_evaluable | no matching hardened rule |
| case_005 | Ooi Boon Beng | None | not_evaluable | no matching hardened rule |
| case_005 | Ung Ming Xian (f) | None | not_evaluable | no matching hardened rule |
| case_005 | Ung Ming Xian (f) | None | not_evaluable | no matching hardened rule |
| case_005 | Property, plant and equipment | ifrs-smes:PropertyPlantAndEquipment | exact_qname_value_period_match |  |
| case_005 | Property, plant and equipment | ifrs-smes:PropertyPlantAndEquipment | exact_qname_value_period_match |  |
| case_005 | Total non-current assets | ifrs-smes:NoncurrentAssets | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_005 | Total non-current assets | ifrs-smes:NoncurrentAssets | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_005 | Trade receivables JE | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | context_optimized_candidate_requires_review |
| case_005 | Other receivables and deposits | ifrs-smes:TradeAndOtherCurrentReceivables | exact_qname_value_period_match | context_optimized_candidate_requires_review, statement_template_candidate_requires_review, template_candidate_conflicts_with_existing_prediction |
| case_005 | Other receivables and deposits | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | context_optimized_candidate_requires_review, statement_template_candidate_requires_review, template_candidate_conflicts_with_existing_prediction |
| case_005 | Bank balances | ssmt:CashAndBankBalances | exact_qname_value_period_match |  |
| case_005 | Bank balances | ssmt:CashAndBankBalances | exact_qname_value_period_match |  |
| case_005 | Total current assets | ifrs-smes:CurrentAssets | exact_qname_value_period_match | hardened_rule_requires_review, generic_label_requires_review, known_false_positive_risk |
| case_005 | Total current assets | ifrs-smes:CurrentAssets | exact_qname_value_period_match | hardened_rule_requires_review, generic_label_requires_review, known_false_positive_risk |
| case_005 | TOTAL ASSETS DISCUSSION) | None | not_evaluable | dictionary_candidate_requires_review, extraction_artifact_discussion_label_blocked, non_exact_dictionary_alias_blocked |
| case_005 | TOTAL ASSETS DISCUSSION) | None | not_evaluable | dictionary_candidate_requires_review, extraction_artifact_discussion_label_blocked, non_exact_dictionary_alias_blocked |
| case_005 | Share capital | ifrs-smes:IssuedCapital | exact_qname_value_period_match | statement_template_candidate_requires_review, note_linked_candidate_requires_review |
| case_005 | Share capital | ifrs-smes:IssuedCapital | exact_qname_value_period_match | statement_template_candidate_requires_review, note_linked_candidate_requires_review |
| case_005 | Accumulated Losses | ifrs-smes:RetainedEarnings | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_005 | Accumulated Losses | ifrs-smes:RetainedEarnings | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_005 | Total equity | ifrs-smes:Equity | ambiguous_xbrl_support | context_optimized_candidate_requires_review |
| case_005 | Total equity | ifrs-smes:Equity | ambiguous_xbrl_support | context_optimized_candidate_requires_review |
| case_005 | Term loan | None | not_evaluable | borrowings_specificity_requires_note_or_current_noncurrent_boundary, dictionary_candidate_requires_review |
| case_005 | Term loan | None | not_evaluable | borrowings_specificity_requires_note_or_current_noncurrent_boundary, dictionary_candidate_requires_review |
| case_005 | Amount due to directors | ssmt-mpers:OtherCurrentPayablesDueToRelatedParties | value_exists_but_different_qname | statement_template_candidate_requires_review, note_linked_candidate_requires_review |
| case_005 | Amount due to directors | ssmt-mpers:OtherCurrentPayablesDueToRelatedParties | value_exists_but_different_qname | statement_template_candidate_requires_review, note_linked_candidate_requires_review |
| case_005 | Total non current liabilities toachat | ifrs-smes:NoncurrentLiabilities | qname_exists_but_value_mismatch | dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_005 | Total non current liabilities toachat | ifrs-smes:NoncurrentLiabilities | qname_exists_but_value_mismatch | dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_005 | Other payables and accruals clean | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_005 | Other payables and accruals clean | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked |
| case_005 | Term loan | None | not_evaluable | borrowings_specificity_requires_note_or_current_noncurrent_boundary, dictionary_candidate_requires_review |
| case_005 | Term loan | None | not_evaluable | borrowings_specificity_requires_note_or_current_noncurrent_boundary, dictionary_candidate_requires_review |
| case_005 | in | None | not_evaluable | no matching hardened rule |
| case_005 | in | None | not_evaluable | no matching hardened rule |
| case_005 | Total liabilities D Por current Fral to | ifrs-smes:Liabilities | exact_qname_value_period_match | generic_label_requires_review |
| case_005 | TOTAL EQUITY AND LIABILITIES | ifrs-smes:EquityAndLiabilities | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_005 | TOTAL EQUITY AND LIABILITIES | ifrs-smes:EquityAndLiabilities | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_005 | Turnover | ifrs-smes:Revenue | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_005 | Less : Cost of sales | ifrs-smes:CostOfSales | qname_exists_but_value_mismatch | statement_template_candidate_requires_review |
| case_005 | Less : Cost of sales | ifrs-smes:CostOfSales | qname_exists_but_value_mismatch | statement_template_candidate_requires_review |
| case_005 | Gross profit | ifrs-smes:GrossProfit | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_005 | Depreciation | None | not_evaluable | no matching hardened rule |
| case_005 | Depreciation | None | not_evaluable | no matching hardened rule |
| case_005 | Other operating expenses | None | not_evaluable | administrative_expense_component_dictionary_blocked, administrative_expense_component_row_order_blocked, dictionary_candidate_requires_review, row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_005 | Other operating expenses | None | not_evaluable | administrative_expense_component_dictionary_blocked, administrative_expense_component_row_order_blocked, dictionary_candidate_requires_review, row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_005 | Staff costs | ifrs-smes:WagesAndSalaries | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_005 | Staff costs | ifrs-smes:WagesAndSalaries | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_005 | Loss from operating activities | None | not_evaluable | operating_result_row_order_requires_total_or_subtotal, row_order_candidate_requires_review |
| case_005 | Loss from operating activities | None | not_evaluable | operating_result_row_order_requires_total_or_subtotal, row_order_candidate_requires_review |
| case_005 | Other income | ifrs-smes:OtherIncome | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_005 | Other income | ifrs-smes:OtherIncome | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_005 | Loss before taxation | ifrs-smes:ProfitLossBeforeTax | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_005 | Loss before taxation | ifrs-smes:ProfitLossBeforeTax | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_005 | Less : Taxation DRAFT FÅCate | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | context_optimized_candidate_requires_review |
| case_005 | Less : Taxation DRAFT FÅCate | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | context_optimized_candidate_requires_review |
| case_005 | Cash flows from operating activities Loss before taxation | None | not_evaluable | cash_flow_header_or_component_blocked, cash_flow_total_requires_exact_total_label, dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked, row_order_candidate_requires_review |
| case_005 | Adjustments for :- Depreciation of property, plant and equipment | ssmt-mpers:AdjustmentsForDepreciationExpense | exact_qname_value_period_match | cash_flow_ppe_purchase_requires_purchase_or_acquisition_label, dictionary_candidate_requires_review, row_order_candidate_requires_review |
| case_005 | Adjustments for :- Depreciation of property, plant and equipment | ssmt-mpers:AdjustmentsForDepreciationExpense | exact_qname_value_period_match | cash_flow_ppe_purchase_requires_purchase_or_acquisition_label, dictionary_candidate_requires_review, row_order_candidate_requires_review |
| case_005 | Operating loss before working capital changes | None | not_evaluable | no matching hardened rule |
| case_005 | Operating loss before working capital changes | None | not_evaluable | no matching hardened rule |
| case_005 | Decrease / (Increase) in trade and other receivables | None | not_evaluable | no matching hardened rule |
| case_005 | Decrease / (Increase) in trade and other receivables | None | not_evaluable | no matching hardened rule |
| case_005 | Increase in trade and other payables | None | not_evaluable | no matching hardened rule |
| case_005 | Increase in trade and other payables | None | not_evaluable | no matching hardened rule |
| case_005 | Increase in amount due to directors | None | not_evaluable | no matching hardened rule |
| case_005 | Increase in amount due to directors | None | not_evaluable | no matching hardened rule |
| case_005 | Cash from operating activities | ifrs-smes:CashFlowsFromUsedInOperatingActivities | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_005 | Cash from operating activities | ifrs-smes:CashFlowsFromUsedInOperatingActivities | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_005 | Cash flows from investing activities | ifrs-smes:CashFlowsFromUsedInInvestingActivities | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_005 | Cash flows from investing activities | ifrs-smes:CashFlowsFromUsedInInvestingActivities | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_005 | Term loans repayments | ifrs-smes:CashFlowsFromUsedInFinancingActivities | exact_qname_value_period_match |  |
| case_005 | Term loans repayments | ifrs-smes:CashFlowsFromUsedInFinancingActivities | exact_qname_value_period_match |  |
| case_005 | Net (decrease) / increase in cash and cash equivalents | ifrs-smes:IncreaseDecreaseInCashAndCashEquivalents | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_005 | Net (decrease) / increase in cash and cash equivalents | ifrs-smes:IncreaseDecreaseInCashAndCashEquivalents | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_005 | Cash and cash equivalents at beginning of year | ifrs-smes:CashAndCashEquivalents | qname_value_match_period_uncertain | statement_template_candidate_requires_review |
| case_005 | Cash and cash equivalents at beginning of year | ifrs-smes:CashAndCashEquivalents | qname_value_match_period_uncertain | statement_template_candidate_requires_review |
| case_005 | Cash and cash equivalents at the end of year | ifrs-smes:CashAndCashEquivalents | qname_value_match_period_uncertain | statement_template_candidate_requires_review |
| case_005 | Cash and cash equivalents at the end of year | ifrs-smes:CashAndCashEquivalents | qname_value_match_period_uncertain | statement_template_candidate_requires_review |
| case_005 | Bank balances | ifrs-smes:CashAndCashEquivalents | qname_value_match_period_uncertain | statement_template_candidate_requires_review |
| case_005 | Bank balances | ifrs-smes:CashAndCashEquivalents | qname_value_match_period_uncertain | statement_template_candidate_requires_review |
| case_005 | Addition | None | not_evaluable | no matching hardened rule |
| case_005 | Addition | None | not_evaluable | no matching hardened rule |
| case_005 | Disposal | None | not_evaluable | no matching hardened rule |
| case_005 | Disposal | None | not_evaluable | no matching hardened rule |
| case_005 | Charges for the year 53 | None | not_evaluable | no matching hardened rule |
| case_005 | Charges for the year 53 | None | not_evaluable | no matching hardened rule |
| case_005 | Prior year | None | not_evaluable | no matching hardened rule |
| case_005 | Prior year | None | not_evaluable | no matching hardened rule |
| case_005 | Other receivables | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | context_optimized_candidate_requires_review, context_rule_not_advisory_safe, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_005 | Other receivables | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | context_optimized_candidate_requires_review, context_rule_not_advisory_safe, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_005 | Term loan No.1 | None | not_evaluable | no matching hardened rule |
| case_005 | Term loan No.1 | None | not_evaluable | no matching hardened rule |
| case_005 | Other payables | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | context_optimized_candidate_requires_review, context_rule_not_advisory_safe, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_005 | Other payables | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | context_optimized_candidate_requires_review, context_rule_not_advisory_safe, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_005 | Utilities deposits | ssmt-mpers:OtherCurrentNontradeDeposits | exact_qname_value_period_match | low_context_confidence_requires_review |
| case_005 | Utilities deposits | ssmt-mpers:OtherCurrentNontradeDeposits | exact_qname_value_period_match | low_context_confidence_requires_review |
| case_005 | Term loan No. 2 | None | not_evaluable | no matching hardened rule |
| case_005 | Term loan No. 2 | None | not_evaluable | no matching hardened rule |
| case_005 | Accruals | None | not_evaluable | no matching hardened rule |
| case_005 | Accruals | None | not_evaluable | no matching hardened rule |
| case_005 | Less : Interest in suspense | None | not_evaluable | no matching hardened rule |
| case_005 | Less : Due more than twelve months we.I | None | not_evaluable | no matching hardened rule |
| case_005 | Less : Due more than twelve months we.I | None | not_evaluable | no matching hardened rule |
| case_005 | cal- og atunshown | None | not_evaluable | no matching hardened rule |
| case_005 | cal- og atunshown | None | not_evaluable | no matching hardened rule |
| case_005 | Loss before taxation | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_005 | Loss before taxation | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_005 | Audit fee | ssmt-mpers:AuditorsRemuneration | exact_qname_value_period_match | statement_template_candidate_requires_review, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_005 | Audit fee | ssmt-mpers:AuditorsRemuneration | exact_qname_value_period_match | statement_template_candidate_requires_review, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_005 | Taxation at statutory tax rate of 15% | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_005 | Taxation at statutory tax rate of 15% | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_005 | Directors' remuneration | ssmt-mpers:DirectorsRemuneration | exact_qname_value_period_match | statement_template_candidate_requires_review, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_005 | Directors' remuneration | ssmt-mpers:DirectorsRemuneration | exact_qname_value_period_match | statement_template_candidate_requires_review, low_context_confidence_requires_review, non_main_statement_context_requires_review, notes_context_requires_review |
| case_005 | Expenses not deductible for tax purposes | None | not_evaluable | no matching hardened rule |
| case_005 | Expenses not deductible for tax purposes | None | not_evaluable | no matching hardened rule |
| case_005 | Depreciation of property, plant and equipment | None | not_evaluable | label matched rule but statement family did not match |
| case_005 | Depreciation of property, plant and equipment | None | not_evaluable | label matched rule but statement family did not match |
| case_005 | Effect of unabsorbed losses | None | not_evaluable | no matching hardened rule |
| case_005 | Effect of unabsorbed losses | None | not_evaluable | no matching hardened rule |
| case_005 | Term loan interests | None | not_evaluable | no matching hardened rule |
| case_005 | Term loan interests | None | not_evaluable | no matching hardened rule |
| case_005 | Tax expenses for the financial year | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_005 | Tax expenses for the financial year | None | not_evaluable | dictionary_candidate_requires_review, low_context_confidence_blocks_dictionary_candidate, missing_note_link_confirmation, note_detail_main_statement_concept_blocked, notes_context_requires_review |
| case_005 | Sales | ifrs-smes:Revenue | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_005 | Sales | ifrs-smes:Revenue | exact_qname_value_period_match | context_optimized_candidate_requires_review |
| case_005 | Add : Purchases | None | not_evaluable | no matching hardened rule |
| case_005 | Add : Purchases | None | not_evaluable | no matching hardened rule |
| case_005 | Less: Closing stocks | None | not_evaluable | no matching hardened rule |
| case_005 | Less: Closing stocks | None | not_evaluable | no matching hardened rule |
| case_005 | GROSS PROFIT | ifrs-smes:GrossProfit | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_005 | GROSS PROFIT | ifrs-smes:GrossProfit | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_005 | Commission | None | not_evaluable | no matching hardened rule |
| case_005 | Commission | None | not_evaluable | no matching hardened rule |
| case_005 | Payroll fee | None | not_evaluable | no matching hardened rule |
| case_005 | Payroll fee | None | not_evaluable | no matching hardened rule |
| case_005 | OR | None | not_evaluable | no matching hardened rule |
| case_005 | OR | None | not_evaluable | no matching hardened rule |
| case_005 | Audit fee | ssmt-mpers:AuditorsRemuneration | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_005 | Audit fee | ssmt-mpers:AuditorsRemuneration | exact_qname_value_period_match | statement_template_candidate_requires_review |
| case_005 | HOE | None | not_evaluable | no matching hardened rule |
| case_005 | HOE | None | not_evaluable | no matching hardened rule |
| case_005 | Ronic | None | not_evaluable | no matching hardened rule |
| case_005 | Ronic | None | not_evaluable | no matching hardened rule |
| case_005 | Commissioner for oaths | None | not_evaluable | no matching hardened rule |
| case_005 | Commissioner for oaths | None | not_evaluable | no matching hardened rule |
| case_005 | Directors' salary | ssmt-mpers:DirectorsRemuneration | qname_exists_but_value_mismatch | statement_template_candidate_requires_review |
| case_005 | Directors' salary | ssmt-mpers:DirectorsRemuneration | qname_exists_but_value_mismatch | statement_template_candidate_requires_review |
| case_005 | Directors' PCB | None | not_evaluable | no matching hardened rule |
| case_005 | Directors' PCB | None | not_evaluable | no matching hardened rule |
| case_005 | Electricity and water | None | not_evaluable | no matching hardened rule |
| case_005 | Electricity and water | None | not_evaluable | no matching hardened rule |
| case_005 | Interests on term loans | None | not_evaluable | no matching hardened rule |
| case_005 | Interests on term loans | None | not_evaluable | no matching hardened rule |
| case_005 | Insurance | None | not_evaluable | no matching hardened rule |
| case_005 | Insurance | None | not_evaluable | no matching hardened rule |
| case_005 | Maintenance fee (HR table) | None | not_evaluable | no matching hardened rule |
| case_005 | Maintenance fee (HR table) | None | not_evaluable | no matching hardened rule |
| case_005 | Printing and stationeries 1,242 &MUR | None | not_evaluable | no matching hardened rule |
| case_005 | Quit rent and assessment | None | not_evaluable | no matching hardened rule |
| case_005 | Quit rent and assessment | None | not_evaluable | no matching hardened rule |
| case_005 | Rental of photostat machine | None | not_evaluable | no matching hardened rule |
| case_005 | Rental of photostat machine | None | not_evaluable | no matching hardened rule |
| case_005 | Secretarial fee | None | not_evaluable | administrative_expense_component_row_order_blocked, row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_005 | Secretarial fee | None | not_evaluable | administrative_expense_component_row_order_blocked, row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_005 | Tax fee | None | not_evaluable | no matching hardened rule |
| case_005 | Tax fee | None | not_evaluable | no matching hardened rule |
| case_005 | Telephone & fax charges | None | not_evaluable | no matching hardened rule |
| case_005 | Telephone & fax charges | None | not_evaluable | no matching hardened rule |
| case_005 | Upkeep Bangsar office :unselected: | None | not_evaluable | no matching hardened rule |
| case_005 | Upkeep Bangsar office :unselected: | None | not_evaluable | no matching hardened rule |
| case_005 | Upkeep computer :unselected: | None | not_evaluable | no matching hardened rule |
| case_005 | Upkeep computer :unselected: | None | not_evaluable | no matching hardened rule |
| case_005 | Upkeep of air conditioner :unselected: | None | not_evaluable | no matching hardened rule |
| case_005 | Upkeep of air conditioner :unselected: | None | not_evaluable | no matching hardened rule |
| case_005 | DISCUSSION | None | not_evaluable | no matching hardened rule |
| case_005 | DISCUSSION | None | not_evaluable | no matching hardened rule |
| case_005 | Office equipment - current year OR | None | not_evaluable | no matching hardened rule |
| case_005 | Office equipment - current year OR | None | not_evaluable | no matching hardened rule |
| case_005 | - prior year | None | not_evaluable | no matching hardened rule |
| case_005 | Computer and software Ba | None | not_evaluable | no matching hardened rule |
| case_005 | Computer and software Ba | None | not_evaluable | no matching hardened rule |
| case_005 | Furniture and fitting | None | not_evaluable | no matching hardened rule |
| case_005 | Furniture and fitting | None | not_evaluable | no matching hardened rule |
| case_005 | TOTAL OPERATING EXPENSES FOLAViceRal | ifrs-smes:OtherExpenseByFunction | exact_qname_value_period_match | administrative_expense_component_dictionary_blocked, administrative_expense_component_row_order_blocked, dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked, row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_005 | TOTAL OPERATING EXPENSES FOLAViceRal | ifrs-smes:OtherExpenseByFunction | exact_qname_value_period_match | administrative_expense_component_dictionary_blocked, administrative_expense_component_row_order_blocked, dictionary_candidate_requires_review, non_exact_dictionary_alias_blocked, row_order_candidate_requires_review, row_order_confidence_below_hotfix_threshold |
| case_005 | LOSS FOR THE YEAR | ifrs-smes:ProfitLoss | ambiguous_xbrl_support | context_optimized_candidate_requires_review |
| case_005 | LOSS FOR THE YEAR | ifrs-smes:ProfitLoss | ambiguous_xbrl_support | context_optimized_candidate_requires_review |
