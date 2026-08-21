import json
from pathlib import Path
import unittest

from services.toc_aware_document_structure import build_page_text_evidence
from services.toc_detection import detect_toc_pages
from services.toc_entry_extractor import extract_toc_entries


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "toc_aware"
    / "fixture_k_real_pdf_job65_regression.json"
)


class TocBlockBoundaryTests(unittest.TestCase):
    def test_index_block_stops_before_corporate_body_content(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        pages = build_page_text_evidence(payload)
        detection = detect_toc_pages(pages)
        lines = [
            line
            for page in pages
            if page["pdf_page_index"] in detection.candidate_page_indexes
            for line in page["lines"]
        ]

        entries = extract_toc_entries(lines)

        self.assertEqual(detection.candidate_page_indexes, (1,))
        self.assertEqual(len(entries), 9)
        self.assertEqual(
            entries[-1].canonical_section_hint,
            "notes_to_financial_statements",
        )
        rejected = {
            "CORPORATE INFORMATION",
            "BOARD OF DIRECTORS",
            "Maybank Islamic Berhad",
            "No. 1, Persiaran Jalil",
        }
        self.assertTrue(rejected.isdisjoint({entry.raw_title for entry in entries}))

    def test_later_high_density_body_page_is_not_a_second_toc_block(self):
        pages = [
            {
                "pdf_page_index": 1,
                "azure_page_number": 2,
                "lines": [
                    {"text": "INDEX"},
                    {"text": "Directors Report 1"},
                    {"text": "Statement of Financial Position 2"},
                    {"text": "Notes to Financial Statements 3"},
                ],
            },
            {
                "pdf_page_index": 8,
                "azure_page_number": 9,
                "lines": [
                    {"text": "CORPORATE INFORMATION 1"},
                    {"text": "Statement by Directors 5"},
                    {"text": "BOARD OF DIRECTORS 6"},
                    {"text": "Maybank Islamic Berhad 7"},
                    {"text": "REGISTERED OFFICE 8"},
                ],
            },
        ]

        result = detect_toc_pages(pages)

        self.assertEqual(result.candidate_page_indexes, (1,))


if __name__ == "__main__":
    unittest.main()
