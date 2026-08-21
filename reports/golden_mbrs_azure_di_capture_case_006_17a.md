# Azure Document Intelligence Extraction v2 Spike - Feature #13W

## Summary

- Provider: azure_document_intelligence
- Model ID: prebuilt-layout
- Cases processed: 1
- Pages processed: 15
- Tables detected: 10
- Characters detected: 15875
- Candidate rows: 320
- Numeric facts: 1
- Comparative numeric facts: 29
- Text blocks: 46
- Runtime seconds: 43.062
- Average seconds/page: 2.871
- Database mutated: False
- Production behavior changed: False
- Reference XML sent to provider: False

## Per Case

| Case | Status | Pages | Tables | Chars | Candidates | Numeric | Comparative | Text Blocks | Runtime s |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| case_006 | ok | 15 | 10 | 15875 | 320 | 1 | 29 | 46 | 7.594 |

## Limitations

- Read-only Azure DI spike only; no production cutover.
- prebuilt-layout output is converted with conservative heuristics and is not final mapping evidence.
- Reference XML is used only for offline comparison reports and is not sent to Azure DI.
- No DB writes, API/UI changes, Hugging Face/OpenAI calls, XBRL generation, or Arelle validation are performed.
