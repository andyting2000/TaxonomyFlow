# Azure DI Normalized Extraction v2 Candidates - Feature #13Y

## Summary

- Input report: reports\golden_mbrs_azure_di_capture_case_003_17a.json
- Original candidates: 564
- Normalized candidates: 146
- Row type counts before: {'comparative_numeric_fact': 60, 'heading': 379, 'metadata': 64, 'numeric_fact': 9, 'subtotal_or_total': 14, 'text_block': 38}
- Row type counts after: {'comparative_numeric_fact': 60, 'heading': 19, 'metadata': 13, 'numeric_fact': 9, 'subtotal_or_total': 12, 'text_block': 33}
- Total candidates: 146
- Numeric facts: 9
- Comparative numeric facts: 60
- Subtotal/total: 12
- Text blocks: 33
- Headings: 19
- Metadata: 13
- Index/TOC rows suppressed: 0
- Header/footer/context rows removed from normalized rows: 413
- Merged text-block fragments: 5
- Database mutated: False
- Production behavior changed: False
- Live provider calls: False

## Action Counts

- downgrade_to_metadata: 138
- keep: 146
- keep_for_context_only: 275
- merge_text_block_fragment: 5

## Limitations

- Report-only Azure DI normalization; no production cutover.
- No Azure DI, Hugging Face, OpenAI, semantic matcher, DB, XBRL, Arelle, API, or UI call is performed.
- Suppressed candidates remain preserved in the normalization audit trail.
