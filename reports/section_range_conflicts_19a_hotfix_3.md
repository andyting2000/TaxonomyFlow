# Section Range Conflicts 19A Hotfix 3

- Analysis status: `PASS`
- Real-PDF smoke: `NOT_RERUN`
- Source: Job `67` `19A-v3` (read-only)
- Target contract: `19A-v4`

## Conflict root causes and corrected ranges

### Directors' Report

- Printed: `[1, 4]`; mapped PDF: `[2, 5]`; persisted v3: `[None, None]`.
- Anchor: `A` / `exact_normalized_title` on PDF `2`; expected/actual offset `1` / `1`.
- Root cause: The document-wide page_alignment_ambiguous flag activated unsafe_range_projection after the exact Tier-A start anchor had resolved PDF page 2. That branch collapsed the already derivable 2-5 range to 2-2; the fail-closed validator then cleared both endpoints.
- Corrected derived PDF range: `[2, 5]`; geometry remains start-only at `2.2573`.
- Consistency: `validated`; review: `False`.

### Independent Auditors' Report

- Printed: `[7, 10]`; mapped PDF: `[8, 11]`; persisted v3: `[None, None]`.
- Anchor: `B` / `canonical_title_prefix` on PDF `8`; expected/actual offset `1` / `1`.
- Root cause: Repeated canonical-prefix report headers produced a cross-page near tie. The selected PDF-8 anchor agreed with the +1 regime, but the old grouper withheld it and the document-wide ambiguous flag discarded the uniquely mapped 8-11 endpoints; the validator then cleared both endpoints.
- Corrected derived PDF range: `[8, 11]`; geometry remains start-only at `3.1712`.
- Consistency: `validated`; review: `False`.

### Notes to the Financial Statements

- Printed: `[15, 22]`; mapped PDF: `[16, 23]`; persisted v3: `[None, None]`.
- Anchor: `B` / `canonical_title_prefix` on PDF `16`; expected/actual offset `1` / `1`.
- Root cause: Repeated Notes continuation headers produced a cross-page near tie. The selected PDF-16 anchor agreed with the +1 regime, but the old grouper withheld it and discarded the uniquely mapped 16-23 endpoints, leaving the long Notes container unresolved.
- Corrected derived PDF range: `[16, 23]`; geometry remains start-only at `2.0656`.
- Consistency: `validated`; review: `False`.

## Assignment and containment

- Before: assigned `640`, unassigned `1589`, assignment excluding TOC `0.300611`, dropped `0`.
- Projected after: assigned `1699`, unassigned `530`, assignment excluding TOC `0.798027`, unassigned excluding TOC `0.201973`, dropped `0`.
- Range topology: `{'section_page_gap_count': 0, 'section_page_overlap_count': 0, 'section_same_page_geometry_boundary_count': 0}`.
- Notes containment: `{'parent_pdf_range': [16, 23], 'parent_evidence_count': 604, 'child_count': 116, 'children_outside_parent_count': 0, 'children_outside_parent': [], 'cover_page_child_count': 0, 'conservation_passed': True, 'dropped_items': 0}`.
- Human review: `{'alignment_requires_human_review': False, 'section_ids_requiring_human_review': [], 'requires_human_review': False}`.

## Versioning and safety

- Incremented to 19A-v4 / structure_19a_v4.json because persisted page-range and geometry semantics changed. Existing 19B/19C version/hash validation rejects v3 linkages.
- No provider, live LLM, database, mapping/template, confirmed/final mapping, XBRL, or Arelle action occurred.
- Fixture/projection PASS is not a fresh real-PDF PASS.
