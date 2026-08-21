# Azure DI Refinement Comparison - Feature #14D

## Summary

- #14C XBRL eligible: 8
- #14D XBRL eligible: 17
- #14C decisions: {'approve_suggested_concept_simulated': 8, 'defer_mapping': 6, 'request_alias_enrichment': 24, 'blocked_from_xbrl': 3, 'require_manual_taxonomy_mapping': 12}
- #14D decisions: {'approve_suggested_concept_simulated': 17, 'defer_mapping': 17, 'blocked_from_xbrl': 4, 'require_manual_taxonomy_mapping': 15}
- #14D mapping statuses: {'medium_confidence_suggestion': 27, 'no_safe_suggestion': 4, 'ambiguous_multiple_suggestions': 15, 'high_confidence_suggestion': 6, 'low_confidence_suggestion': 1}
- Recommended next feature: Feature #14E - Manual mapping review UI/API planning if review workflow is now acceptable.

## Improved Labels

- `13V-MAP-0003` Notes to the Financial Statements: The Company is principally engaged in the business as insurance: low_confidence_suggestion -> medium_confidence_suggestion
- `13V-MAP-0004` Notes to the Financial Statements: All material transfers to or from reserves and provisions during: low_confidence_suggestion -> medium_confidence_suggestion
- `13V-MAP-0005` Notes to the Financial Statements: There were no changes in the contributed share capital of: low_confidence_suggestion -> medium_confidence_suggestion
- `13V-MAP-0007` Notes to the Financial Statements: Since the end of the previous financial year, no Director: low_confidence_suggestion -> medium_confidence_suggestion
- `13V-MAP-0008` Notes to the Financial Statements: Neither during nor at the end of the financial year: low_confidence_suggestion -> medium_confidence_suggestion
- `13V-MAP-0010` Notes to the Financial Statements: No dividend was paid since the end of the previous: low_confidence_suggestion -> medium_confidence_suggestion
- `13V-MAP-0011` Notes to the Financial Statements: There was no indemnity given to or insurance effected for: low_confidence_suggestion -> medium_confidence_suggestion
- `13V-MAP-0012` Notes to the Financial Statements: (i) to ascertain that proper action had been taken in: low_confidence_suggestion -> medium_confidence_suggestion
- `13V-MAP-0013` Notes to the Financial Statements: (ii) to ensure that any current assets, which were unlikely: low_confidence_suggestion -> medium_confidence_suggestion
- `13V-MAP-0014` Notes to the Financial Statements: (ii) which would render the values attributed to current assets: low_confidence_suggestion -> medium_confidence_suggestion
- `13V-MAP-0015` Notes to the Financial Statements: (iii) which have arisen which would render adherence to the: low_confidence_suggestion -> medium_confidence_suggestion
- `13V-MAP-0016` Notes to the Financial Statements: (ii) any contingent liability of the Company which has arisen: low_confidence_suggestion -> medium_confidence_suggestion
- `13V-MAP-0017` Notes to the Financial Statements: (d) No contingent or other liability has become enforceable or: low_confidence_suggestion -> medium_confidence_suggestion
- `13V-MAP-0018` Notes to the Financial Statements: (e) At the date of this report, the Directors are: low_confidence_suggestion -> medium_confidence_suggestion
- `13V-MAP-0019` Notes to the Financial Statements: (i) the results of the operations of the Company during: low_confidence_suggestion -> medium_confidence_suggestion
- `13V-MAP-0020` Notes to the Financial Statements: (ii) there has not arisen in the interval between the: low_confidence_suggestion -> medium_confidence_suggestion
- `13V-MAP-0021` Notes to the Financial Statements: This report was approved by the Board of Directors on: low_confidence_suggestion -> medium_confidence_suggestion
- `13V-MAP-0028` Amount due to director: low_confidence_suggestion -> high_confidence_suggestion
- `13V-MAP-0045` Notes to the Financial Statements: The financial statements have been prepared in compliance with the: low_confidence_suggestion -> medium_confidence_suggestion
- `13V-MAP-0049` Notes to the Financial Statements: Transaction costs of an equity transaction are accounted for as: low_confidence_suggestion -> medium_confidence_suggestion
- `13V-MAP-0050` Notes to the Financial Statements: For the purpose of subsequent measurement, the Company classifies financial: low_confidence_suggestion -> medium_confidence_suggestion
- `13V-MAP-0051` Notes to the Financial Statements: For short-term other receivable, where the effect of discounting is: low_confidence_suggestion -> medium_confidence_suggestion
- `13V-MAP-0053` 9. Bank Overdraft -Unsecured: The bank overdraft represents the surplus of unpresented cheques over: low_confidence_suggestion -> medium_confidence_suggestion

## Worsened Labels

- `13V-MAP-0022` Notes to the Financial Statements: STATEMENT BY DIRECTORS PURSUANT TO SECTION 251(2) OF THE COMPANIES: medium_confidence_suggestion -> ambiguous_multiple_suggestions
- `13V-MAP-0032` Tax expense: medium_confidence_suggestion -> ambiguous_multiple_suggestions
- `13V-MAP-0039` Increase in director's account: low_confidence_suggestion -> no_safe_suggestion

## Cautionary Notes

- All mapping outputs remain suggested_only.
- All simulated approvals remain simulated_only=true and human_approved=false.
- No production mapping approval, XBRL generation, or Arelle validation occurred.
- If eligibility does not improve, the report should be read as blocker diagnosis rather than production readiness.
