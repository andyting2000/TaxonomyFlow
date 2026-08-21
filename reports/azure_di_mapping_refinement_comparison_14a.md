# Azure DI Mapping Refinement Comparison - Feature #14A

## Summary

- #13Z status counts: {'low_confidence_suggestion': 24, 'no_safe_suggestion': 4, 'ambiguous_multiple_suggestions': 16, 'medium_confidence_suggestion': 9}
- #14A status counts: {'medium_confidence_suggestion': 7, 'low_confidence_suggestion': 26, 'no_safe_suggestion': 3, 'ambiguous_multiple_suggestions': 12, 'high_confidence_suggestion': 5}
- Changed labels: 44
- Worsened labels: 3
- Recommended next feature: Feature #14B - Manual mapping review workflow if ambiguous mappings remain dominant.

## Confidence Distribution Change

- ambiguous_multiple_suggestions: 16 -> 12 (-4)
- high_confidence_suggestion: 0 -> 5 (+5)
- low_confidence_suggestion: 24 -> 26 (+2)
- medium_confidence_suggestion: 9 -> 7 (-2)
- no_safe_suggestion: 4 -> 3 (-1)

## Diagnostic

- Baseline aliases were mostly generated from raw taxonomy labels and local names, so common annual-report labels often matched only by weak token overlap.
- Text-block candidates often carried broad section labels such as Notes to the Financial Statements, hiding Directors' Report, accounting policy, and note-specific intent.
- Several numeric labels had multiple nearby taxonomy concepts and needed curated local aliases plus statement-family hints to separate candidates.
- The baseline required a strong score gap before high confidence; close concept scores were surfaced as ambiguous by design.

## Cautionary Notes

- Higher confidence remains a suggested-only signal, not final mapping approval.
- No XBRL generation or Arelle validation was performed.
- Ambiguous and no-safe records remain review signals, not failures.
