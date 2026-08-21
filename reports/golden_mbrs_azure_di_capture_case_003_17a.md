# Azure Document Intelligence Extraction v2 Spike - Feature #13W

## Summary

- Provider: azure_document_intelligence
- Model ID: prebuilt-layout
- Cases processed: 1
- Pages processed: 23
- Tables detected: 17
- Characters detected: 30570
- Candidate rows: 564
- Numeric facts: 9
- Comparative numeric facts: 60
- Text blocks: 38
- Runtime seconds: 1798.875
- Average seconds/page: 78.212
- Database mutated: False
- Production behavior changed: False
- Reference XML sent to provider: False

## Per Case

| Case | Status | Pages | Tables | Chars | Candidates | Numeric | Comparative | Text Blocks | Runtime s |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| case_003 | ok | 23 | 17 | 30570 | 564 | 9 | 60 | 38 | 8.688 |

## Limitations

- Read-only Azure DI spike only; no production cutover.
- prebuilt-layout output is converted with conservative heuristics and is not final mapping evidence.
- Reference XML is used only for offline comparison reports and is not sent to Azure DI.
- No DB writes, API/UI changes, Hugging Face/OpenAI calls, XBRL generation, or Arelle validation are performed.
