# Azure Document Intelligence Extraction v2 Spike - Feature #13W

## Summary

- Provider: azure_document_intelligence
- Model ID: prebuilt-layout
- Cases processed: 1
- Pages processed: 24
- Tables detected: 17
- Characters detected: 32213
- Candidate rows: 684
- Numeric facts: 9
- Comparative numeric facts: 86
- Text blocks: 38
- Runtime seconds: 375.672
- Average seconds/page: 15.653
- Database mutated: False
- Production behavior changed: False
- Reference XML sent to provider: False

## Per Case

| Case | Status | Pages | Tables | Chars | Candidates | Numeric | Comparative | Text Blocks | Runtime s |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| case_005 | ok | 24 | 17 | 32213 | 684 | 9 | 86 | 38 | 8.766 |

## Limitations

- Read-only Azure DI spike only; no production cutover.
- prebuilt-layout output is converted with conservative heuristics and is not final mapping evidence.
- Reference XML is used only for offline comparison reports and is not sent to Azure DI.
- No DB writes, API/UI changes, Hugging Face/OpenAI calls, XBRL generation, or Arelle validation are performed.
