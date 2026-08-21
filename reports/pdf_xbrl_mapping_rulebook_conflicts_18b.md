# PDF-XBRL Mapping Rulebook Conflicts - Feature #18B

- Conflict records: 247

| Pattern | Target qname | Status | Reasons |
| --- | --- | --- | --- |
| bank balances | ssmt:CashAndBankBalances | excluded | ambiguous_observations_present, major_alignment_conflict, multiple_candidates_close_in_score, period_type_mismatch, statement_family_conflict, statement_family_mismatch |
| bank balances | ssmt:CashAndBankBalances | excluded | ambiguous_observations_present, multiple_candidates_close_in_score, statement_family_conflict |
| total non current assets | ifrs-smes:NoncurrentAssets | excluded | ambiguous_observations_present, generic_pdf_label_with_duplicate_value, subtotal_total_semantics_mismatch |
| total equity | ifrs-smes:Equity | excluded | ambiguous_observations_present, generic_pdf_label_with_duplicate_value, multiple_candidates_close_in_score, subtotal_total_semantics_mismatch |
| total equity and liabilities | ifrs-smes:EquityAndLiabilities | excluded | ambiguous_observations_present, generic_pdf_label_with_duplicate_value, subtotal_total_semantics_mismatch |
| accumulated losses | ifrs-smes:RetainedEarnings | excluded | ambiguous_observations_present, multiple_candidates_close_in_score, same_value_repeated_across_many_facts, target_qname_maps_from_many_label_patterns |
| addition | ifrs-smes:LandAndBuildings | excluded | ambiguous_observations_present, generic_label_requires_review, generic_pdf_label_with_duplicate_value, multiple_candidates_close_in_score, same_value_repeated_across_many_facts, statement_family_conflict, zero_only_evidence |
| disposal | ssmt-mpers:GainsOnDisposalOfSubsidiaryJointVenturesAndAssociates | excluded | ambiguous_observations_present, generic_label_requires_review, generic_pdf_label_with_duplicate_value, zero_only_evidence |
| loss for the financial year | ssmt-mpers:OtherBalancesWithRelatedParties | excluded | ambiguous_observations_present, label_statement_maps_to_multiple_qnames, multiple_candidates_close_in_score, same_value_repeated_across_many_facts, zero_only_evidence |
| revenue | ifrs-smes:Revenue | excluded | ambiguous_observations_present, generic_pdf_label_with_duplicate_value, label_statement_maps_to_multiple_qnames, multiple_candidates_close_in_score |
| tax expense | ifrs-smes:IncomeTaxExpenseContinuingOperations | excluded | ambiguous_observations_present, current_comparative_period_confusion, label_statement_maps_to_multiple_qnames, major_alignment_conflict, one_xbrl_fact_matches_multiple_pdf_rows, period_year_mismatch, sign_mismatch_absolute_value_only, statement_family_conflict, target_qname_maps_from_many_label_patterns |
| cash flows from investing activities | ifrs-smes:CashFlowsFromUsedInInvestingActivities | excluded | ambiguous_observations_present, multiple_candidates_close_in_score, target_qname_maps_from_many_label_patterns, zero_only_evidence |
| net cash from operating activities | ifrs-smes:CashFlowsFromUsedInOperatingActivities | excluded | ambiguous_observations_present, label_statement_maps_to_multiple_qnames, multiple_candidates_close_in_score, subtotal_total_semantics_mismatch, target_qname_maps_from_many_label_patterns |
| tax expense | ifrs-smes:ProfitLossBeforeTax | excluded | ambiguous_observations_present, label_statement_maps_to_multiple_qnames, multiple_candidates_close_in_score, same_value_repeated_across_many_facts, statement_family_conflict, target_qname_maps_from_many_label_patterns |
| tax expense | ifrs-smes:ProfitLossBeforeTax | excluded | ambiguous_observations_present, label_statement_maps_to_multiple_qnames, major_alignment_conflict, multiple_candidates_close_in_score, same_value_repeated_across_many_facts, statement_family_conflict, statement_family_mismatch, target_qname_maps_from_many_label_patterns |
| total assets | ifrs-smes:Assets | excluded | ambiguous_observations_present, generic_pdf_label_with_duplicate_value, subtotal_total_semantics_mismatch |
| trade and other receivables | ifrs-smes:AdjustmentsForDecreaseIncreaseInTradeAccountReceivable | excluded | label_statement_maps_to_multiple_qnames, major_alignment_conflict, statement_family_mismatch |
| accumulated losses carried forward | ifrs-smes:RetainedEarnings | excluded | ambiguous_observations_present, current_comparative_period_confusion, major_alignment_conflict, multiple_candidates_close_in_score, period_year_mismatch, same_value_repeated_across_many_facts, target_qname_maps_from_many_label_patterns |
| audit fee | ssmt-mpers:AuditorsRemuneration | excluded | ambiguous_observations_present, multiple_candidates_close_in_score, same_value_repeated_across_many_facts, statement_family_conflict, target_qname_maps_from_many_label_patterns |
| auditor s remuneration | ssmt-mpers:AuditorsRemuneration | excluded | ambiguous_observations_present, multiple_candidates_close_in_score, target_qname_maps_from_many_label_patterns |
