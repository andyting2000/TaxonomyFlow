# Job 69 Notes segmentation - #19B-hotfix-1

Status: **PASS**

## Boundary result

- Parent Notes range: PDF 16-23 (unchanged)
- Before: 116 v1 children
- After: 24 v2 logical children
- Raw v2 candidates: 148
- Physical/semantic duplicates merged: 19
- Continuation headings merged: 2
- Boilerplate boundaries suppressed: 31
- Table/value boundaries suppressed: 50
- Invalid numeric note numbers rejected: 7
- Prose candidates rejected: 15

## Conservation and fact attachment

- Evidence: total=604, assigned=604, ambiguous=0, unassigned=0, dropped=0
- Conservation: True
- Extracted rows attached: 11
- Zero-meaning children: 0
- Share Capital extracted rows: 1
- Share Capital assignments: 740000
- Standalone RM child present: False

## Classification

- Before child outcomes: {'matched': 12, 'unassigned': 104}
- After child outcomes: {'matched': 6, 'unassigned': 18}
- Registry semantics and deterministic classifier were not broadened; only corrected logical child evidence was reclassified.

## Version and downstream contract

- Current artifact: `template_classification_19b_v2.json` (19B-v2)
- v1 is stale by filename/version after the child identity and segmentation semantic change.
- Existing Job 69 #19C source version: 19B-v1
- Existing Job 69 #19C regeneration required: True
- #19C compatibility remains fail-closed through current #19B version/hash linkage; no ranking code changed.

## Safety

- Live LLM calls: 0
- Azure provider calls: 0
- Mapping/tag/final-mapping mutations: 0
- XBRL and Arelle were not run.
