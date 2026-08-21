# Rulebook Mapper Dictionary Errors - Feature #18E-B-2

- False positives: 162
- High-risk ambiguity cases: 117

| Sample | Label | QName | Status | Method |
| --- | --- | --- | --- | --- |
| case_001 | Total shareholders' equity | ifrs-smes:Equity | qname_exists_but_value_mismatch | pdf_xbrl_rulebook |
| case_001 | Total shareholders' equity | ifrs-smes:Equity | ambiguous_xbrl_support | pdf_xbrl_rulebook |
| case_001 | Other payables and accruals | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_001 | Other payables and accruals | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_001 | Provision for taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | statement_concept_dictionary |
| case_001 | Total current liabilities | ifrs-smes:CurrentLiabilities | qname_exists_but_value_mismatch | pdf_xbrl_rulebook |
| case_001 | Staff costs | ifrs-smes:WagesAndSalaries | value_exists_but_different_qname | statement_template_pattern |
| case_001 | Other operating costs | ifrs-smes:AdministrativeExpense | predicted_qname_not_found_in_xbrl | dictionary_row_order_agreement |
| case_001 | Other operating costs | ifrs-smes:AdministrativeExpense | value_exists_but_different_qname | dictionary_row_order_agreement |
| case_001 | Profit / (Loss) from operating activities | ssmt-mpers:ProfitLossFromOperatingActivities | qname_exists_but_value_mismatch | row_order_alignment |
| case_001 | Less : Taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | pdf_xbrl_rulebook |
| case_001 | Total comprehensive profit / (loss) for the year / period | ifrs-smes:ProfitLoss | qname_exists_but_value_mismatch | pdf_xbrl_rulebook |
| case_001 | Total comprehensive profit / (loss) for the year / period | ifrs-smes:ProfitLoss | ambiguous_xbrl_support | pdf_xbrl_rulebook |
| case_001 | Comprehensive profit for the year | ifrs-smes:ComprehensiveIncome | qname_exists_but_value_mismatch | dictionary_row_order_conflict |
| case_001 | Comprehensive profit for the year | ifrs-smes:ComprehensiveIncome | qname_exists_but_value_mismatch | dictionary_row_order_conflict |
| case_001 | Cash flows from operating activities Profit / (Loss) before taxation | ifrs-smes:CashFlowsFromUsedInOperatingActivities | value_exists_but_different_qname | dictionary_row_order_agreement |
| case_001 | Cash flows from operating activities Profit / (Loss) before taxation | ifrs-smes:CashFlowsFromUsedInOperatingActivities | qname_exists_but_value_mismatch | dictionary_row_order_agreement |
| case_001 | Profit / (Loss) before taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | statement_concept_dictionary |
| case_001 | Profit / (Loss) before taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | statement_concept_dictionary |
| case_001 | Taxation at tax rates of - 15% | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | statement_concept_dictionary |
| case_001 | Taxation at tax rates of - 15% | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | statement_concept_dictionary |
| case_001 | Tax expenses for the year | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | statement_concept_dictionary |
| case_001 | Other payables | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_001 | Other payables | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_001 | EPF Contribution | ifrs-smes:WagesAndSalaries | qname_exists_but_value_mismatch | statement_template_pattern |
| case_001 | EIS Contribution | ifrs-smes:WagesAndSalaries | qname_exists_but_value_mismatch | note_link_template_pattern |
| case_001 | SOCSO Contribution | ifrs-smes:WagesAndSalaries | qname_exists_but_value_mismatch | statement_template_pattern |
| case_001 | Bank charges | ifrs-smes:AdministrativeExpense | predicted_qname_not_found_in_xbrl | row_order_alignment |
| case_001 | Bank charges | ifrs-smes:AdministrativeExpense | predicted_qname_not_found_in_xbrl | row_order_alignment |
| case_001 | Director's fee | ssmt-mpers:DirectorsFees | predicted_qname_not_found_in_xbrl | statement_template_pattern |
| case_001 | Director's fee | ssmt-mpers:DirectorsFees | predicted_qname_not_found_in_xbrl | statement_template_pattern |
| case_001 | Secretarial fee | ifrs-smes:AdministrativeExpense | predicted_qname_not_found_in_xbrl | row_order_alignment |
| case_001 | Secretarial fee | ifrs-smes:AdministrativeExpense | predicted_qname_not_found_in_xbrl | row_order_alignment |
| case_001 | Taxation fee | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | pdf_xbrl_rulebook |
| case_001 | Profit after taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | statement_concept_dictionary |
| case_002 | Bank charges | ifrs-smes:AdministrativeExpense | predicted_qname_not_found_in_xbrl | row_order_alignment |
| case_002 | Bank charges | ifrs-smes:AdministrativeExpense | predicted_qname_not_found_in_xbrl | row_order_alignment |
| case_002 | Taxation fee zaplatilade fel | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | pdf_xbrl_rulebook |
| case_002 | Taxation fee zaplatilade fel | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | pdf_xbrl_rulebook |
| case_002 | Taxation processing fee | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_002 | Term loan interests | ifrs-smes:FinanceCosts | qname_exists_but_value_mismatch | pdf_xbrl_rulebook |
| case_002 | Term loan interests | ifrs-smes:FinanceCosts | qname_exists_but_value_mismatch | pdf_xbrl_rulebook |
| case_002 | Trade receivables | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_002 | Trade receivables | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_002 | Other receivables and deposits | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_002 | Total equity | ifrs-smes:Equity | ambiguous_xbrl_support | pdf_xbrl_rulebook |
| case_002 | Total equity | ifrs-smes:Equity | ambiguous_xbrl_support | pdf_xbrl_rulebook |
| case_002 | Term loan on | ifrs-smes:Borrowings | value_exists_but_different_qname | statement_concept_dictionary |
| case_002 | Term loan on | ifrs-smes:Borrowings | value_exists_but_different_qname | statement_concept_dictionary |
| case_002 | Less : Cost of sales POSE (31,632) | ifrs-smes:CostOfSales | qname_exists_but_value_mismatch | statement_template_pattern |
| case_002 | Other operating expenses | ifrs-smes:AdministrativeExpense | predicted_qname_not_found_in_xbrl | dictionary_row_order_agreement |
| case_002 | Other operating expenses | ifrs-smes:AdministrativeExpense | predicted_qname_not_found_in_xbrl | dictionary_row_order_agreement |
| case_002 | Loss from operating activities | ssmt-mpers:ProfitLossFromOperatingActivities | qname_exists_but_value_mismatch | row_order_alignment |
| case_002 | Loss from operating activities | ssmt-mpers:ProfitLossFromOperatingActivities | qname_exists_but_value_mismatch | row_order_alignment |
| case_002 | Less : Taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | pdf_xbrl_rulebook |
| case_002 | Loss for the financial year DRAFT FOR DISCUSSION | ifrs-smes:ProfitLoss | ambiguous_xbrl_support | pdf_xbrl_rulebook |
| case_002 | Loss for the financial year DRAFT FOR DISCUSSION | ifrs-smes:ProfitLoss | ambiguous_xbrl_support | pdf_xbrl_rulebook |
| case_002 | Net cash from operating activities | ifrs-smes:CashFlowsFromUsedInOperatingActivities | value_exists_but_different_qname | statement_template_pattern |
| case_002 | Net cash to investing activities | ifrs-smes:CashFlowsFromUsedInInvestingActivities | value_exists_but_different_qname | statement_template_pattern |
| case_002 | Net cash to investing activities | ifrs-smes:CashFlowsFromUsedInInvestingActivities | value_exists_but_different_qname | statement_template_pattern |
| case_002 | Other receivables | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_002 | Other payables | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_002 | Other payables | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_002 | Loss before taxation :selected: (77,641) | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | statement_concept_dictionary |
| case_002 | Taxation at Malaysian rate of 15% | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | statement_concept_dictionary |
| case_002 | Taxation at Malaysian rate of 15% | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | statement_concept_dictionary |
| case_002 | Less : OPERATING EXPENSES (SCHEDULE II) | ifrs-smes:AdministrativeExpense | predicted_qname_not_found_in_xbrl | dictionary_row_order_agreement |
| case_002 | Less : OPERATING EXPENSES (SCHEDULE II) | ifrs-smes:AdministrativeExpense | predicted_qname_not_found_in_xbrl | dictionary_row_order_agreement |
| case_002 | LOSS FROM OPERATING ACTIVITIES DISATTIES | ssmt-mpers:ProfitLossFromOperatingActivities | qname_exists_but_value_mismatch | row_order_alignment |
| case_002 | LOSS FROM OPERATING ACTIVITIES DISATTIES | ssmt-mpers:ProfitLossFromOperatingActivities | qname_exists_but_value_mismatch | row_order_alignment |
| case_002 | Other income | ifrs-smes:OtherIncome | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_002 | Other income | ifrs-smes:OtherIncome | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_002 | LOSS FOR THE FINANCIAL YEAR DRAFT REFINAR | ifrs-smes:ProfitLoss | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_002 | LOSS FOR THE FINANCIAL YEAR DRAFT REFINAR | ifrs-smes:ProfitLoss | ambiguous_xbrl_support | pdf_xbrl_rulebook |
| case_002 | Loss after taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | statement_concept_dictionary |
| case_003 | Trade receivables | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_003 | Trade receivables | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_003 | Other receivables, deposits and prepayments | ifrs-smes:TradeAndOtherCurrentReceivables | qname_exists_but_value_mismatch | pdf_xbrl_rulebook |
| case_003 | Other receivables, deposits and prepayments | ifrs-smes:TradeAndOtherCurrentReceivables | qname_exists_but_value_mismatch | pdf_xbrl_rulebook |
| case_003 | Total current assets | ifrs-smes:CurrentAssets | qname_exists_but_value_mismatch | pdf_xbrl_rulebook |
| case_003 | TOTAL ASSETS | ifrs-smes:Assets | qname_exists_but_value_mismatch | pdf_xbrl_rulebook |
| case_003 | Retained profits :unselected: | ifrs-smes:RetainedEarnings | qname_exists_but_value_mismatch | statement_template_pattern |
| case_003 | Total equity | ifrs-smes:Equity | qname_exists_but_value_mismatch | pdf_xbrl_rulebook |
| case_003 | Total equity | ifrs-smes:Equity | ambiguous_xbrl_support | pdf_xbrl_rulebook |
| case_003 | Total non current liabilities | ifrs-smes:NoncurrentLiabilities | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_003 | Total non current liabilities | ifrs-smes:NoncurrentLiabilities | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_003 | Other payables and accruals | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_003 | Other payables and accruals | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_003 | Total current liabilities | ifrs-smes:CurrentLiabilities | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_003 | Total current liabilities | ifrs-smes:CurrentLiabilities | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_003 | Total liabilities | ifrs-smes:Liabilities | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_003 | Total liabilities | ifrs-smes:Liabilities | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_003 | TOTAL EQUITY AND LIABILITIES | ifrs-smes:EquityAndLiabilities | qname_exists_but_value_mismatch | pdf_xbrl_rulebook |
| case_003 | Turnover | ifrs-smes:Revenue | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_003 | Other operating expenses | ifrs-smes:AdministrativeExpense | predicted_qname_not_found_in_xbrl | dictionary_row_order_agreement |
| case_003 | Other operating expenses | ifrs-smes:AdministrativeExpense | predicted_qname_not_found_in_xbrl | dictionary_row_order_agreement |
| case_003 | Loss from operating activities | ssmt-mpers:ProfitLossFromOperatingActivities | qname_exists_but_value_mismatch | row_order_alignment |
| case_003 | Loss from operating activities | ssmt-mpers:ProfitLossFromOperatingActivities | qname_exists_but_value_mismatch | row_order_alignment |
| case_003 | Add : Other income | ifrs-smes:OtherIncome | qname_exists_but_value_mismatch | pdf_xbrl_rulebook |
| case_003 | (Less) / Add : Taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_003 | (Less) / Add : Taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | pdf_xbrl_rulebook |
| case_003 | Loss for the financial year DRAFT FOR | ifrs-smes:ProfitLoss | qname_exists_but_value_mismatch | pdf_xbrl_rulebook |
| case_003 | Loss for the financial year DRAFT FOR | ifrs-smes:ProfitLoss | ambiguous_xbrl_support | pdf_xbrl_rulebook |
| case_003 | Loss for the financial year | ifrs-smes:ProfitLoss | qname_exists_but_value_mismatch | dictionary_row_order_agreement |
| case_003 | Other receivables | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_003 | Other receivables | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_003 | Other payables | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_003 | Other payables | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_003 | Taxation at statutory tax rate of 15% | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | statement_concept_dictionary |
| case_003 | Taxation at statutory tax rate of 15% | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | statement_concept_dictionary |
| case_003 | Over provision for taxation prior year | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | statement_concept_dictionary |
| case_003 | Tax expenses for the year | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | statement_concept_dictionary |
| case_003 | Bank charges | ifrs-smes:AdministrativeExpense | predicted_qname_not_found_in_xbrl | row_order_alignment |
| case_003 | Bank charges | ifrs-smes:AdministrativeExpense | predicted_qname_not_found_in_xbrl | row_order_alignment |
| case_003 | Taxation fee | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | pdf_xbrl_rulebook |
| case_003 | Taxation fee | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | pdf_xbrl_rulebook |
| case_003 | TOTAL OPERATING EXPENSES | ifrs-smes:OtherExpenseByFunction | qname_exists_but_value_mismatch | pdf_xbrl_rulebook |
| case_003 | LOSS FOR THE YEAR | ifrs-smes:ProfitLoss | qname_exists_but_value_mismatch | pdf_xbrl_rulebook |
| case_003 | LOSS FOR THE YEAR | ifrs-smes:ProfitLoss | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_003 | Loss after taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | statement_concept_dictionary |
| case_004 | Total equity | ifrs-smes:Equity | ambiguous_xbrl_support | pdf_xbrl_rulebook |
| case_004 | Total equity | ifrs-smes:Equity | ambiguous_xbrl_support | pdf_xbrl_rulebook |
| case_004 | Amount due to directors | ssmt-mpers:OtherCurrentPayablesDueToRelatedParties | value_exists_but_different_qname | note_link_template_pattern |
| case_004 | Amount due to directors | ssmt-mpers:OtherCurrentPayablesDueToRelatedParties | value_exists_but_different_qname | note_link_template_pattern |
| case_004 | Less : Taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_004 | Less : Taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_004 | Loss for the financial year | ifrs-smes:ProfitLoss | ambiguous_xbrl_support | pdf_xbrl_rulebook |
| case_004 | Loss for the financial year | ifrs-smes:ProfitLoss | ambiguous_xbrl_support | pdf_xbrl_rulebook |
| case_004 | Cash flows from operating activities Loss before taxation | ifrs-smes:CashFlowsFromUsedInOperatingActivities | value_exists_but_different_qname | dictionary_row_order_agreement |
| case_004 | Decrease in property, plant and equipment | ifrs-smes:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities | value_exists_but_different_qname | dictionary_row_order_agreement |
| case_004 | Decrease in property, plant and equipment | ifrs-smes:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities | value_exists_but_different_qname | dictionary_row_order_agreement |
| case_004 | Loss before taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | statement_concept_dictionary |
| case_004 | Loss before taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | statement_concept_dictionary |
| case_004 | Taxation at statutory tax rate of 15% | ifrs-smes:IncomeTaxExpenseContinuingOperations | predicted_qname_not_found_in_xbrl | statement_concept_dictionary |
| case_004 | Taxation at statutory tax rate of 15% | ifrs-smes:IncomeTaxExpenseContinuingOperations | predicted_qname_not_found_in_xbrl | statement_concept_dictionary |
| case_004 | Tax expenses for the year | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | statement_concept_dictionary |
| case_004 | Tax expenses for the year | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | statement_concept_dictionary |
| case_004 | Taxation fee | ifrs-smes:IncomeTaxExpenseContinuingOperations | predicted_qname_not_found_in_xbrl | statement_concept_dictionary |
| case_004 | Taxation fee | ifrs-smes:IncomeTaxExpenseContinuingOperations | predicted_qname_not_found_in_xbrl | statement_concept_dictionary |
| case_004 | Loss after taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | statement_concept_dictionary |
| case_005 | Secretarial fee | ifrs-smes:AdministrativeExpense | predicted_qname_not_found_in_xbrl | row_order_alignment |
| case_005 | Secretarial fee | ifrs-smes:AdministrativeExpense | predicted_qname_not_found_in_xbrl | row_order_alignment |
| case_005 | LOSS FOR THE YEAR | ifrs-smes:ProfitLoss | ambiguous_xbrl_support | pdf_xbrl_rulebook |
| case_005 | LOSS FOR THE YEAR | ifrs-smes:ProfitLoss | ambiguous_xbrl_support | pdf_xbrl_rulebook |
| case_005 | Trade receivables JE | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_005 | Other receivables and deposits | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_005 | Total equity | ifrs-smes:Equity | ambiguous_xbrl_support | pdf_xbrl_rulebook |
| case_005 | Total equity | ifrs-smes:Equity | ambiguous_xbrl_support | pdf_xbrl_rulebook |
| case_005 | Term loan | ifrs-smes:Borrowings | value_exists_but_different_qname | statement_concept_dictionary |
| case_005 | Term loan | ifrs-smes:Borrowings | value_exists_but_different_qname | statement_concept_dictionary |
| case_005 | Amount due to directors | ssmt-mpers:OtherCurrentPayablesDueToRelatedParties | value_exists_but_different_qname | note_link_template_pattern |
| case_005 | Amount due to directors | ssmt-mpers:OtherCurrentPayablesDueToRelatedParties | value_exists_but_different_qname | note_link_template_pattern |
| case_005 | Total non current liabilities toachat | ifrs-smes:NoncurrentLiabilities | qname_exists_but_value_mismatch | pdf_xbrl_rulebook |
| case_005 | Total non current liabilities toachat | ifrs-smes:NoncurrentLiabilities | qname_exists_but_value_mismatch | pdf_xbrl_rulebook |
| case_005 | Other payables and accruals clean | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_005 | Other payables and accruals clean | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_005 | Term loan | ifrs-smes:Borrowings | value_exists_but_different_qname | statement_concept_dictionary |
| case_005 | Term loan | ifrs-smes:Borrowings | value_exists_but_different_qname | statement_concept_dictionary |
| case_005 | Less : Cost of sales | ifrs-smes:CostOfSales | qname_exists_but_value_mismatch | statement_template_pattern |
| case_005 | Less : Cost of sales | ifrs-smes:CostOfSales | qname_exists_but_value_mismatch | statement_template_pattern |
| case_005 | Other operating expenses | ifrs-smes:AdministrativeExpense | predicted_qname_not_found_in_xbrl | dictionary_row_order_agreement |
| case_005 | Other operating expenses | ifrs-smes:AdministrativeExpense | predicted_qname_not_found_in_xbrl | dictionary_row_order_agreement |
| case_005 | Loss from operating activities | ssmt-mpers:ProfitLossFromOperatingActivities | qname_exists_but_value_mismatch | row_order_alignment |
| case_005 | Loss from operating activities | ssmt-mpers:ProfitLossFromOperatingActivities | qname_exists_but_value_mismatch | row_order_alignment |
| case_005 | Less : Taxation DRAFT FÅCate | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_005 | Less : Taxation DRAFT FÅCate | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_005 | Cash flows from operating activities Loss before taxation | ifrs-smes:CashFlowsFromUsedInOperatingActivities | value_exists_but_different_qname | dictionary_row_order_agreement |
| case_005 | Other receivables | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_005 | Other receivables | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_005 | Other payables | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_005 | Other payables | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | pdf_xbrl_rulebook |
| case_005 | Loss before taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | predicted_qname_not_found_in_xbrl | statement_concept_dictionary |
| case_005 | Loss before taxation | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | statement_concept_dictionary |
| case_005 | Taxation at statutory tax rate of 15% | ifrs-smes:IncomeTaxExpenseContinuingOperations | predicted_qname_not_found_in_xbrl | statement_concept_dictionary |
| case_005 | Taxation at statutory tax rate of 15% | ifrs-smes:IncomeTaxExpenseContinuingOperations | predicted_qname_not_found_in_xbrl | statement_concept_dictionary |
| case_005 | Tax expenses for the financial year | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | statement_concept_dictionary |
| case_005 | Tax expenses for the financial year | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | statement_concept_dictionary |
| case_005 | Directors' salary | ssmt-mpers:DirectorsRemuneration | qname_exists_but_value_mismatch | statement_template_pattern |
| case_005 | Directors' salary | ssmt-mpers:DirectorsRemuneration | qname_exists_but_value_mismatch | statement_template_pattern |
