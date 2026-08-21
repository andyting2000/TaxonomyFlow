# Feature #13R Extraction v2 Candidate Quality Report

## Summary

- Total candidates analyzed: 92
- Candidate type distribution: {'comparative_numeric_fact': 22, 'heading': 24, 'numeric_fact': 1, 'subtotal_or_total': 9, 'text_block': 36}
- Source distribution: {'unknown': 92}
- Readiness distribution: {'high': 20, 'low': 2, 'medium': 46, 'not_ready': 24}
- Database mutated: False
- Live model calls made: False
- Reference XML sent to model: False

## Numeric Quality

- Numeric candidates: 32
- Missing values: 0
- Non-numeric values: 0
- Date/year values as amounts: 0
- Parentheses negatives: 0
- Dash/zero values: 7
- Amount formatting concerns: 0

## Text-Block Quality

- Text blocks: 36
- Short text blocks: 1
- Long text blocks: 0
- Heading-only text blocks: 0
- Weak text-block labels: 0
- Cases missing text-block signal: []

## Source Quality

- Hugging Face candidates: 0
- Native-only candidates: 0
- OpenAI candidates: 0
- Unknown-source candidates: 92

## Top Issue Categories

- numeric_quality: 12
- label_quality: 9
- comparative_quality: 9
- duplicate_quality: 4
- section_quality: 1
- text_block_quality: 1

## Per Case

| Case | Candidates | Numeric | Text Blocks | HF | Native | Score | Readiness |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Shield-Plus | 92 | 32 | 36 | 0 | 0 | 50.9 | ready_for_mapping_prototype |

## Limitations

- Heuristic analysis only; scores are provisional and are not final mapping accuracy.
- Reference report is used only for offline comparison and is not sent to any model.
- No benchmark rerun, model call, DB mutation, XBRL generation, Arelle validation, UI upload, or production cutover is performed.
