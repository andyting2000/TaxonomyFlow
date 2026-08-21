# Golden MBRS Dataset Summary - Feature #17A

## Metrics

- total_cases: 6
- ready_pdf_xml_pairs: 6
- cases_with_normalized_azure_di_extraction: 6
- cases_missing_normalized_azure_di_extraction: 0
- total_extracted_rows: 857
- total_xml_facts: 2549
- aligned_rows: 110
- unaligned_rows: 526
- strong_gold_examples: 110
- ambiguous_alignments: 221
- concept_coverage: {'strong_gold_concepts': 39, 'reference_concepts': 282, 'ratio': 0.1383}
- value_match_rate: 0.3944
- current_prior_ambiguity: 77

## Cases

| Case | Pair | Azure DI | XML Facts | Extracted Rows | Strong Gold | Ambiguous | Unaligned |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| case_001 | ready | consumed | 413 | 148 | 17 | 48 | 83 |
| case_002 | ready | consumed | 427 | 171 | 26 | 40 | 105 |
| case_003 | ready | consumed | 414 | 146 | 19 | 41 | 86 |
| case_004 | ready | consumed | 400 | 127 | 19 | 35 | 73 |
| case_005 | ready | consumed | 421 | 170 | 22 | 36 | 112 |
| case_006 | ready | consumed | 474 | 95 | 7 | 21 | 67 |

## Limitations

- Only local normalized Azure DI reports are consumed; missing captures are reported explicitly.
- Strong gold examples are conservative alignments, not automatically applied mappings.
- Auditor XML remains local and is not sent to any external provider or LLM.
