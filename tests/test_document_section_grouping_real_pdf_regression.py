import json
from pathlib import Path
import unittest

from services.toc_aware_document_structure import analyze_document_structure


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "toc_aware"
    / "fixture_k_real_pdf_job65_regression.json"
)


class DocumentSectionGroupingRealPdfRegressionTests(unittest.TestCase):
    def test_reliable_plus_one_ranges_assign_notes_and_conserve_content(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

        result = analyze_document_structure(
            job_id=65,
            azure_result=payload,
            normalized_candidates=[],
        )

        self.assertEqual(len(result.toc_entries), 9)
        self.assertEqual(result.page_alignment_summary["dominant_offsets"], [1])
        self.assertFalse(result.page_alignment_summary["requires_human_review"])
        notes = next(
            section
            for section in result.sections
            if section.canonical_section_type == "notes_to_financial_statements"
        )
        self.assertEqual((notes.pdf_page_start, notes.pdf_page_end), (16, 23))
        notes_evidence_count = sum(
            len(values)
            for values in (
                notes.text_block_ids,
                notes.heading_ids,
                notes.table_ids,
                notes.table_cell_ids,
                notes.extracted_row_ids,
            )
        )
        self.assertGreater(notes_evidence_count, 0)
        self.assertEqual(result.safety_summary["dropped_content_count"], 0)
        self.assertGreater(result.safety_summary["assignment_rate"], 0.55)
        self.assertLess(result.safety_summary["unassigned_rate"], 0.45)


if __name__ == "__main__":
    unittest.main()
