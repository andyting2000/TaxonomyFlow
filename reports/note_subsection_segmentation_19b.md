# Note Subsection Segmentation #19B

- Status: `PASS`
- Feature: `19B-resume`
- Registry: `mpers-2022-v1`
- Registry hash: `16de7eaeafcdf760c7f4869072a6b0a3925088f6bc260672389b5c502015b7d4`

## Evidence

- `fixture`: tests\fixtures\toc_aware\fixture_i_notes_spanning_pages.json
- `child_subsection_count`: 3
- `child_headings`: ["1. BASIS OF PREPARATION", "2. SIGNIFICANT ACCOUNTING POLICIES", "3. PROPERTY, PLANT AND EQUIPMENT"]
- `conservation`: {"ambiguous_evidence_ids": [], "ambiguous_items": 0, "assigned_evidence_ids": ["page:4:line:1", "page:5:line:0", "page:6:line:0"], "assigned_items": 3, "dropped_items": 0, "passed": true, "total_notes_evidence_items": 4, "unassigned_evidence_ids": ["page:4:line:0"], "unassigned_items": 1}
- `warnings`: ["unassigned_notes_content"]
- `structural_parent`: notes_container
- `taxonomy_code_for_structural_parent`: None
- `730000_behavior`: taxonomy leaf Notes - List of notes only

## Decision

Notes evidence is conserved with zero dropped items.
