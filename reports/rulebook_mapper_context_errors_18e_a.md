# Rulebook Mapper Context Errors - Feature #18E-A

- False positives: 68
- Not evaluable predictions: 17

| Sample | Label | Value | QName | Status | Reason |
| --- | --- | ---: | --- | --- | --- |
| case_001 | Less : Taxation | -24692 | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | predicted qname exists but no matching value/period fact was found |
| case_001 | Taxation fee | 350 | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | predicted qname exists but no matching value/period fact was found |
| case_001 | Total comprehensive profit / (loss) for the year / period | 103550 | ifrs-smes:ProfitLoss | qname_exists_but_value_mismatch | predicted qname exists but no matching value/period fact was found |
| case_001 | Total comprehensive profit / (loss) for the year / period | -3097 | ifrs-smes:ProfitLoss | ambiguous_xbrl_support | multiple matching facts for predicted qname/value/period |
| case_001 | Total current liabilities | 114071 | ifrs-smes:CurrentLiabilities | qname_exists_but_value_mismatch | predicted qname exists but no matching value/period fact was found |
| case_001 | Total shareholders' equity | 100553 | ifrs-smes:Equity | qname_exists_but_value_mismatch | predicted qname exists but no matching value/period fact was found |
| case_001 | Total shareholders' equity | -2997 | ifrs-smes:Equity | ambiguous_xbrl_support | multiple matching facts for predicted qname/value/period |
| case_001 | Other payables and accruals | 63381 | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | same value/period exists under a different qname |
| case_001 | Other payables and accruals | 1398 | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | same value/period exists under a different qname |
| case_001 | Other payables | 62681 | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | same value/period exists under a different qname |
| case_001 | Other payables | 0 | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | same value/period exists under a different qname |
| case_002 | Loss for the financial year DRAFT FOR DISCUSSION | -25287 | ifrs-smes:ProfitLoss | ambiguous_xbrl_support | multiple matching facts for predicted qname/value/period |
| case_002 | Loss for the financial year DRAFT FOR DISCUSSION | -77641 | ifrs-smes:ProfitLoss | ambiguous_xbrl_support | multiple matching facts for predicted qname/value/period |
| case_002 | LOSS FOR THE FINANCIAL YEAR DRAFT REFINAR | -23562 | ifrs-smes:ProfitLoss | value_exists_but_different_qname | same value/period exists under a different qname |
| case_002 | LOSS FOR THE FINANCIAL YEAR DRAFT REFINAR | -77641 | ifrs-smes:ProfitLoss | ambiguous_xbrl_support | multiple matching facts for predicted qname/value/period |
| case_002 | Other income | 60 | ifrs-smes:OtherIncome | value_exists_but_different_qname | same value/period exists under a different qname |
| case_002 | Other income | 10 | ifrs-smes:OtherIncome | value_exists_but_different_qname | same value/period exists under a different qname |
| case_002 | Taxation fee zaplatilade fel | 200 | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | predicted qname exists but no matching value/period fact was found |
| case_002 | Taxation fee zaplatilade fel | 250 | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | predicted qname exists but no matching value/period fact was found |
| case_002 | Taxation processing fee | 600 | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | same value/period exists under a different qname |
| case_002 | Less : Taxation | -1725 | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | predicted qname exists but no matching value/period fact was found |
| case_002 | Term loan interests | 33168 | ifrs-smes:FinanceCosts | qname_exists_but_value_mismatch | predicted qname exists but no matching value/period fact was found |
| case_002 | Term loan interests | 35186 | ifrs-smes:FinanceCosts | qname_exists_but_value_mismatch | predicted qname exists but no matching value/period fact was found |
| case_002 | Total equity | -292608 | ifrs-smes:Equity | ambiguous_xbrl_support | multiple matching facts for predicted qname/value/period |
| case_002 | Total equity | -267321 | ifrs-smes:Equity | ambiguous_xbrl_support | multiple matching facts for predicted qname/value/period |
| case_002 | Other payables | 75621 | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | same value/period exists under a different qname |
| case_002 | Other payables | 66390 | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | same value/period exists under a different qname |
| case_002 | Trade receivables | 0 | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | same value/period exists under a different qname |
| case_002 | Trade receivables | 6913 | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | same value/period exists under a different qname |
| case_002 | Other receivables and deposits | 44399 | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | same value/period exists under a different qname |
| case_002 | Other receivables | 0 | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | same value/period exists under a different qname |
| case_003 | Add : Other income | 8430 | ifrs-smes:OtherIncome | qname_exists_but_value_mismatch | predicted qname exists but no matching value/period fact was found |
| case_003 | Loss for the financial year DRAFT FOR | -2686 | ifrs-smes:ProfitLoss | qname_exists_but_value_mismatch | predicted qname exists but no matching value/period fact was found |
| case_003 | Loss for the financial year DRAFT FOR | -7086 | ifrs-smes:ProfitLoss | ambiguous_xbrl_support | multiple matching facts for predicted qname/value/period |
| case_003 | LOSS FOR THE YEAR | -2686 | ifrs-smes:ProfitLoss | qname_exists_but_value_mismatch | predicted qname exists but no matching value/period fact was found |
| case_003 | LOSS FOR THE YEAR | -8163 | ifrs-smes:ProfitLoss | value_exists_but_different_qname | same value/period exists under a different qname |
| case_003 | Turnover | 18000 | ifrs-smes:Revenue | value_exists_but_different_qname | same value/period exists under a different qname |
| case_003 | (Less) / Add : Taxation | 0 | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | same value/period exists under a different qname |
| case_003 | (Less) / Add : Taxation | 1077 | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | predicted qname exists but no matching value/period fact was found |
| case_003 | Taxation fee | 200 | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | predicted qname exists but no matching value/period fact was found |
| case_003 | Taxation fee | 250 | ifrs-smes:IncomeTaxExpenseContinuingOperations | qname_exists_but_value_mismatch | predicted qname exists but no matching value/period fact was found |
| case_003 | TOTAL ASSETS | 184023 | ifrs-smes:Assets | qname_exists_but_value_mismatch | predicted qname exists but no matching value/period fact was found |
| case_003 | Total current assets | 154021 | ifrs-smes:CurrentAssets | qname_exists_but_value_mismatch | predicted qname exists but no matching value/period fact was found |
| case_003 | Total current liabilities | 800 | ifrs-smes:CurrentLiabilities | value_exists_but_different_qname | same value/period exists under a different qname |
| case_003 | Total current liabilities | 11900 | ifrs-smes:CurrentLiabilities | value_exists_but_different_qname | same value/period exists under a different qname |
| case_003 | Total equity | 171223 | ifrs-smes:Equity | qname_exists_but_value_mismatch | predicted qname exists but no matching value/period fact was found |
| case_003 | Total equity | 173909 | ifrs-smes:Equity | ambiguous_xbrl_support | multiple matching facts for predicted qname/value/period |
| case_003 | TOTAL EQUITY AND LIABILITIES | 184023 | ifrs-smes:EquityAndLiabilities | qname_exists_but_value_mismatch | predicted qname exists but no matching value/period fact was found |
| case_003 | Total liabilities | 12800 | ifrs-smes:Liabilities | value_exists_but_different_qname | same value/period exists under a different qname |
| case_003 | Total liabilities | 11900 | ifrs-smes:Liabilities | value_exists_but_different_qname | same value/period exists under a different qname |
| case_003 | Total non current liabilities | 12000 | ifrs-smes:NoncurrentLiabilities | value_exists_but_different_qname | same value/period exists under a different qname |
| case_003 | Total non current liabilities | 12000 | ifrs-smes:NoncurrentLiabilities | value_exists_but_different_qname | same value/period exists under a different qname |
| case_003 | TOTAL OPERATING EXPENSES | 35186 | ifrs-smes:OtherExpenseByFunction | qname_exists_but_value_mismatch | predicted qname exists but no matching value/period fact was found |
| case_003 | Other payables and accruals | 800 | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | same value/period exists under a different qname |
| case_003 | Other payables and accruals | 11900 | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | same value/period exists under a different qname |
| case_003 | Other payables | 0 | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | same value/period exists under a different qname |
| case_003 | Other payables | 7100 | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | same value/period exists under a different qname |
| case_003 | Trade receivables | 32400 | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | same value/period exists under a different qname |
| case_003 | Trade receivables | 0 | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | same value/period exists under a different qname |
| case_003 | Other receivables, deposits and prepayments | 120800 | ifrs-smes:TradeAndOtherCurrentReceivables | qname_exists_but_value_mismatch | predicted qname exists but no matching value/period fact was found |
| case_003 | Other receivables, deposits and prepayments | 25400 | ifrs-smes:TradeAndOtherCurrentReceivables | qname_exists_but_value_mismatch | predicted qname exists but no matching value/period fact was found |
| case_003 | Other receivables | 119700 | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | same value/period exists under a different qname |
| case_003 | Other receivables | 24300 | ifrs-smes:TradeAndOtherCurrentReceivables | value_exists_but_different_qname | same value/period exists under a different qname |
| case_004 | Loss for the financial year | -9915 | ifrs-smes:ProfitLoss | ambiguous_xbrl_support | multiple matching facts for predicted qname/value/period |
| case_004 | Loss for the financial year | -188217 | ifrs-smes:ProfitLoss | ambiguous_xbrl_support | multiple matching facts for predicted qname/value/period |
| case_004 | Less : Taxation | 0 | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | same value/period exists under a different qname |
| case_004 | Less : Taxation | 0 | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | same value/period exists under a different qname |
| case_004 | Total equity | -303233 | ifrs-smes:Equity | ambiguous_xbrl_support | multiple matching facts for predicted qname/value/period |
| case_004 | Total equity | -293318 | ifrs-smes:Equity | ambiguous_xbrl_support | multiple matching facts for predicted qname/value/period |
| case_005 | LOSS FOR THE YEAR | -138197 | ifrs-smes:ProfitLoss | ambiguous_xbrl_support | multiple matching facts for predicted qname/value/period |
| case_005 | LOSS FOR THE YEAR | -104646 | ifrs-smes:ProfitLoss | ambiguous_xbrl_support | multiple matching facts for predicted qname/value/period |
| case_005 | Less : Taxation DRAFT FÅCate | 0 | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | same value/period exists under a different qname |
| case_005 | Less : Taxation DRAFT FÅCate | 0 | ifrs-smes:IncomeTaxExpenseContinuingOperations | value_exists_but_different_qname | same value/period exists under a different qname |
| case_005 | Total equity | -1056406 | ifrs-smes:Equity | ambiguous_xbrl_support | multiple matching facts for predicted qname/value/period |
| case_005 | Total equity | -918209 | ifrs-smes:Equity | ambiguous_xbrl_support | multiple matching facts for predicted qname/value/period |
| case_005 | Total non current liabilities toachat | 1719316 | ifrs-smes:NoncurrentLiabilities | qname_exists_but_value_mismatch | predicted qname exists but no matching value/period fact was found |
| case_005 | Total non current liabilities toachat | 1624178 | ifrs-smes:NoncurrentLiabilities | qname_exists_but_value_mismatch | predicted qname exists but no matching value/period fact was found |
| case_005 | Other payables and accruals clean | 146856 | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | same value/period exists under a different qname |
| case_005 | Other payables and accruals clean | 135966 | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | same value/period exists under a different qname |
| case_005 | Other payables | 140156 | ifrs-smes:TradeAndOtherCurrentPayables | value_exists_but_different_qname | same value/period exists under a different qname |
