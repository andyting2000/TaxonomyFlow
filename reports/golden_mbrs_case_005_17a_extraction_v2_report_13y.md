# Azure DI Normalized Extraction v2 Candidates - Feature #13Y

## Summary

- Input report: reports\golden_mbrs_azure_di_capture_case_005_17a.json
- Original candidates: 684
- Normalized candidates: 170
- Row type counts before: {'comparative_numeric_fact': 86, 'heading': 473, 'metadata': 66, 'numeric_fact': 9, 'subtotal_or_total': 12, 'text_block': 38}
- Row type counts after: {'comparative_numeric_fact': 80, 'heading': 20, 'metadata': 16, 'numeric_fact': 8, 'subtotal_or_total': 12, 'text_block': 34}
- Total candidates: 170
- Numeric facts: 8
- Comparative numeric facts: 80
- Subtotal/total: 12
- Text blocks: 34
- Headings: 20
- Metadata: 16
- Index/TOC rows suppressed: 0
- Header/footer/context rows removed from normalized rows: 512
- Merged text-block fragments: 4
- Database mutated: False
- Production behavior changed: False
- Live provider calls: False

## Action Counts

- downgrade_to_metadata: 217
- keep: 168
- keep_for_context_only: 295
- merge_text_block_fragment: 4

## Limitations

- Report-only Azure DI normalization; no production cutover.
- No Azure DI, Hugging Face, OpenAI, semantic matcher, DB, XBRL, Arelle, API, or UI call is performed.
- Suppressed candidates remain preserved in the normalization audit trail.
