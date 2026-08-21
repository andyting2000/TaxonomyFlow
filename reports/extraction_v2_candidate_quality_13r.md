# Feature #13R Extraction v2 Candidate Quality Report

## Summary

- Total candidates analyzed: 940
- Candidate type distribution: {'comparative_numeric_fact': 37, 'heading': 129, 'metadata': 10, 'numeric_fact': 542, 'subtotal_or_total': 76, 'text_block': 146}
- Source distribution: {'huggingface': 818, 'native_only': 122}
- Readiness distribution: {'high': 337, 'low': 146, 'medium': 318, 'not_ready': 139}
- Database mutated: False
- Live model calls made: False
- Reference XML sent to model: False

## Numeric Quality

- Numeric candidates: 655
- Missing values: 0
- Non-numeric values: 7
- Date/year values as amounts: 0
- Parentheses negatives: 135
- Dash/zero values: 123
- Amount formatting concerns: 423

## Text-Block Quality

- Text blocks: 146
- Short text blocks: 9
- Long text blocks: 0
- Heading-only text blocks: 0
- Weak text-block labels: 65
- Cases missing text-block signal: ['001-bizaid-synthetic']

## Source Quality

- Hugging Face candidates: 818
- Native-only candidates: 122
- OpenAI candidates: 0
- Unknown-source candidates: 0

## Top Issue Categories

- numeric_quality: 755
- comparative_quality: 372
- duplicate_quality: 211
- label_quality: 163
- text_block_quality: 74
- section_quality: 57
- label_pollution: 50
- mapping_readiness: 47

## Per Case

| Case | Candidates | Numeric | Text Blocks | HF | Native | Score | Readiness |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 001-bizaid-synthetic | 122 | 40 | 0 | 0 | 122 | 11.5 | needs_numeric_cleanup_first |
| 002-bezlife-marketing | 115 | 89 | 24 | 115 | 0 | 81.0 | needs_text_block_cleanup_first |
| 003-fine-batik | 189 | 158 | 28 | 189 | 0 | 72.7 | needs_numeric_cleanup_first |
| 004-info-house | 150 | 99 | 34 | 150 | 0 | 58.9 | needs_manual_review_policy |
| 005-jconnector | 134 | 90 | 29 | 134 | 0 | 63.5 | needs_candidate_cleanup_first |
| 006-Rahsia-Herbal | 146 | 126 | 14 | 146 | 0 | 66.8 | needs_manual_review_policy |
| 007-Shield-Plus | 84 | 53 | 17 | 84 | 0 | 52.2 | needs_numeric_cleanup_first |

## Limitations

- Heuristic analysis only; scores are provisional and are not final mapping accuracy.
- Reference report is used only for offline comparison and is not sent to any model.
- No benchmark rerun, model call, DB mutation, XBRL generation, Arelle validation, UI upload, or production cutover is performed.
