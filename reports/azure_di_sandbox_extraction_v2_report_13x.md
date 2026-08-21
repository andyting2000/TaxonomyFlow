# Azure DI-first Extraction v2 Sandbox - Feature #13X

## Summary

- Provider: azure_document_intelligence
- Model ID: prebuilt-layout
- PDF: benchmark_cases\007-Shield-Plus\Shield-Plus.pdf
- Case ID: Shield-Plus
- Pages processed: 15
- Tables detected: 10
- Paragraphs detected: 372
- Content characters: 15875
- Total candidates: 317
- Numeric candidates: 1
- Comparative numeric candidates: 26
- Text blocks: 46
- Runtime seconds: 46.813
- Average seconds/page: 3.121
- Approval flag used: True
- Database mutated: False
- Production behavior changed: False
- Reference XML sent to provider: False

## Cost Runtime

- Pages sent to Azure DI: 15
- Estimated billable pages: 15
- Dollar cost estimated: False

## Cost Tracking

- Azure Portal -> Document Intelligence resource -> Monitoring -> Metrics -> Processed Pages
- Azure Portal -> Cost Management + Billing -> Cost Analysis

## Limitations

- Sandbox report only; no production cutover.
- Azure DI prebuilt-layout is the primary extraction direction for this sandbox path, not validated production behavior.
- Reference XML is not sent to Azure DI or any model.
- No DB mutation, API/UI implementation, Hugging Face/OpenAI call, semantic matcher call, XBRL generation, or Arelle validation is performed.
