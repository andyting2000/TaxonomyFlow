# Ranked Candidate Dry-Run Safety - #18F-F

The enabled test smoke returned zero for every mutation counter. Every returned candidate required human review and was not auto-applicable.

The UI guard now rejects non-zero mutation counters, unsafe candidate booleans, and unsafe action values. It retains the unsafe response only to display the safety summary and warning; candidate rows are blocked. The panel contains no mutation, confirmation, acceptance, application, save, or auto-map action.
