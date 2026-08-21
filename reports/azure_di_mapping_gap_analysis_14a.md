# Azure DI Mapping Gap Analysis - Feature #14A

## Summary

- No-safe labels: 3
- Weak row-type coverage: {'text_block': 26, 'numeric_fact': 1, 'comparative_numeric_fact': 11, 'subtotal_or_total': 3}
- Recommended next feature: Feature #14B - Manual mapping review workflow if ambiguous mappings remain dominant.

## No-Safe Labels

- `13V-MAP-0006` - Owners of the Company (numeric_fact)
- `13V-MAP-0023` Statutory Declaration: No. A-1, Jalan S.321/37 Damansara Utama (,, Ti ... > (text_block)
- `13V-MAP-0052` no par value (comparative_numeric_fact)

## Concept Metadata Limitations

- Reference report was used only as an offline concept inventory fallback, not as a direct answer key.
- Aliases attach only to qnames discovered in local template metadata or optional reference concept inventory.
- No fake concept qnames are created.
- Reference report, when provided, is used only as offline concept inventory and not as a direct answer key.

## Limitations

- Deterministic local metadata suggestions only; no final mapping is approved.
- No semantic matcher, embeddings, LLM, Azure DI, Hugging Face, OpenAI, DB mutation, XBRL generation, or Arelle validation is used.
- Reference report, when provided, is used only as offline concept inventory/gap context and not as a direct answer key.
