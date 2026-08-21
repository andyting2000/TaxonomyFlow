import json
from pathlib import Path
import unittest

from services.document_section_grouper import validate_section_page_mapping_consistency
from services.toc_aware_document_structure import analyze_document_structure


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "toc_aware"
    / "fixture_l_real_pdf_job66_anchor_range.json"
)


class DocumentSectionRangeAuthorityJob66Tests(unittest.TestCase):
    def test_mapped_toc_ranges_are_authoritative_over_cover_candidates(self):
        structure = analyze_document_structure(
            job_id=66,
            azure_result=json.loads(FIXTURE.read_text(encoding="utf-8")),
            normalized_candidates=[],
        )

        expected = {
            "directors_report": (2, 5),
            "statement_by_directors": (6, 6),
            "statutory_declaration": (7, 7),
            "independent_auditors_report": (8, 11),
            "statement_of_financial_position": (12, 12),
            "statement_of_comprehensive_income": (13, 13),
            "statement_of_changes_in_equity": (14, 14),
            "statement_of_cash_flows": (15, 15),
            "notes_to_financial_statements": (16, 23),
        }
        actual = {
            section.canonical_section_type: (
                section.pdf_page_start,
                section.pdf_page_end,
            )
            for section in structure.sections
        }
        self.assertEqual(actual, expected)
        self.assertEqual(structure.page_alignment_summary["dominant_offsets"], [1])
        self.assertGreaterEqual(structure.page_mapping_confidence, 0.90)
        self.assertFalse(structure.page_alignment_summary["requires_human_review"])
        self.assertEqual(
            structure.safety_summary["section_page_mapping_conflict_count"],
            0,
        )
        self.assertEqual(structure.safety_summary["dropped_content_count"], 0)
        self.assertGreater(
            structure.safety_summary["assignment_rate_excluding_toc"],
            0.75,
        )

    def test_consistency_validator_reconciles_a_contradictory_anchor_range(self):
        structure = analyze_document_structure(
            job_id=66,
            azure_result=json.loads(FIXTURE.read_text(encoding="utf-8")),
            normalized_candidates=[],
        )
        notes = next(
            section
            for section in structure.sections
            if section.canonical_section_type == "notes_to_financial_statements"
        )
        notes.pdf_page_start = 0
        notes.pdf_page_end = 0
        notes.azure_page_start = 1
        notes.azure_page_end = 1

        metrics = validate_section_page_mapping_consistency(
            structure.sections,
            type(
                "Alignment",
                (),
                {
                    "page_mappings": structure.page_mappings,
                    "confidence": structure.page_mapping_confidence,
                    "requires_human_review": structure.page_alignment_summary[
                        "requires_human_review"
                    ],
                },
            )(),
        )

        self.assertEqual((notes.pdf_page_start, notes.pdf_page_end), (16, 23))
        self.assertIn("section_range_conflicts_with_page_mapping", notes.warnings)
        self.assertEqual(metrics["section_page_mapping_conflicts_reconciled_count"], 1)
        self.assertEqual(metrics["section_page_mapping_conflict_count"], 0)


if __name__ == "__main__":
    unittest.main()
