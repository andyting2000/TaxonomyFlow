# Feature #13S Cleaned Extraction v2 Candidates

## Summary

- Original candidate count: 940
- Cleaned candidate count: 937
- Suppressed count: 3
- Downgraded count: 47
- Converted row type count: 238
- Conflict review count: 95
- Manual review count: 12
- Row type counts: {'comparative_numeric_fact': 299, 'heading': 126, 'metadata': 57, 'numeric_fact': 233, 'subtotal_or_total': 76, 'text_block': 146}
- Database mutated: False
- Live model calls made: False

## Audit Trail

The JSON report retains every original candidate with original_candidate_id, proposed row type, action, duplicate groups, and cleaned candidate payload.

## Limitations

- Cleaned candidates are benchmark/reporting output only.
- Original extraction report is not modified.
- Conflicting values are preserved for review and are not automatically chosen.
- No taxonomy mapping, XBRL generation, Arelle validation, DB mutation, live model call, or production cutover is performed.
