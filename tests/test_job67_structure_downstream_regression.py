from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from config import settings
from schemas import DocumentStructureResult, HeadingAnchor, TocEntry
from services.document_page_alignment import align_document_pages
from services.document_section_grouper import (
    build_content_evidence,
    build_document_sections,
    group_document_content,
    summarize_section_range_topology,
    validate_section_page_mapping_consistency,
)
from services.toc_aware_document_structure import FEATURE_VERSION
from services.toc_aware_template_classification import (
    analyze_template_classification,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "toc_aware"
    / "fixture_m_job67_range_conflicts.json"
)


def _structure():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    entries = [TocEntry.model_validate(row) for row in payload["toc_entries"]]
    anchors = [HeadingAnchor.model_validate(row) for row in payload["heading_anchors"]]
    alignment = align_document_pages(
        entries,
        anchors,
        azure_page_numbers=payload["azure_page_numbers"],
    )
    sections = build_document_sections(67, entries, anchors, alignment)
    consistency = validate_section_page_mapping_consistency(sections, alignment)
    unassigned, ambiguous, conservation = group_document_content(
        sections,
        payload["content_inventory"],
        anchors,
        toc_page_indexes=payload["toc_page_indexes"],
    )
    return DocumentStructureResult(
        job_id=67,
        document_id="filing-job-67-regression",
        feature_version=FEATURE_VERSION,
        toc_detected=True,
        toc_page_indexes=payload["toc_page_indexes"],
        toc_confidence=1.0,
        page_mapping_confidence=alignment.confidence,
        page_alignment_summary=alignment.to_dict(),
        section_count=len(sections),
        toc_entries=entries,
        heading_anchors=anchors,
        page_mappings=list(alignment.page_mappings),
        sections=sections,
        content_evidence=build_content_evidence(payload["content_inventory"]),
        unassigned_content=unassigned,
        ambiguous_content=ambiguous,
        safety_summary={
            **conservation,
            **consistency,
            **summarize_section_range_topology(sections),
        },
        generated_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
    )


class Job67StructureDownstreamRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_19b_preserves_narrative_and_notes_parent_child_contracts(self):
        structure = _structure()
        with patch.object(
            settings,
            "toc_aware_template_classification_live_llm_enabled",
            False,
        ):
            result = await analyze_template_classification(
                job_id=67,
                filing_id=67,
                structure=structure,
            )

        outcomes = {outcome.section_id: outcome for outcome in result.outcomes}
        directors = next(
            section
            for section in structure.sections
            if section.canonical_section_type == "directors_report"
        )
        auditors = next(
            section
            for section in structure.sections
            if section.canonical_section_type == "independent_auditors_report"
        )
        notes = next(
            section
            for section in structure.sections
            if section.canonical_section_type == "notes_to_financial_statements"
        )

        self.assertEqual(outcomes[directors.section_id].outcome.value, "narrative_only")
        self.assertEqual(outcomes[auditors.section_id].outcome.value, "narrative_only")
        notes_container = next(
            outcome
            for outcome in result.outcomes
            if outcome.parent_section_id == notes.section_id
            and outcome.outcome.value == "container_only"
        )
        self.assertEqual(notes_container.raw_title, notes.raw_title)
        self.assertTrue(result.notes_conservation.passed)
        self.assertEqual(result.notes_conservation.dropped_items, 0)
        self.assertTrue(result.note_subsections)
        self.assertTrue(
            all(
                notes.pdf_page_start
                <= subsection.pdf_page_start
                <= subsection.pdf_page_end
                <= notes.pdf_page_end
                for subsection in result.note_subsections
            )
        )
        self.assertTrue(
            all(subsection.pdf_page_start != 0 for subsection in result.note_subsections)
        )
        self.assertEqual(structure.safety_summary["section_page_overlap_count"], 0)
        self.assertEqual(structure.safety_summary["dropped_content_count"], 0)


if __name__ == "__main__":
    unittest.main()
