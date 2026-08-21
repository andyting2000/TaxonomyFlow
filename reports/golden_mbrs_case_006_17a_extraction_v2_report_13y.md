# Azure DI Normalized Extraction v2 Candidates - Feature #13Y

## Summary

- Input report: reports\golden_mbrs_azure_di_capture_case_006_17a.json
- Original candidates: 320
- Normalized candidates: 95
- Row type counts before: {'comparative_numeric_fact': 29, 'heading': 201, 'metadata': 38, 'numeric_fact': 1, 'subtotal_or_total': 5, 'text_block': 46}
- Row type counts after: {'comparative_numeric_fact': 22, 'heading': 24, 'metadata': 3, 'numeric_fact': 1, 'subtotal_or_total': 9, 'text_block': 36}
- Total candidates: 95
- Numeric facts: 1
- Comparative numeric facts: 22
- Subtotal/total: 9
- Text blocks: 36
- Headings: 24
- Metadata: 3
- Index/TOC rows suppressed: 18
- Header/footer/context rows removed from normalized rows: 200
- Merged text-block fragments: 10
- Database mutated: False
- Production behavior changed: False
- Live provider calls: False

## Action Counts

- downgrade_to_metadata: 76
- keep: 92
- keep_for_context_only: 124
- merge_text_block_fragment: 10
- suppress_index_or_toc_row: 18

## Limitations

- Report-only Azure DI normalization; no production cutover.
- No Azure DI, Hugging Face, OpenAI, semantic matcher, DB, XBRL, Arelle, API, or UI call is performed.
- Suppressed candidates remain preserved in the normalization audit trail.
