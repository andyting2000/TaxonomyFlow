# Azure DI Concept Metadata Enrichment v2 - Feature #14D

## Summary

- Concepts: 946
- Aliases: 4655
- Curated aliases attached in v2: 1030
- Unresolved alias groups in v2: 0
- Numeric concepts: 656
- Text-block concepts: 148

## #14C Blocker Diagnosis

- Non-approved #14C decisions: 45
- Decision types: {'defer_mapping': 6, 'request_alias_enrichment': 24, 'blocked_from_xbrl': 3, 'require_manual_taxonomy_mapping': 12}
- Row types: {'text_block': 27, 'numeric_fact': 1, 'comparative_numeric_fact': 14, 'subtotal_or_total': 3}

## Curated Alias Groups

- accounting_policies_text_v2: 74
- administrative_expenses_v2: 1
- amortisation_spelling_v2: 19
- bank_overdraft_unsecured_v2: 4
- cash_and_bank_balances_v2: 37
- depreciation_abbreviations_v2: 15
- director_account_v2: 35
- directors_report_text_v2: 6
- notes_text_v2: 9
- payables_plural_v2: 232
- ppe_abbreviations_v2: 29
- profit_loss_v2: 312
- receivables_plural_v2: 240
- share_capital_v2: 2
- statement_by_directors_text_v2: 5
- tax_expense_v2: 10

## Unresolved Alias Groups

- None

## Limitations

- Enrichment v2 is deterministic and attaches aliases only to existing local/reference-inventory qnames.
- No fake concept qnames are created.
- Reference report, when provided, is used only as offline concept inventory and not as a direct answer key.
- No Azure DI, Hugging Face, OpenAI, embeddings, semantic matcher, DB, XBRL, or Arelle path is used.
