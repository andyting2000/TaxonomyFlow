from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import unittest

from schemas import HeadingAnchor, TocEntry
from services.document_page_alignment import align_document_pages
from services.document_section_grouper import (
    build_document_sections,
    group_document_content,
    validate_section_page_mapping_consistency,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "toc_aware"
    / "fixture_m_job67_range_conflicts.json"
)
TARGET_RANGES = {
    "directors_report": (2, 5),
    "independent_auditors_report": (8, 11),
    "notes_to_financial_statements": (16, 23),
}


def _case():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    entries = [TocEntry.model_validate(row) for row in payload["toc_entries"]]
    anchors = [HeadingAnchor.model_validate(row) for row in payload["heading_anchors"]]
    alignment = align_document_pages(
        entries,
        anchors,
        azure_page_numbers=payload["azure_page_numbers"],
    )
    return payload, entries, anchors, alignment


class DocumentSectionRangeAuthorityJob67Tests(unittest.TestCase):
    def test_robust_regime_keeps_authoritative_multipage_ranges_despite_continuation_header_ties(self):
        _payload, entries, anchors, alignment = _case()

        self.assertEqual(alignment.dominant_offsets, (1,))
        self.assertEqual(alignment.competing_high_quality_offset_count, 0)
        self.assertFalse(alignment.requires_human_review)
        sections = build_document_sections(67, entries, anchors, alignment)
        metrics = validate_section_page_mapping_consistency(sections, alignment)
        by_type = {section.canonical_section_type: section for section in sections}

        self.assertEqual(
            {key: (by_type[key].pdf_page_start, by_type[key].pdf_page_end) for key in TARGET_RANGES},
            TARGET_RANGES,
        )
        self.assertEqual(metrics["section_page_mapping_conflict_count"], 0)
        for section_type in TARGET_RANGES:
            section = by_type[section_type]
            self.assertTrue(section.provenance["authoritative_page_mapping"])
            self.assertEqual(section.heading_anchor_page, section.pdf_page_start)
            self.assertTrue(section.start_heading_bbox)
            self.assertIsNotNone(section.start_heading_offset)
            self.assertEqual(section.range_consistency["status"], "validated")
            self.assertFalse(section.requires_human_review)

    def test_first_page_geometry_never_collapses_multipage_ownership(self):
        _payload, entries, anchors, alignment = _case()
        sections = build_document_sections(67, entries, anchors, alignment)
        by_type = {section.canonical_section_type: section for section in sections}

        for section_type, expected in TARGET_RANGES.items():
            section = by_type[section_type]
            self.assertEqual(section.heading_anchor_page, expected[0])
            self.assertEqual((section.pdf_page_start, section.pdf_page_end), expected)
            self.assertGreater(section.pdf_page_end, section.pdf_page_start)

    def test_consistency_validator_exposes_dimensions_and_safely_reconciles(self):
        _payload, entries, anchors, alignment = _case()
        sections = build_document_sections(67, entries, anchors, alignment)
        notes = next(
            section
            for section in sections
            if section.canonical_section_type == "notes_to_financial_statements"
        )
        notes.pdf_page_start = 16
        notes.pdf_page_end = 16
        notes.azure_page_start = 17
        notes.azure_page_end = 17

        metrics = validate_section_page_mapping_consistency(sections, alignment)

        self.assertEqual((notes.pdf_page_start, notes.pdf_page_end), (16, 23))
        self.assertEqual(
            notes.range_consistency["conflict_dimensions"],
            ["end_page_conflict", "range_collapsed"],
        )
        self.assertEqual(notes.range_consistency["status"], "reconciled")
        self.assertEqual(notes.range_consistency["expected_pdf_range"], [16, 23])
        self.assertEqual(notes.range_consistency["observed_pdf_range"], [16, 16])
        self.assertEqual(metrics["section_page_mapping_conflicts_reconciled_count"], 1)

    def test_unreliable_projection_is_not_forced(self):
        _payload, entries, anchors, alignment = _case()
        unsafe = replace(
            alignment,
            confidence=0.60,
            requires_human_review=True,
            warnings=("page_alignment_ambiguous", "inconsistent_heading_anchors"),
            regimes=(),
        )

        sections = build_document_sections(67, entries, anchors, unsafe)
        metrics = validate_section_page_mapping_consistency(sections, unsafe)
        notes = next(
            section
            for section in sections
            if section.canonical_section_type == "notes_to_financial_statements"
        )

        self.assertEqual((notes.pdf_page_start, notes.pdf_page_end), (None, None))
        self.assertEqual(notes.range_consistency["status"], "unresolved")
        self.assertFalse(notes.range_consistency["safe_reconciliation"])
        self.assertGreater(metrics["section_page_mapping_conflict_count"], 0)

    def test_corrected_ranges_assign_all_target_pages_and_conserve_content(self):
        payload, entries, anchors, alignment = _case()
        sections = build_document_sections(67, entries, anchors, alignment)
        validate_section_page_mapping_consistency(sections, alignment)
        unassigned, ambiguous, summary = group_document_content(
            sections,
            payload["content_inventory"],
            anchors,
            toc_page_indexes=payload["toc_page_indexes"],
        )
        by_type = {section.canonical_section_type: section for section in sections}
        notes = by_type["notes_to_financial_statements"]
        assigned_notes = {
            *notes.heading_ids,
            *notes.text_block_ids,
        }

        self.assertEqual(ambiguous, [])
        self.assertEqual(summary["dropped_content_count"], 0)
        self.assertEqual(summary["assigned_content_count"], 16)
        self.assertEqual({item.reason for item in unassigned}, {"toc_page_excluded", "outside_reliable_section_ranges"})
        self.assertNotIn("cover", assigned_notes)
        self.assertNotIn("toc", assigned_notes)
        self.assertEqual(len(assigned_notes), 8)
        self.assertEqual(notes.candidate_note_heading_ids, ["notes-1", "notes-3"])


if __name__ == "__main__":
    unittest.main()
