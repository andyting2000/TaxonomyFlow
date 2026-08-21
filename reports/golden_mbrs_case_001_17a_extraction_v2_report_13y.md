# Azure DI Normalized Extraction v2 Candidates - Feature #13Y

## Summary

- Input report: reports\golden_mbrs_azure_di_capture_case_001_17a.json
- Original candidates: 526
- Normalized candidates: 148
- Row type counts before: {'comparative_numeric_fact': 59, 'heading': 345, 'metadata': 67, 'numeric_fact': 9, 'subtotal_or_total': 8, 'text_block': 38}
- Row type counts after: {'comparative_numeric_fact': 59, 'heading': 22, 'metadata': 14, 'numeric_fact': 9, 'subtotal_or_total': 8, 'text_block': 36}
- Total candidates: 148
- Numeric facts: 9
- Comparative numeric facts: 59
- Subtotal/total: 8
- Text blocks: 36
- Headings: 22
- Metadata: 14
- Index/TOC rows suppressed: 0
- Header/footer/context rows removed from normalized rows: 376
- Merged text-block fragments: 2
- Database mutated: False
- Production behavior changed: False
- Live provider calls: False

## Action Counts

- downgrade_to_metadata: 110
- keep: 148
- keep_for_context_only: 266
- merge_text_block_fragment: 2

## Limitations

- Report-only Azure DI normalization; no production cutover.
- No Azure DI, Hugging Face, OpenAI, semantic matcher, DB, XBRL, Arelle, API, or UI call is performed.
- Suppressed candidates remain preserved in the normalization audit trail.
