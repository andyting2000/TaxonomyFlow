# Azure Document Intelligence Extraction v2 Spike - Feature #13W

## Summary

- Provider: azure_document_intelligence
- Model ID: prebuilt-layout
- Cases processed: 1
- Pages processed: 26
- Tables detected: 13
- Characters detected: 38290
- Candidate rows: 526
- Numeric facts: 9
- Comparative numeric facts: 59
- Text blocks: 38
- Runtime seconds: 662.641
- Average seconds/page: 25.486
- Database mutated: False
- Production behavior changed: False
- Reference XML sent to provider: False

## Per Case

| Case | Status | Pages | Tables | Chars | Candidates | Numeric | Comparative | Text Blocks | Runtime s |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| case_001 | ok | 26 | 13 | 38290 | 526 | 9 | 59 | 38 | 8.937 |

## Limitations

- Read-only Azure DI spike only; no production cutover.
- prebuilt-layout output is converted with conservative heuristics and is not final mapping evidence.
- Reference XML is used only for offline comparison reports and is not sent to Azure DI.
- No DB writes, API/UI changes, Hugging Face/OpenAI calls, XBRL generation, or Arelle validation are performed.
