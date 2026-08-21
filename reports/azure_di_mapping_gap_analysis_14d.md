# Azure DI Mapping Gap Analysis - Feature #14D

## Summary

- No-safe labels: 4
- Weak row-type coverage: {'numeric_fact': 1, 'text_block': 5, 'comparative_numeric_fact': 11, 'subtotal_or_total': 3}
- Recommended next feature: Feature #14E - Reviewed mapping quality evaluation against reference XML, no DB mutation.

## No-Safe Labels

- `13V-MAP-0006` - Owners of the Company (numeric_fact)
- `13V-MAP-0023` Statutory Declaration: No. A-1, Jalan S.321/37 Damansara Utama (,, Ti ... > (text_block)
- `13V-MAP-0039` Increase in director's account (comparative_numeric_fact)
- `13V-MAP-0052` no par value (comparative_numeric_fact)

## Concept Metadata Limitations

- Enrichment v2 is deterministic and attaches aliases only to existing local/reference-inventory qnames.
- No fake concept qnames are created.
- Reference report, when provided, is used only as offline concept inventory and not as a direct answer key.
- No Azure DI, Hugging Face, OpenAI, embeddings, semantic matcher, DB, XBRL, or Arelle path is used.

## Limitations

- Deterministic local metadata suggestions only; no final mapping is approved.
- No semantic matcher, embeddings, LLM, Azure DI, Hugging Face, OpenAI, DB mutation, XBRL generation, or Arelle validation is used.
- Reference report, when provided, is used only as offline concept inventory/gap context and not as a direct answer key.
