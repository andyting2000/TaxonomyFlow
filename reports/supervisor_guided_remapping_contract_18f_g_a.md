# Supervisor-guided remapping contract - #18F-G-A

The POST endpoint is ownership-gated, disabled by default, and admin-only by default. It requires a completed eligible Supervisor review and a remaining retry.

The mapper receives only the production row context, candidate-constrained mapping evidence, advisory Supervisor findings, sanitized concept-card fields, and do-not-confuse guidance. Auditor XML, parsed reference facts, target answers, gold qnames, and evaluation labels are forbidden recursively.

The response separates the initial suggestion, Supervisor review, revised suggestion, and zero-mutation safety counters.
