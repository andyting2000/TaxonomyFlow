# Feature #13R Extraction v2 Candidate Quality Report

## Summary

- Total candidates analyzed: 317
- Candidate type distribution: {'comparative_numeric_fact': 26, 'heading': 201, 'metadata': 38, 'numeric_fact': 1, 'subtotal_or_total': 5, 'text_block': 46}
- Source distribution: {'unknown': 317}
- Readiness distribution: {'high': 20, 'low': 2, 'medium': 56, 'not_ready': 239}
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

- Text blocks: 46
- Short text blocks: 2
- Long text blocks: 0
- Heading-only text blocks: 0
- Weak text-block labels: 0
- Cases missing text-block signal: []

## Source Quality

- Hugging Face candidates: 0
- Native-only candidates: 0
- OpenAI candidates: 0
- Unknown-source candidates: 317

## Top Issue Categories

- duplicate_quality: 182
- label_quality: 29
- numeric_quality: 12
- comparative_quality: 9
- label_pollution: 8
- text_block_quality: 2

## Per Case

| Case | Candidates | Numeric | Text Blocks | HF | Native | Score | Readiness |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Shield-Plus | 317 | 32 | 46 | 0 | 0 | 6.6 | needs_numeric_cleanup_first |

## Limitations

- Heuristic analysis only; scores are provisional and are not final mapping accuracy.
- Reference report is used only for offline comparison and is not sent to any model.
- No benchmark rerun, model call, DB mutation, XBRL generation, Arelle validation, UI upload, or production cutover is performed.
