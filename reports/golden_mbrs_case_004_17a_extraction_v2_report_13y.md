# Azure DI Normalized Extraction v2 Candidates - Feature #13Y

## Summary

- Input report: reports\golden_mbrs_azure_di_capture_case_004_17a.json
- Original candidates: 464
- Normalized candidates: 127
- Row type counts before: {'comparative_numeric_fact': 42, 'heading': 303, 'metadata': 61, 'numeric_fact': 7, 'subtotal_or_total': 14, 'text_block': 37}
- Row type counts after: {'comparative_numeric_fact': 42, 'heading': 20, 'metadata': 13, 'numeric_fact': 7, 'subtotal_or_total': 14, 'text_block': 31}
- Total candidates: 127
- Numeric facts: 7
- Comparative numeric facts: 42
- Subtotal/total: 14
- Text blocks: 31
- Headings: 20
- Metadata: 13
- Index/TOC rows suppressed: 0
- Header/footer/context rows removed from normalized rows: 331
- Merged text-block fragments: 6
- Database mutated: False
- Production behavior changed: False
- Live provider calls: False

## Action Counts

- downgrade_to_metadata: 95
- keep: 127
- keep_for_context_only: 236
- merge_text_block_fragment: 6

## Limitations

- Report-only Azure DI normalization; no production cutover.
- No Azure DI, Hugging Face, OpenAI, semantic matcher, DB, XBRL, Arelle, API, or UI call is performed.
- Suppressed candidates remain preserved in the normalization audit trail.
