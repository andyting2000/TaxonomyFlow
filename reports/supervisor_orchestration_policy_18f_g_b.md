# Supervisor Orchestration Policy

Eligibility uses only persisted mapping evidence, row context, ranked candidates, diagnostics, reviews, and revisions. It imports no LLM client and performs no external call.

High-priority signals include no safe candidate, statement/concept-family mismatch, and candidate-source conflict. Medium signals include broad substitutes, period ambiguity, close competitors, low confidence, confirmation requirements, and explicit human request.

Completed reviews are not requeued. Remapping becomes available only after a completed non-agree review with concrete mapping evidence and is blocked after one durable attempt.

The jobs 59-61 sample produced a `76%` eligibility rate. Calibration is required before application-workflow integration.
