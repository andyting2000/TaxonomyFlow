# PDF-XBRL Rulebook False-Positive Analysis - Feature #18D-B

- Active false positives: 3
- All rule false positives: 23
- Raw XML included: False

| Sample | Label | Predicted qname | Error type | Fix |
| --- | --- | --- | --- | --- |
| case_003 | Total current assets | ifrs-smes:CurrentAssets | subtotal/component confusion | require section block |
| case_003 | Add : Other income | ifrs-smes:OtherIncome | generic label conflict | downgrade rule |
| case_003 | TOTAL OPERATING EXPENSES | ifrs-smes:OtherExpenseByFunction | subtotal/component confusion | require section block |
