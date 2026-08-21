# Feature #13T Manual Review Queue

## Summary

- Queue item count: 50
- Priority distribution: {'critical': 2, 'high': 11, 'low': 32, 'medium': 5}
- Database mutated: False

## Per Case Review Load

| Case | Queue Items |
| --- | ---: |
| Shield-Plus | 50 |

## Top Conflict Groups

- `conflict-0002` Shield-Plus / net loss for the year: 2 candidates, priority=critical

## Queue Preview

- `13T-0001` critical Shield-Plus p9: Net loss for the year [manual_review_required] reasons=['duplicate_conflicting_values', 'subtotal_total_uncertainty', 'current_prior_uncertainty', 'sign_uncertainty']
- `13T-0002` critical Shield-Plus p9: Net loss for the year [manual_review_required] reasons=['duplicate_conflicting_values', 'subtotal_total_uncertainty', 'current_prior_uncertainty', 'sign_uncertainty']
- `13T-0003` high Shield-Plus p3: Siah Teong Ban [manual_review_required] reasons=['heading_like_numeric_fact', 'sign_uncertainty']
- `13T-0004` high Shield-Plus p3: Lee Ah Kim [manual_review_required] reasons=['heading_like_numeric_fact', 'sign_uncertainty']
- `13T-0005` high Shield-Plus p7: Total Asset [manual_review_required] reasons=['heading_like_numeric_fact', 'subtotal_total_uncertainty']
- `13T-0006` high Shield-Plus p7: Capital Deficiency [manual_review_required] reasons=['heading_like_numeric_fact', 'subtotal_total_uncertainty', 'sign_uncertainty']
- `13T-0007` high Shield-Plus p7: Total current liabilities [manual_review_required] reasons=['heading_like_numeric_fact', 'subtotal_total_uncertainty']
- `13T-0008` high Shield-Plus p7: Capital Deficiency and Liabilities [manual_review_required] reasons=['heading_like_numeric_fact', 'subtotal_total_uncertainty']
- `13T-0009` high Shield-Plus p8: Revenue [manual_review_required] reasons=['heading_like_numeric_fact']
- `13T-0010` high Shield-Plus p10: NET (DECREASE) INCREASE IN CASH AND CASH EQUIVALENTS [manual_review_required] reasons=['heading_like_numeric_fact', 'sign_uncertainty']
- `13T-0011` high Shield-Plus p10: CASH AND CASH EQUIVALENTS AT BEGINNING OF YEAR [manual_review_required] reasons=['heading_like_numeric_fact', 'sign_uncertainty']
- `13T-0012` high Shield-Plus p14: Deposit [manual_review_required] reasons=['heading_like_numeric_fact']
- `13T-0013` high Shield-Plus p15: Accruals [manual_review_required] reasons=['heading_like_numeric_fact']
- `13T-0014` medium Shield-Plus p8: Loss before tax [suggest_mapping_only] reasons=['subtotal_total_uncertainty']
- `13T-0015` medium Shield-Plus p8: Loss after tax and representing total comprehensive loss for the year [suggest_mapping_only] reasons=['subtotal_total_uncertainty']
- `13T-0016` medium Shield-Plus p9: Other comprehensive income for the year [suggest_mapping_only] reasons=['current_prior_uncertainty', 'sign_uncertainty']
- `13T-0017` medium Shield-Plus p10: Loss before tax and working capital changes [suggest_mapping_only] reasons=['subtotal_total_uncertainty']
- `13T-0018` medium Shield-Plus p15: Notes to the Financial Statements: The outstanding amount due to director is shown in Note [manual_review_required] reasons=['text_block_boundary_uncertainty']
- `13T-0019` low Shield-Plus p1: DIRECTORS' REPORT [reference_only_or_context] reasons=[]
- `13T-0020` low Shield-Plus p1: STATEMENT BY DIRECTORS [reference_only_or_context] reasons=[]
- `13T-0021` low Shield-Plus p1: STATUTORY DECLARATION [reference_only_or_context] reasons=[]
- `13T-0022` low Shield-Plus p1: STATEMENT OF FINANCIAL POSITION [reference_only_or_context] reasons=[]
- `13T-0023` low Shield-Plus p1: STATEMENT OF COMPREHENSIVE INCOME [reference_only_or_context] reasons=[]
- `13T-0024` low Shield-Plus p1: STATEMENT OF CHANGES IN EQUITY [reference_only_or_context] reasons=[]
- `13T-0025` low Shield-Plus p1: STATEMENT OF CASH FLOWS [reference_only_or_context] reasons=[]

## Limitations

- This is not taxonomy mapping.
- This is not XBRL generation.
- This does not prove production readiness.
- Reference XML is not sent to any model.
- No DB mutation, live model call, benchmark rerun, UI/API implementation, or production cutover is performed.
