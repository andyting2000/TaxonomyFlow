# Golden MBRS Few-Shot Qwen vs Baseline #17B

- Holdout rows: `29`
- External LLM called: `True`
- Auditor XML sent externally: `False`
- Target gold answers sent externally: `False`

| Metric | Few-shot Qwen | #17B-pre Qwen Same Holdout | Delta |
|---|---:|---:|---:|
| coverage | `0.6552` | `0.5517` | `0.1035` |
| accuracy | `0.6552` | `0.5517` | `0.1035` |
| accuracy_when_predicted | `1.0` | `1.0` | `0.0` |
| correct | `19` | `16` | `3.0` |
| wrong_concept | `0` | `0` | `0.0` |
| no_prediction | `10` | `13` | `-3.0` |
