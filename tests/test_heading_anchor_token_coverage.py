import unittest

from services.document_page_alignment import evaluate_heading_anchor_match
from services.toc_entry_extractor import extract_toc_entries


class HeadingAnchorTokenCoverageTests(unittest.TestCase):
    def setUp(self):
        self.entry = extract_toc_entries(
            [
                {
                    "text": "Statement of Financial Position 11",
                    "pdf_page_index": 0,
                }
            ]
        )[0]

    def test_exact_heading_has_complete_bidirectional_coverage(self):
        match = evaluate_heading_anchor_match(
            self.entry,
            "STATEMENT OF FINANCIAL POSITION",
        )

        self.assertTrue(match.trusted)
        self.assertEqual(match.match_tier, "A")
        self.assertEqual(match.expected_token_coverage, 1.0)
        self.assertEqual(match.candidate_token_coverage, 1.0)

    def test_ocr_typo_can_pass_strong_fuzzy_with_substantial_coverage(self):
        match = evaluate_heading_anchor_match(
            self.entry,
            "STATEMENT OF FINANCIAL POSITLON",
        )

        self.assertTrue(match.trusted)
        self.assertEqual(match.match_tier, "C")
        self.assertGreaterEqual(match.expected_token_coverage, 0.6)
        self.assertGreaterEqual(match.length_ratio, 0.9)

    def test_single_generic_word_cannot_anchor_long_expected_heading(self):
        match = evaluate_heading_anchor_match(self.entry, "POSITION")

        self.assertFalse(match.trusted)
        self.assertEqual(match.rejection_reason, "insufficient_containment_coverage")
        self.assertLess(match.expected_token_coverage, 0.5)


if __name__ == "__main__":
    unittest.main()
