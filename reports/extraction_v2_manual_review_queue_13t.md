# Feature #13T Manual Review Queue

## Summary

- Queue item count: 709
- Priority distribution: {'critical': 92, 'high': 232, 'low': 311, 'medium': 74}
- Database mutated: False

## Per Case Review Load

| Case | Queue Items |
| --- | ---: |
| 003-fine-batik | 129 |
| 001-bizaid-synthetic | 122 |
| 004-info-house | 106 |
| 006-Rahsia-Herbal | 105 |
| 005-jconnector | 101 |
| 002-bezlife-marketing | 81 |
| 007-Shield-Plus | 65 |

## Top Conflict Groups

- `conflict-0039` 002-bezlife-marketing / epf contribution: 2 candidates, priority=critical
- `conflict-0040` 002-bezlife-marketing / director s fee: 2 candidates, priority=critical
- `conflict-0041` 002-bezlife-marketing / rental of office: 2 candidates, priority=critical
- `conflict-0042` 003-fine-batik / accumulated losses carried forward: 2 candidates, priority=critical
- `conflict-0043` 003-fine-batik / bank balances: 2 candidates, priority=critical
- `conflict-0044` 003-fine-batik / term loan: 2 candidates, priority=critical
- `conflict-0045` 003-fine-batik / loss before taxation: 3 candidates, priority=critical
- `conflict-0046` 003-fine-batik / loss for the financial year: 4 candidates, priority=critical
- `conflict-0047` 003-fine-batik / as at 31st december 2022: 3 candidates, priority=critical
- `conflict-0048` 003-fine-batik / as at 31st december 2023: 3 candidates, priority=critical

## Queue Preview

- `13T-0001` critical 002-bezlife-marketing p24: EPF Contribution [manual_review_required] reasons=['duplicate_conflicting_values']
- `13T-0002` critical 002-bezlife-marketing p24: Director's fee [manual_review_required] reasons=['duplicate_conflicting_values']
- `13T-0003` critical 002-bezlife-marketing p24: Rental of office [manual_review_required] reasons=['duplicate_conflicting_values']
- `13T-0004` critical 002-bezlife-marketing p26: EPF Contribution [manual_review_required] reasons=['duplicate_conflicting_values', 'sign_uncertainty']
- `13T-0005` critical 002-bezlife-marketing p26: Director's fee [manual_review_required] reasons=['duplicate_conflicting_values', 'sign_uncertainty']
- `13T-0006` critical 002-bezlife-marketing p26: Rental of office [manual_review_required] reasons=['duplicate_conflicting_values', 'sign_uncertainty']
- `13T-0007` critical 003-fine-batik p3: Accumulated losses carried forward [manual_review_required] reasons=['duplicate_conflicting_values', 'sign_uncertainty']
- `13T-0008` critical 003-fine-batik p3: Accumulated losses carried forward [manual_review_required] reasons=['duplicate_conflicting_values', 'sign_uncertainty']
- `13T-0009` critical 003-fine-batik p13: Bank balances [manual_review_required] reasons=['duplicate_conflicting_values', 'ambiguous_statement_section']
- `13T-0010` critical 003-fine-batik p13: Term loan [manual_review_required] reasons=['duplicate_conflicting_values']
- `13T-0011` critical 003-fine-batik p13: Term loan [manual_review_required] reasons=['duplicate_conflicting_values']
- `13T-0012` critical 003-fine-batik p14: Loss before taxation [manual_review_required] reasons=['duplicate_conflicting_values', 'duplicate_same_label_value', 'sign_uncertainty']
- `13T-0013` critical 003-fine-batik p14: Loss for the financial year [manual_review_required] reasons=['duplicate_conflicting_values', 'sign_uncertainty']
- `13T-0014` critical 003-fine-batik p15: As at 31st December 2022 [manual_review_required] reasons=['duplicate_conflicting_values']
- `13T-0015` critical 003-fine-batik p15: As at 31st December 2022 [manual_review_required] reasons=['duplicate_conflicting_values', 'sign_uncertainty']
- `13T-0016` critical 003-fine-batik p15: As at 31st December 2022 [manual_review_required] reasons=['duplicate_conflicting_values', 'sign_uncertainty']
- `13T-0017` critical 003-fine-batik p15: Loss for the financial year [manual_review_required] reasons=['duplicate_conflicting_values', 'sign_uncertainty']
- `13T-0018` critical 003-fine-batik p15: As at 31st December 2023 [manual_review_required] reasons=['duplicate_conflicting_values']
- `13T-0019` critical 003-fine-batik p15: As at 31st December 2023 [manual_review_required] reasons=['duplicate_conflicting_values', 'sign_uncertainty']
- `13T-0020` critical 003-fine-batik p15: As at 31st December 2023 [manual_review_required] reasons=['duplicate_conflicting_values', 'sign_uncertainty']
- `13T-0021` critical 003-fine-batik p15: Loss for the financial year [manual_review_required] reasons=['duplicate_conflicting_values', 'sign_uncertainty']
- `13T-0022` critical 003-fine-batik p15: As at 31st December 2024 [manual_review_required] reasons=['duplicate_conflicting_values']
- `13T-0023` critical 003-fine-batik p15: As at 31st December 2024 [manual_review_required] reasons=['duplicate_conflicting_values', 'sign_uncertainty']
- `13T-0024` critical 003-fine-batik p15: As at 31st December 2024 [manual_review_required] reasons=['duplicate_conflicting_values', 'sign_uncertainty']
- `13T-0025` critical 003-fine-batik p16: Loss before taxation [manual_review_required] reasons=['duplicate_conflicting_values', 'sign_uncertainty']

## Limitations

- This is not taxonomy mapping.
- This is not XBRL generation.
- This does not prove production readiness.
- Reference XML is not sent to any model.
- No DB mutation, live model call, benchmark rerun, UI/API implementation, or production cutover is performed.
