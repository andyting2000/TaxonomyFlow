# PDF-XBRL Mapping Rulebook Exclusions - Feature #18B

- Excluded rules: 234
- Zero-only exclusions: 66
- Generic-label exclusions: 1

| Pattern | Target qname | Reason |
| --- | --- | --- |
| 1 1 | ifrs-smes:NoncurrentAssets | ambiguous_alignment_only |
| accounting fee | ifrs-smes:CostOfSales | conflicting_qnames; zero_only_evidence; ambiguous_alignment_only |
| accounting fee | ssmt-mpers:AuditorsRemuneration | conflicting_qnames; ambiguous_alignment_only |
| accruals | ssmt-mpers:CurrentNontradeAccruals | conflicting_qnames; ambiguous_alignment_only |
| accruals | ssmt-mpers:NoncurrentNontradeAccruals | conflicting_qnames; ambiguous_alignment_only |
| accuals | ssmt-mpers:CurrentNontradeAccruals | ambiguous_alignment_only |
| accumulated losses | ifrs-smes:RetainedEarnings | ambiguous_alignment_only |
| accumulated losses brought forward | ifrs-smes:ProfitLossBeforeTax | conflicting_qnames; ambiguous_alignment_only |
| accumulated losses brought forward | ifrs-smes:RetainedEarnings | conflicting_qnames; ambiguous_alignment_only |
| accumulated losses carried forward | ifrs-smes:RetainedEarnings | ambiguous_alignment_only |
| add other income fros | ifrs-smes:OtherIncome | zero_only_evidence; ambiguous_alignment_only |
| add purchases | ifrs-smes:CostOfSales | ambiguous_alignment_only |
| addition | ifrs-smes:LandAndBuildings | zero_only_evidence; ambiguous_alignment_only |
| addition | ifrs-smes:LandAndBuildings | zero_only_evidence; generic_label_without_statement_context; ambiguous_alignment_only |
| advertisement | ifrs-smes:OtherIncome | zero_only_evidence; ambiguous_alignment_only |
| amount due from directors | ssmt-mpers:OtherCurrentReceivablesDueFromRelatedParties | ambiguous_alignment_only |
| amount due to director | ssmt-mpers:OtherCurrentPayablesDueToRelatedParties | ambiguous_alignment_only |
| amount due to directors | ifrs-smes:AmountsPayableRelatedPartyTransactions | conflicting_qnames; ambiguous_alignment_only |
| amount due to directors | ifrs-smes:NoncurrentPayablesToTradeSuppliers | conflicting_qnames; ambiguous_alignment_only |
| amount due to directors | ssmt-mpers:OtherCurrentPayablesDueToRelatedParties | conflicting_qnames; ambiguous_alignment_only |
| amount due to directors | ssmt-mpers:OtherNoncurrentPayablesDueToRelatedCompanies | conflicting_qnames; ambiguous_alignment_only |
| and crediting rental received | ssmt-mpers:OtherRentalIncomeOnLandAndBuildings | low_confidence_only |
| as at 31 12 23 1 1 | ifrs-smes:LandAndBuildings | zero_only_evidence; ambiguous_alignment_only |
| as at 31 12 24 1 1 purpose | ifrs-smes:InvestmentProperty | zero_only_evidence; ambiguous_alignment_only |
| at beginning and end of the financial year period | ssmt-mpers:AmountOfSharesIssuedAndFullyPaidOutstanding | ambiguous_alignment_only |
| at beginning and end of the year | ssmt-mpers:AmountOfSharesIssuedAndFullyPaidOutstanding | ambiguous_alignment_only |
| at beginning and end of the year | ssmt-mpers:AmountOfSharesIssuedAndFullyPaidOutstanding | conflicting_qnames; ambiguous_alignment_only |
| at beginning and end of the year | ssmt-mpers:CapitalFromOrdinaryShares | conflicting_qnames; ambiguous_alignment_only |
| audit fee | ssmt-mpers:AuditorsRemuneration | ambiguous_alignment_only |
| audit fee | ssmt-mpers:AuditorsRemuneration | ambiguous_alignment_only |
