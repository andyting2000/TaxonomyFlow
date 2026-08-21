# TOC-aware pipeline safety #19A

Status: **PASS**

## Default and compatibility boundary

Analysis, persistence, and the reserved LLM fallback all default to false. The analyzer is deterministic and local. It adds no Azure provider call and makes no LLM or Supervisor call.

Enabled and disabled extraction snapshots match across labels, values, periods, statement/template assignments, review state, confirmation state, warnings, and calculation flags. `confirmed_tag_id` and final mapping mutations remain zero. Existing suggestions, Supervisor records, XBRL, and Arelle are untouched.

## Failure and retry behavior

- No TOC is a structured warning; an otherwise usable filing reaches `REVIEW`.
- Analyzer exceptions produce `toc_aware_structure_analysis_failed`; extraction/mapping continues.
- Artifact exceptions produce `toc_aware_structure_persistence_failed`; stale output is removed and the workflow continues.
- The underlying extraction remains authoritative for genuinely unusable documents.

Every extraction attempt invalidates the prior derived artifact, including retries with either #19A flag disabled. A single fixed job/version path and atomic replace prevent duplicate/partial artifacts.

## Access, cleanup, and bounds

The API uses the existing owned-job check, hides cross-owner jobs, and exposes results only for `REVIEW`/`COMPLETED`. Normal job deletion and account deletion remove the artifact; the directory is Git-ignored.

Resource limits cover TOC pages/lines/entries, heading candidates/comparisons, content inventory/grouping comparisons, and a 25 MiB artifact. Loads validate both schema and embedded identity.

## Verification

- Focused #19A suites: 51 passed
- Full backend discovery: 1,317 passed
- Changed-file compilation: passed
- App import: passed, 83 routes
- Report and tracker JSON validation: passed
- Live Azure/LLM/Supervisor calls: zero

Residual risk is explicit: unusual layouts may yield warnings, unassigned content, or human-review requirements. Heading-only fallback, relational persistence, classification, mapping, UI migration, XBRL, and Arelle remain deferred.

Recommended next: **#19B — classify primary sections and note subsections into the 24 internal template groups.**
