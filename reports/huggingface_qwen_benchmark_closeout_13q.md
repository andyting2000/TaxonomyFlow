# Feature #13Q Hugging Face Qwen Benchmark Closeout

## Summary

- Benchmark complete: True
- Full Hugging Face benchmark successful: True
- Provider: huggingface
- Vision model: Qwen/Qwen2.5-VL-72B-Instruct:fastest
- Text model: Qwen/Qwen3-30B-A3B-Instruct-2507:featherless-ai
- Embedding model: Qwen/Qwen3-Embedding-8B
- OpenAI used: False

## Final Aggregate Result

- Cases processed: 7
- Total candidates: 940
- Hugging Face candidates: 818
- Native-only candidates: 122
- OpenAI candidates: 0
- Numeric candidates: 655
- Text-block candidates: 146
- Reference facts: 3101
- Reference numeric facts: 2590
- Reference text blocks: 304
- Missing numeric extraction signal: False
- Missing text-block extraction signal: False

## Improvement Summary

- No-live/native baseline: 122 candidates, 0 Hugging Face candidates.
- Full Hugging Face run: 940 candidates, 818 Hugging Face candidates.
- Text-block signal: improved from missing to present.
- Numeric signal: present and much stronger.

## Per Case

| Case | Candidates | Numeric | Text Blocks | Hugging Face | Native | OpenAI |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 001-bizaid-synthetic | 122 | 40 | 0 | 0 | 122 | 0 |
| 002-bezlife-marketing | 115 | 89 | 24 | 115 | 0 | 0 |
| 003-fine-batik | 189 | 158 | 28 | 189 | 0 | 0 |
| 004-info-house | 150 | 99 | 34 | 150 | 0 | 0 |
| 005-jconnector | 134 | 90 | 29 | 134 | 0 | 0 |
| 006-Rahsia-Herbal | 146 | 126 | 14 | 146 | 0 | 0 |
| 007-Shield-Plus | 84 | 53 | 17 | 84 | 0 | 0 |

## Limitations

- Comparison is rough label/concept overlap only.
- This is not final taxonomy mapping.
- No XBRL generation was performed.
- No Arelle validation was performed.
- No production cutover was performed.
- Candidate quality still needs review.
- Duplicates, labels like 'As at 31/12/2023', headings, totals, and sign/year classification may require cleanup.

## Recommended Next Feature

- Feature #13R - Candidate quality and mapping readiness analysis before production cutover
