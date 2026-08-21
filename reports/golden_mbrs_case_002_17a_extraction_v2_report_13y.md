# Azure DI Normalized Extraction v2 Candidates - Feature #13Y

## Summary

- Input report: reports\golden_mbrs_azure_di_capture_case_002_17a.json
- Original candidates: 707
- Normalized candidates: 171
- Row type counts before: {'comparative_numeric_fact': 79, 'heading': 489, 'metadata': 69, 'numeric_fact': 15, 'subtotal_or_total': 13, 'text_block': 42}
- Row type counts after: {'comparative_numeric_fact': 74, 'heading': 23, 'metadata': 14, 'numeric_fact': 15, 'subtotal_or_total': 11, 'text_block': 34}
- Total candidates: 171
- Numeric facts: 15
- Comparative numeric facts: 74
- Subtotal/total: 11
- Text blocks: 34
- Headings: 23
- Metadata: 14
- Index/TOC rows suppressed: 0
- Header/footer/context rows removed from normalized rows: 528
- Merged text-block fragments: 8
- Database mutated: False
- Production behavior changed: False
- Live provider calls: False

## Action Counts

- downgrade_to_metadata: 243
- keep: 171
- keep_for_context_only: 285
- merge_text_block_fragment: 8

## Limitations

- Report-only Azure DI normalization; no production cutover.
- No Azure DI, Hugging Face, OpenAI, semantic matcher, DB, XBRL, Arelle, API, or UI call is performed.
- Suppressed candidates remain preserved in the normalization audit trail.
