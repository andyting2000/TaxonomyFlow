# Supervisor-guided remapping safety - #18F-G-A

- Backend and frontend correction flags default to disabled.
- Auto-run is false and the service fails closed if it is enabled.
- The default retry limit is one durable attempt per initial suggestion.
- Original suggestions and extracted-row mapping fields are never updated.
- Every revision requires human review and is unsafe for auto-apply.
- Auditor XML, parsed XML facts, gold answers, and evaluation labels are excluded.
- Tests and report generation made no external LLM calls.
