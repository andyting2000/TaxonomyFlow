import unittest

from services.document_page_alignment import detect_heading_anchors
from services.toc_entry_extractor import extract_toc_entries


class HeadingAnchorQualityTests(unittest.TestCase):
    def test_short_fragments_are_recorded_as_rejected_not_trusted(self):
        entries = extract_toc_entries(
            [
                {"text": "Statement by Directors 5", "pdf_page_index": 0},
                {"text": "Statutory Declaration 6", "pdf_page_index": 0},
                {"text": "Notes to Financial Statements 15-22", "pdf_page_index": 0},
            ]
        )
        payload = {
            "pages": [
                {"page_number": 2, "height": 1000, "lines": [
                    {"content": "TO", "page_number": 2},
                    {"content": "SE", "page_number": 2},
                    {"content": "(e)", "page_number": 2},
                ]}
            ],
            "paragraphs": [],
        }

        anchors = detect_heading_anchors(entries, payload, toc_page_indexes=[0])

        self.assertEqual(len(anchors), 3)
        self.assertTrue(all(not anchor.trusted for anchor in anchors))
        self.assertTrue(all(anchor.rejection_reason for anchor in anchors))
        self.assertEqual({anchor.matched_heading for anchor in anchors}, {"TO", "SE", "(e)"})

    def test_exact_and_canonical_alias_headings_are_trusted(self):
        entries = extract_toc_entries(
            [
                {"text": "Statement of Financial Position 11", "pdf_page_index": 0},
                {"text": "Notes to Financial Statements 15-22", "pdf_page_index": 0},
            ]
        )
        payload = {
            "pages": [
                {"page_number": 13, "height": 1000, "lines": [
                    {"content": "BALANCE SHEET", "page_number": 13},
                ]},
                {"page_number": 17, "height": 1000, "lines": [
                    {"content": "NOTES TO FINANCIAL STATEMENTS", "page_number": 17},
                ]},
            ],
            "paragraphs": [],
        }

        anchors = detect_heading_anchors(entries, payload, toc_page_indexes=[0])

        self.assertTrue(all(anchor.trusted for anchor in anchors))
        self.assertEqual(
            {anchor.match_method for anchor in anchors},
            {"exact_normalized_title", "canonical_alias_exact"},
        )


if __name__ == "__main__":
    unittest.main()
