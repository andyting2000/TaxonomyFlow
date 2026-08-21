# Azure DI Manual Mapping Review Queue - Feature #14D

## Summary

- Review queue items: 53
- Workflow statuses: {'ready_for_review_approval': 17, 'needs_confirmation': 17, 'blocked_from_xbrl': 4, 'needs_human_concept_choice': 15}
- Priorities: {'medium': 32, 'critical': 16, 'high': 5}
- Database mutated: False
- Final mapping approved: False

## Queue Preview

- `14D-REVIEW-0001` medium ready_for_review_approval - Notes to the Financial Statements: The Directors hereby submit their report and the audited financial
- `14D-REVIEW-0002` medium ready_for_review_approval - Notes to the Financial Statements: The Directors in office during the financial year and during
- `14D-REVIEW-0003` medium needs_confirmation - Notes to the Financial Statements: The Company is principally engaged in the business as insurance
- `14D-REVIEW-0004` medium ready_for_review_approval - Notes to the Financial Statements: All material transfers to or from reserves and provisions during
- `14D-REVIEW-0005` medium needs_confirmation - Notes to the Financial Statements: There were no changes in the contributed share capital of
- `14D-REVIEW-0006` critical blocked_from_xbrl - - Owners of the Company
- `14D-REVIEW-0007` medium ready_for_review_approval - Notes to the Financial Statements: Since the end of the previous financial year, no Director
- `14D-REVIEW-0008` medium ready_for_review_approval - Notes to the Financial Statements: Neither during nor at the end of the financial year
- `14D-REVIEW-0009` medium ready_for_review_approval - Notes to the Financial Statements: According to the Register of Directors' Shareholdings required to be
- `14D-REVIEW-0010` medium ready_for_review_approval - Notes to the Financial Statements: No dividend was paid since the end of the previous
- `14D-REVIEW-0011` medium needs_confirmation - Notes to the Financial Statements: There was no indemnity given to or insurance effected for
- `14D-REVIEW-0012` medium needs_confirmation - Notes to the Financial Statements: (i) to ascertain that proper action had been taken in
- `14D-REVIEW-0013` medium needs_confirmation - Notes to the Financial Statements: (ii) to ensure that any current assets, which were unlikely
- `14D-REVIEW-0014` medium needs_confirmation - Notes to the Financial Statements: (ii) which would render the values attributed to current assets
- `14D-REVIEW-0015` medium needs_confirmation - Notes to the Financial Statements: (iii) which have arisen which would render adherence to the
- `14D-REVIEW-0016` medium needs_confirmation - Notes to the Financial Statements: (ii) any contingent liability of the Company which has arisen
- `14D-REVIEW-0017` medium needs_confirmation - Notes to the Financial Statements: (d) No contingent or other liability has become enforceable or
- `14D-REVIEW-0018` medium ready_for_review_approval - Notes to the Financial Statements: (e) At the date of this report, the Directors are
- `14D-REVIEW-0019` medium needs_confirmation - Notes to the Financial Statements: (i) the results of the operations of the Company during
- `14D-REVIEW-0020` medium needs_confirmation - Notes to the Financial Statements: (ii) there has not arisen in the interval between the
- `14D-REVIEW-0021` medium ready_for_review_approval - Notes to the Financial Statements: This report was approved by the Board of Directors on
- `14D-REVIEW-0022` high needs_human_concept_choice - Notes to the Financial Statements: STATEMENT BY DIRECTORS PURSUANT TO SECTION 251(2) OF THE COMPANIES
- `14D-REVIEW-0023` critical blocked_from_xbrl - Statutory Declaration: No. A-1, Jalan S.321/37 Damansara Utama (,, Ti ... >
- `14D-REVIEW-0024` critical needs_human_concept_choice - Other receivable
- `14D-REVIEW-0025` medium ready_for_review_approval - Contributed share capital

## Limitations

- Review queue is report-only and does not approve mappings.
- No DB/API/UI implementation is included.
- No XBRL generation or Arelle validation can use this queue directly.
