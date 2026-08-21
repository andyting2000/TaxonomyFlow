# Hybrid Mapper Policy - Feature #18E-C

- Safe for auto-apply: `False`
- Human review final: `True`
- Confirmed tag automation: `False`
- Combined coverage: `0.4322`
- Hybrid reaches 80%: `False`
- Recommended next feature: Feature #18E-B-2 - Expand deterministic mapper coverage for rows neither mapper covers.

| When | Action |
| --- | --- |
| deterministic and Qwen agree on the same QName | show as strongest review candidate |
| deterministic advisory exists but Qwen is missing or abstains | show deterministic advisory as review candidate |
| Qwen suggests a QName where deterministic mapper has no match | show Qwen candidate as review evidence only |
| deterministic and Qwen suggest different QNames | raise conflict for manual review and do not prefer either automatically |
| neither mapper covers the row | leave unmapped and queue for future deterministic hardening if business-critical |
