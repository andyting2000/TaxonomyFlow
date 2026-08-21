# Azure DI Manual Mapping Review Queue - Feature #14B

## Summary

- Review queue items: 53
- Workflow statuses: {'ready_for_review_approval': 8, 'needs_confirmation': 6, 'needs_alias_or_metadata_enrichment': 24, 'blocked_from_xbrl': 3, 'needs_human_concept_choice': 12}
- Priorities: {'medium': 33, 'critical': 14, 'high': 6}
- Database mutated: False
- Final mapping approved: False

## Queue Preview

- `14B-REVIEW-0001` medium ready_for_review_approval - Notes to the Financial Statements: The Directors hereby submit their report and the audited financial
- `14B-REVIEW-0002` medium ready_for_review_approval - Notes to the Financial Statements: The Directors in office during the financial year and during
- `14B-REVIEW-0003` medium needs_confirmation - Notes to the Financial Statements: The Company is principally engaged in the business as insurance
- `14B-REVIEW-0004` medium needs_alias_or_metadata_enrichment - Notes to the Financial Statements: All material transfers to or from reserves and provisions during
- `14B-REVIEW-0005` medium needs_alias_or_metadata_enrichment - Notes to the Financial Statements: There were no changes in the contributed share capital of
- `14B-REVIEW-0006` critical blocked_from_xbrl - - Owners of the Company
- `14B-REVIEW-0007` medium needs_alias_or_metadata_enrichment - Notes to the Financial Statements: Since the end of the previous financial year, no Director
- `14B-REVIEW-0008` medium needs_alias_or_metadata_enrichment - Notes to the Financial Statements: Neither during nor at the end of the financial year
- `14B-REVIEW-0009` medium ready_for_review_approval - Notes to the Financial Statements: According to the Register of Directors' Shareholdings required to be
- `14B-REVIEW-0010` medium needs_alias_or_metadata_enrichment - Notes to the Financial Statements: No dividend was paid since the end of the previous
- `14B-REVIEW-0011` medium needs_alias_or_metadata_enrichment - Notes to the Financial Statements: There was no indemnity given to or insurance effected for
- `14B-REVIEW-0012` medium needs_alias_or_metadata_enrichment - Notes to the Financial Statements: (i) to ascertain that proper action had been taken in
- `14B-REVIEW-0013` medium needs_alias_or_metadata_enrichment - Notes to the Financial Statements: (ii) to ensure that any current assets, which were unlikely
- `14B-REVIEW-0014` medium needs_alias_or_metadata_enrichment - Notes to the Financial Statements: (ii) which would render the values attributed to current assets
- `14B-REVIEW-0015` medium needs_alias_or_metadata_enrichment - Notes to the Financial Statements: (iii) which have arisen which would render adherence to the
- `14B-REVIEW-0016` medium needs_alias_or_metadata_enrichment - Notes to the Financial Statements: (ii) any contingent liability of the Company which has arisen
- `14B-REVIEW-0017` medium needs_alias_or_metadata_enrichment - Notes to the Financial Statements: (d) No contingent or other liability has become enforceable or
- `14B-REVIEW-0018` medium needs_alias_or_metadata_enrichment - Notes to the Financial Statements: (e) At the date of this report, the Directors are
- `14B-REVIEW-0019` medium needs_alias_or_metadata_enrichment - Notes to the Financial Statements: (i) the results of the operations of the Company during
- `14B-REVIEW-0020` medium needs_alias_or_metadata_enrichment - Notes to the Financial Statements: (ii) there has not arisen in the interval between the
- `14B-REVIEW-0021` medium needs_alias_or_metadata_enrichment - Notes to the Financial Statements: This report was approved by the Board of Directors on
- `14B-REVIEW-0022` medium needs_confirmation - Notes to the Financial Statements: STATEMENT BY DIRECTORS PURSUANT TO SECTION 251(2) OF THE COMPANIES
- `14B-REVIEW-0023` critical blocked_from_xbrl - Statutory Declaration: No. A-1, Jalan S.321/37 Damansara Utama (,, Ti ... >
- `14B-REVIEW-0024` critical needs_human_concept_choice - Other receivable
- `14B-REVIEW-0025` medium ready_for_review_approval - Contributed share capital

## Limitations

- Review queue is report-only and does not approve mappings.
- No DB/API/UI implementation is included.
- No XBRL generation or Arelle validation can use this queue directly.
