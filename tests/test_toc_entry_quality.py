import unittest

from services.toc_entry_extractor import extract_toc_entries


class TocEntryQualityTests(unittest.TestCase):
    def test_address_and_body_markers_are_not_toc_entries(self):
        entries = extract_toc_entries(
            [
                {"text": "INDEX", "pdf_page_index": 0},
                {"text": "Directors Report 1-4", "pdf_page_index": 0},
                {"text": "Notes to Financial Statements 5-8", "pdf_page_index": 0},
                {"text": "Company body begins here.", "pdf_page_index": 0},
                {"text": "No. 1, Persiaran Jalil 2", "pdf_page_index": 0},
                {"text": "COMPANY NO. 1234", "pdf_page_index": 0},
                {"text": "(e) 5", "pdf_page_index": 0},
            ]
        )

        self.assertEqual([entry.raw_title for entry in entries], [
            "Directors Report",
            "Notes to Financial Statements",
        ])


if __name__ == "__main__":
    unittest.main()
