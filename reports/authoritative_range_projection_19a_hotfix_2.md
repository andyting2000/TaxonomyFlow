# Authoritative range projection #19A-hotfix-2

Status: **PASS** for implementation and regression coverage. Fresh real-PDF smoke: **PENDING**.

Job 66 v2 published Notes at PDF `0-0` / Azure `1-1` even though its printed range was `15-22` and its own page mappings resolved that range to PDF `16-23`. The section artifact, not merely its display, was contradictory.

Explicit TOC ranges now take authority when alignment confidence is at least `0.80`, review is not required, the method is weighted consensus or piecewise alignment, and both endpoints have unique compatible mappings. A heading may confirm the mapped start, refine geometry within a page, or assist when a mapping is missing; an off-regime heading cannot replace that range.

The consistency validator compares every resolvable explicit section range with the mapping endpoints. A contradiction emits `section_range_conflicts_with_page_mapping`. Under reliable alignment it is reconciled and records `section_range_reconciled_to_page_mapping`; otherwise the range is cleared and marked unresolved/review-required, so a false range is not silently published.

The Job 66 fixture derives all nine primary ranges from offset +1: Directors `2-5`, Statement by Directors `6`, Statutory `7`, Auditor `8-11`, the four primary statements `12`, `13`, `14`, `15`, and Notes `16-23` (Azure `17-24`). It validates nine mappings, reports zero unresolved conflicts, and a forced Notes `0-0` contradiction is detected and reconciled to `16-23`.

Because this changes artifact semantics, the structure contract is now `19A-v3` / `structure_19a_v3.json`. A v2 artifact cannot load as current, and the source version/hash contract makes dependent #19B and #19C artifacts stale.
