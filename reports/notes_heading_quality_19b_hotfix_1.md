# Notes heading quality - #19B-hotfix-1

Status: **PASS**

## Deterministic rules

- Recognize bounded decimal, nested alphabetic, and Roman note-number forms; numeric components must be 1-99.
- Prefer Azure section-heading roles and #19A candidates while retaining a deterministic lexical fallback.
- Reject repeated document headers, company identifiers/names, Notes running headers, page markers, and DRAFT fragments as boundaries.
- Reject standalone units, numeric/table fragments, and geometry-overlapping table candidates unless independent section-heading evidence exists.
- Reject long or sentence-like numbered prose using length, word count, punctuation, lead phrase, and verb signals.
- Collapse paragraph/line duplicates by normalized title, compatible number, page, and vertical proximity while retaining every contributing evidence ID.
- Merge same-number/title continuation events into one logical child and preserve every boundary position for page-span assignment.
- Hash parent ID plus stable logical number/title identity for deterministic child IDs.
- Treat a rejected candidate as content, never as dropped evidence; leading Notes boilerplate attaches to the first logical child.

## Job 69 metrics

- raw_heading_candidate_count: 148
- accepted_heading_candidate_count: 45
- accepted_logical_subsection_count: 24
- duplicate_headings_merged: 19
- continuation_headings_merged: 2
- boilerplate_lines_suppressed: 31
- table_value_fragments_suppressed: 50
- invalid_numeric_note_numbers_rejected: 7
- prose_candidates_rejected: 15
- other_low_quality_candidates_rejected: 0
- extracted_rows_attached: 11
- child_sections_with_zero_meaningful_content: 0

## Regression categories

- boilerplate: COMPANY NO..., company-name header, NOTES TO THE FINANCIAL STATEMENTS ... (Continued), DRAFT/DRAF/DRA/DR, repeated page number
- table_or_value: RM, TO, 100 100, 700 1,398
- invalid_numeric_note_number: 465 ..., 700 ..., 897 ...
- prose: 2. The financial statements have been prepared ..., c) After initial recognition, the Company measures ..., 10. The financial statements of the Company ...
- preserved_nested: a) Initial recognition and measurement, b) Subsequent measurement of financial assets, c) Subsequent measurement of financial liabilities, d) Derecognition of financial instruments

All rejected boundary candidates remain assigned source evidence; rejection only prevents a child boundary.
