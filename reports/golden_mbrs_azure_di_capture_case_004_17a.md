# Azure Document Intelligence Extraction v2 Spike - Feature #13W

## Summary

- Provider: azure_document_intelligence
- Model ID: prebuilt-layout
- Cases processed: 1
- Pages processed: 22
- Tables detected: 16
- Characters detected: 30364
- Candidate rows: 464
- Numeric facts: 7
- Comparative numeric facts: 42
- Text blocks: 37
- Runtime seconds: 466.359
- Average seconds/page: 21.198
- Database mutated: False
- Production behavior changed: False
- Reference XML sent to provider: False

## Per Case

| Case | Status | Pages | Tables | Chars | Candidates | Numeric | Comparative | Text Blocks | Runtime s |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| case_004 | ok | 22 | 16 | 30364 | 464 | 7 | 42 | 37 | 8.703 |

## Limitations

- Read-only Azure DI spike only; no production cutover.
- prebuilt-layout output is converted with conservative heuristics and is not final mapping evidence.
- Reference XML is used only for offline comparison reports and is not sent to Azure DI.
- No DB writes, API/UI changes, Hugging Face/OpenAI calls, XBRL generation, or Arelle validation are performed.
