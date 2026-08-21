import json
from pathlib import Path
import unittest

from schemas import DocumentSection, HeadingAnchor, TocEntry
from services.document_page_alignment import align_document_pages
from services.document_section_grouper import (
    build_document_sections,
    group_document_content,
)
from services.toc_aware_document_structure import analyze_document_structure


FIXTURES = Path(__file__).parent / "fixtures" / "toc_aware"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class DocumentSectionGrouperTests(unittest.TestCase):
    def test_same_page_sections_use_heading_boundaries(self):
        result = analyze_document_structure(
            job_id=10,
            azure_result=load_fixture("fixture_e_same_page_sections.json"),
            normalized_candidates=[],
        )
        by_type = {section.canonical_section_type: section for section in result.sections}
        self.assertIn("page:2:line:1", by_type["statement_by_directors"].text_block_ids)
        self.assertIn("page:2:line:3", by_type["statutory_declaration"].text_block_ids)
        self.assertNotIn("page:2:line:3", by_type["statement_by_directors"].text_block_ids)
        self.assertNotIn("overlapping_section_ranges", result.warnings)
        first = by_type["statement_by_directors"]
        second = by_type["statutory_declaration"]
        self.assertEqual(first.pdf_page_end, second.pdf_page_start)
        self.assertEqual(first.end_heading_bbox, second.start_heading_bbox)
        self.assertEqual(first.end_heading_offset, second.start_heading_offset)
        self.assertNotEqual(first.start_heading_offset, first.end_heading_offset)

    def test_notes_section_is_primary_and_retains_candidate_child_headings(self):
        result = analyze_document_structure(
            job_id=11,
            azure_result=load_fixture("fixture_i_notes_spanning_pages.json"),
            normalized_candidates=[],
        )
        notes = next(section for section in result.sections if section.canonical_section_type == "notes_to_financial_statements")
        self.assertIsNone(notes.parent_section_id)
        self.assertEqual(notes.section_level, 1)
        self.assertEqual(notes.pdf_page_end - notes.pdf_page_start + 1, 3)
        self.assertEqual(len(notes.candidate_note_heading_ids), 3)
        self.assertFalse(any(section.parent_section_id == notes.section_id for section in result.sections))
        evidence_by_id = {
            item.content_id: item
            for item in result.content_evidence
        }
        for heading_id in notes.candidate_note_heading_ids:
            evidence = evidence_by_id[heading_id]
            self.assertTrue(evidence.text_evidence)
            self.assertTrue(evidence.pdf_page_indexes)
            self.assertTrue(evidence.bounding_evidence)

    def test_table_cells_and_normalized_rows_are_referenced_and_conserved(self):
        payload = load_fixture("fixture_a_explicit_ranges.json")
        cells = [
            {"content": "Description", "row_index": 0, "column_index": 0, "page_number": 4, "bounding_regions": [{"page_number": 4, "polygon": [{"x": 1, "y": 200}]}]},
            {"content": "2026", "row_index": 0, "column_index": 1, "page_number": 4, "bounding_regions": [{"page_number": 4, "polygon": [{"x": 5, "y": 200}]}]},
            {"content": "Cash", "row_index": 1, "column_index": 0, "page_number": 4, "bounding_regions": [{"page_number": 4, "polygon": [{"x": 1, "y": 300}]}]},
            {"content": "100", "row_index": 1, "column_index": 1, "page_number": 4, "bounding_regions": [{"page_number": 4, "polygon": [{"x": 5, "y": 300}]}]}
        ]
        payload["tables"] = [{"table_index": 0, "row_count": 2, "column_count": 2, "page_numbers": [4], "cells": cells}]
        candidate = {
            "original_candidate_id": "row-cash",
            "page_number": 4,
            "row_type": "numeric_fact",
            "label": "Cash",
            "value": "100",
            "provenance": {"table_index": 0, "row_index": 1, "cells": cells[2:]},
        }
        result = analyze_document_structure(job_id=12, azure_result=payload, normalized_candidates=[candidate])
        statement = next(section for section in result.sections if section.canonical_section_type == "statement_of_financial_position")
        self.assertIn("table:0", statement.table_ids)
        self.assertEqual(len(statement.table_cell_ids), 4)
        self.assertIn("row-cash", statement.extracted_row_ids)
        self.assertTrue(result.safety_summary["content_conservation_passed"])
        self.assertEqual(result.safety_summary["dropped_content_count"], 0)

    def test_no_toc_creates_no_boundaries_and_preserves_all_content(self):
        result = analyze_document_structure(
            job_id=13,
            azure_result=load_fixture("fixture_f_no_toc.json"),
            normalized_candidates=[],
        )
        self.assertFalse(result.toc_detected)
        self.assertEqual(result.sections, [])
        self.assertEqual(
            result.safety_summary["content_inventory_count"],
            result.safety_summary["unassigned_content_count"],
        )

    def test_same_page_row_without_position_is_ambiguous_not_dropped(self):
        payload = load_fixture("fixture_e_same_page_sections.json")
        candidate = {
            "original_candidate_id": "shared-page-row",
            "page_number": 2,
            "row_type": "numeric_fact",
            "label": "Unpositioned row",
            "value": "1",
            "provenance": {},
        }
        result = analyze_document_structure(job_id=14, azure_result=payload, normalized_candidates=[candidate])
        disposition = next(row for row in result.ambiguous_content if row.content_id == "shared-page-row")
        self.assertEqual(len(disposition.candidate_section_ids), 2)
        self.assertTrue(result.safety_summary["content_conservation_passed"])

    def test_unparsed_toc_line_is_content_evidence_not_a_section_boundary(self):
        payload = load_fixture("fixture_a_explicit_ranges.json")
        repeated_header = "ACME SDN. BHD."
        payload["pages"][0]["lines"].append(
            {"content": repeated_header, "page_number": 1}
        )
        for page in payload["pages"][1:]:
            page["lines"].insert(
                0,
                {
                    "content": repeated_header,
                    "page_number": page["page_number"],
                    "polygon": [{"x": 1, "y": 10}],
                },
            )

        result = analyze_document_structure(
            job_id=15,
            azure_result=payload,
            normalized_candidates=[],
        )

        self.assertFalse(
            any(entry.source_text == repeated_header for entry in result.toc_entries)
        )
        self.assertFalse(
            any(section.raw_title == repeated_header for section in result.sections)
        )
        self.assertEqual(result.ambiguous_content, [])
        self.assertTrue(result.safety_summary["content_conservation_passed"])

    def test_year_like_trailing_number_is_not_a_section_boundary(self):
        payload = load_fixture("fixture_a_explicit_ranges.json")
        payload["pages"][0]["lines"].append(
            {"content": "Financial Year 2026", "page_number": 1}
        )

        result = analyze_document_structure(
            job_id=17,
            azure_result=payload,
            normalized_candidates=[],
        )

        self.assertFalse(
            any(item.source_text == "Financial Year 2026" for item in result.toc_entries)
        )

    def test_table_spanning_two_sections_is_ambiguous_while_cells_remain_assignable(self):
        payload = load_fixture("fixture_a_explicit_ranges.json")
        cells = [
            {"content": "Directors data", "row_index": 0, "column_index": 0, "page_number": 3, "bounding_regions": [{"page_number": 3}]},
            {"content": "Position data", "row_index": 1, "column_index": 0, "page_number": 4, "bounding_regions": [{"page_number": 4}]},
        ]
        payload["tables"] = [{
            "table_index": 9,
            "row_count": 2,
            "column_count": 1,
            "page_numbers": [3, 4],
            "cells": cells,
        }]
        result = analyze_document_structure(job_id=15, azure_result=payload, normalized_candidates=[])
        disposition = next(row for row in result.ambiguous_content if row.content_id == "table:9")
        self.assertEqual(disposition.reason, "content_spans_multiple_section_ranges")
        self.assertEqual(disposition.pdf_page_indexes, [2, 3])
        self.assertEqual(disposition.azure_page_numbers, [3, 4])
        assigned_cells = {
            cell_id
            for section in result.sections
            for cell_id in section.table_cell_ids
        }
        self.assertEqual(
            assigned_cells,
            {"table:9:r0:c0", "table:9:r1:c0"},
        )

    def test_multi_page_item_is_ambiguous_when_any_section_range_overlaps_it(self):
        def section(section_id, start, end, order):
            return DocumentSection(
                section_id=section_id,
                job_id=15,
                raw_title=section_id,
                normalized_title=section_id,
                canonical_section_type="unknown_section",
                toc_entry_id=f"entry-{section_id}",
                section_order=order,
                pdf_page_start=start,
                pdf_page_end=end,
                azure_page_start=start + 1,
                azure_page_end=end + 1,
                confidence=0.8,
                grouping_method="test_overlap",
                requires_human_review=True,
            )

        sections = [
            section("broad-section", 1, 4, 0),
            section("nested-section", 3, 3, 1),
        ]
        inventory = [
            {
                "content_id": "table:overlap",
                "content_type": "table",
                "text": "",
                "pdf_page_indexes": [2, 3],
                "azure_page_numbers": [3, 4],
                "provenance": {"source": "test"},
            }
        ]

        unassigned, ambiguous, summary = group_document_content(
            sections,
            inventory,
            [],
            toc_page_indexes=[],
        )

        self.assertEqual(unassigned, [])
        self.assertEqual(sections[0].table_ids, [])
        self.assertEqual(sections[1].table_ids, [])
        self.assertEqual(len(ambiguous), 1)
        self.assertEqual(
            ambiguous[0].reason,
            "content_spans_multiple_section_ranges",
        )
        self.assertEqual(
            ambiguous[0].candidate_section_ids,
            ["broad-section", "nested-section"],
        )
        self.assertTrue(summary["content_conservation_passed"])

    def test_same_page_item_stays_ambiguous_when_any_boundary_anchor_is_missing(self):
        sections = [
            DocumentSection(
                section_id="anchored-section",
                job_id=15,
                raw_title="Anchored",
                normalized_title="anchored",
                canonical_section_type="unknown_section",
                toc_entry_id="entry-anchored",
                section_order=0,
                pdf_page_start=2,
                pdf_page_end=2,
                azure_page_start=3,
                azure_page_end=3,
                heading_anchor_page=2,
                heading_anchor_id="anchor-1",
                confidence=0.8,
                grouping_method="test_overlap",
                requires_human_review=True,
            ),
            DocumentSection(
                section_id="missing-boundary-section",
                job_id=15,
                raw_title="Missing Boundary",
                normalized_title="missing boundary",
                canonical_section_type="unknown_section",
                toc_entry_id="entry-missing",
                section_order=1,
                pdf_page_start=2,
                pdf_page_end=2,
                azure_page_start=3,
                azure_page_end=3,
                confidence=0.6,
                grouping_method="test_overlap",
                requires_human_review=True,
            ),
        ]
        anchor = HeadingAnchor(
            anchor_id="anchor-1",
            toc_entry_id="entry-anchored",
            source_content_id="page:3:line:0",
            toc_title="Anchored",
            matched_heading="ANCHORED",
            pdf_page_index=2,
            azure_page_number=3,
            match_score=0.95,
            match_method="exact_normalized_title",
            text_evidence="ANCHORED",
            bounding_evidence=[
                {
                    "page_number": 3,
                    "polygon": [{"x": 1, "y": 100}],
                }
            ],
        )
        inventory = [
            {
                "content_id": "page:3:line:9",
                "content_type": "text_block",
                "text": "Unresolved content",
                "pdf_page_indexes": [2],
                "azure_page_numbers": [3],
                "top": 600,
                "provenance": {"source": "test"},
            }
        ]

        unassigned, ambiguous, summary = group_document_content(
            sections,
            inventory,
            [anchor],
            toc_page_indexes=[],
        )

        self.assertEqual(unassigned, [])
        self.assertEqual(sections[0].text_block_ids, [])
        self.assertEqual(sections[1].text_block_ids, [])
        self.assertEqual(len(ambiguous), 1)
        self.assertEqual(
            ambiguous[0].reason,
            "overlapping_section_ranges_without_decisive_heading_boundary",
        )
        self.assertEqual(
            ambiguous[0].candidate_section_ids,
            ["anchored-section", "missing-boundary-section"],
        )
        self.assertTrue(summary["content_conservation_passed"])

    def test_every_section_reference_resolves_to_bounded_content_evidence(self):
        result = analyze_document_structure(
            job_id=16,
            azure_result=load_fixture("fixture_i_notes_spanning_pages.json"),
            normalized_candidates=[],
        )
        evidence_by_id = {
            item.content_id: item
            for item in result.content_evidence
        }
        references = {
            reference
            for section in result.sections
            for reference in [
                *section.text_block_ids,
                *section.heading_ids,
                *section.table_ids,
                *section.table_cell_ids,
                *section.extracted_row_ids,
            ]
        }
        references.update(
            item.content_id
            for item in [
                *result.unassigned_content,
                *result.ambiguous_content,
            ]
        )

        self.assertEqual(
            result.safety_summary["content_evidence_count"],
            len(result.content_evidence),
        )
        self.assertTrue(references.issubset(evidence_by_id))

    def test_duplicate_printed_labels_do_not_project_ranges_across_regimes(self):
        entries = []
        anchors = []
        for index, (printed_start, printed_end, pdf_page_index) in enumerate(
            [(1, 2, 2), (2, 2, 3), (1, 2, 8), (2, 2, 9)],
            start=1,
        ):
            entry_id = f"entry-{index}"
            entries.append(
                TocEntry(
                    entry_id=entry_id,
                    raw_title=f"Section {index}",
                    normalized_title=f"section {index}",
                    canonical_section_hint="unknown_section",
                    printed_page_start=printed_start,
                    printed_page_end=printed_end,
                    source_pdf_page_index=0,
                    source_text=f"Section {index} {printed_start}",
                    confidence=0.9,
                    range_method="explicit_range",
                )
            )
            anchors.append(
                HeadingAnchor(
                    anchor_id=f"anchor-{index}",
                    toc_entry_id=entry_id,
                    source_content_id=f"heading-{index}",
                    toc_title=f"Section {index}",
                    matched_heading=f"Section {index}",
                    pdf_page_index=pdf_page_index,
                    azure_page_number=pdf_page_index + 1,
                    match_score=0.9,
                    match_method="exact_normalized_title",
                    text_evidence=f"Section {index}",
                )
            )
        alignment = align_document_pages(
            entries,
            anchors,
            azure_page_numbers=range(1, 13),
        )

        sections = build_document_sections(99, entries, anchors, alignment)

        self.assertEqual(alignment.mapping_method, "heading_anchor_piecewise")
        self.assertTrue(
            all(
                section.pdf_page_end is None or section.pdf_page_end < 8
                for section in sections[:2]
            )
        )
        self.assertIn(sections[0].pdf_page_end, {None, 2, 3})
        self.assertIn(sections[1].pdf_page_end, {None, 3})

    def test_same_page_anchor_ambiguity_is_propagated_to_section_review_metadata(self):
        entries = [
            TocEntry(
                entry_id="entry-1",
                raw_title="Directors Report",
                normalized_title="directors report",
                canonical_section_hint="directors_report",
                printed_page_start=1,
                printed_page_end=1,
                source_pdf_page_index=0,
                source_text="Directors Report 1",
                confidence=0.9,
                range_method="explicit_range",
            ),
            TocEntry(
                entry_id="entry-2",
                raw_title="Statement of Financial Position",
                normalized_title="statement of financial position",
                canonical_section_hint="statement_of_financial_position",
                printed_page_start=2,
                printed_page_end=2,
                source_pdf_page_index=0,
                source_text="Statement of Financial Position 2",
                confidence=0.9,
                range_method="explicit_range",
            ),
        ]
        anchors = [
            HeadingAnchor(
                anchor_id="anchor-1",
                toc_entry_id="entry-1",
                source_content_id="page:3:line:0",
                toc_title="Directors Report",
                matched_heading="DIRECTORS REPORT",
                pdf_page_index=2,
                azure_page_number=3,
                match_score=1.0,
                match_method="exact_normalized_title",
                text_evidence="DIRECTORS REPORT",
                warnings=["heading_anchor_same_page_near_tie"],
                alternative_candidates=[
                    {
                        "source_content_id": "page:3:line:5",
                        "matched_heading": "DIRECTORS REPORT",
                        "pdf_page_index": 2,
                        "azure_page_number": 3,
                        "match_score": 0.93,
                        "match_method": "exact_normalized_title",
                        "bounding_evidence": [
                            {
                                "page_number": 3,
                                "polygon": [{"x": 1, "y": 700}],
                            }
                        ],
                    }
                ],
            ),
            HeadingAnchor(
                anchor_id="anchor-2",
                toc_entry_id="entry-2",
                source_content_id="page:4:line:0",
                toc_title="Statement of Financial Position",
                matched_heading="STATEMENT OF FINANCIAL POSITION",
                pdf_page_index=3,
                azure_page_number=4,
                match_score=1.0,
                match_method="exact_normalized_title",
                text_evidence="STATEMENT OF FINANCIAL POSITION",
            ),
        ]
        alignment = align_document_pages(
            entries,
            anchors,
            azure_page_numbers=range(1, 5),
        )

        sections = build_document_sections(100, entries, anchors, alignment)

        self.assertFalse(alignment.requires_human_review)
        self.assertFalse(sections[0].requires_human_review)
        self.assertIn(
            "heading_anchor_same_page_near_tie",
            sections[0].warnings,
        )
        self.assertTrue(
            sections[0].provenance["heading_geometry_separate_from_page_range"]
        )


if __name__ == "__main__":
    unittest.main()
