import json
from pathlib import Path
import unittest

from services.toc_aware_document_structure import build_page_text_evidence
from services.toc_detection import detect_toc_pages


FIXTURES = Path(__file__).parent / "fixtures" / "toc_aware"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class TocDetectionTests(unittest.TestCase):
    def detect(self, name):
        return detect_toc_pages(build_page_text_evidence(load_fixture(name)))

    def test_index_and_contents_aliases_are_detected(self):
        index = self.detect("fixture_a_explicit_ranges.json")
        contents = self.detect("fixture_b_start_only.json")
        self.assertTrue(index.detected)
        self.assertTrue(contents.detected)
        self.assertIn("toc_heading", index.matched_signals)
        self.assertIn("toc_heading", contents.matched_signals)

    def test_toc_is_not_assumed_to_be_first_or_second_physical_page(self):
        result = self.detect("fixture_d_page_offset.json")
        self.assertTrue(result.detected)
        self.assertEqual(result.candidate_page_indexes, (1,))

    def test_multi_page_toc_includes_continuation_page(self):
        result = self.detect("fixture_h_multi_page_toc.json")
        self.assertEqual(result.candidate_page_indexes, (0, 1))
        self.assertGreaterEqual(result.confidence, 0.55)

    def test_weak_continuation_does_not_recursively_absorb_numeric_body_pages(self):
        pages = [
            {
                "pdf_page_index": 0,
                "azure_page_number": 1,
                "lines": [
                    {"text": "INDEX"},
                    {"text": "Directors Report 1"},
                    {"text": "Balance Sheet 2"},
                    {"text": "Notes to Accounts 3"},
                ],
            },
            {
                "pdf_page_index": 1,
                "azure_page_number": 2,
                "lines": [
                    {"text": "Accounting policies 4"},
                    {"text": "Other information 5"},
                    {"text": "Shareholding analysis 6"},
                ],
            },
        ]
        pages.extend(
            {
                "pdf_page_index": page_index,
                "azure_page_number": page_index + 1,
                "lines": [
                    {"text": "Cash and cash equivalents 100"},
                    {"text": "Trade receivables 200"},
                    {"text": "Total assets 300"},
                ],
            }
            for page_index in range(2, 6)
        )

        result = detect_toc_pages(pages)

        self.assertEqual(result.candidate_page_indexes, (0, 1))

    def test_three_page_toc_uses_bounded_strong_continuation(self):
        pages = [
            {
                "pdf_page_index": 0,
                "azure_page_number": 1,
                "lines": [
                    {"text": "CONTENTS"},
                    {"text": "Directors Report 1"},
                    {"text": "Balance Sheet 2"},
                    {"text": "Notes to Accounts 3"},
                ],
            },
            {
                "pdf_page_index": 1,
                "azure_page_number": 2,
                "lines": [
                    {"text": "Accounting policies 4"},
                    {"text": "Other information 5"},
                    {"text": "Shareholding analysis 6"},
                ],
            },
            {
                "pdf_page_index": 2,
                "azure_page_number": 3,
                "lines": [
                    {"text": "Independent Auditors Report 7"},
                    {"text": "Statement of Financial Position 8"},
                    {"text": "Statement of Cash Flows 9"},
                    {"text": "Notes to Financial Statements 10"},
                ],
            },
        ]

        result = detect_toc_pages(pages)

        self.assertEqual(result.candidate_page_indexes, (0, 1, 2))

    def test_numeric_statement_rows_are_not_a_toc_continuation(self):
        pages = [
            {
                "pdf_page_index": 0,
                "azure_page_number": 1,
                "lines": [
                    {"text": "INDEX"},
                    {"text": "Directors Report 1"},
                    {"text": "Balance Sheet 2"},
                    {"text": "Notes to Accounts 3"},
                ],
            },
            *[
                {
                    "pdf_page_index": page_index,
                    "azure_page_number": page_index + 1,
                    "lines": [
                        {"text": f"Line item {row} {row * 100}"}
                        for row in range(1, 6)
                    ],
                }
                for page_index in range(1, 5)
            ],
        ]

        result = detect_toc_pages(pages)

        self.assertEqual(result.candidate_page_indexes, (0,))

    def test_dotted_leader_rows_without_spaces_are_detected(self):
        pages = [
            {
                "pdf_page_index": 0,
                "azure_page_number": 1,
                "lines": [
                    {"text": "INDEX"},
                    {"text": "Directors Report........1"},
                    {
                        "text": (
                            "Statement of Financial "
                            "Position........2"
                        )
                    },
                    {"text": "Notes to Financial Statements........3"},
                ],
            }
        ]

        result = detect_toc_pages(pages)

        self.assertTrue(result.detected)
        self.assertEqual(result.candidate_page_indexes, (0,))
        self.assertEqual(result.page_evidence[0].entry_pattern_count, 3)

    def test_no_toc_fails_safely(self):
        result = self.detect("fixture_f_no_toc.json")
        self.assertFalse(result.detected)
        self.assertEqual(result.candidate_page_indexes, ())
        self.assertIn("toc_not_detected", result.warnings)


if __name__ == "__main__":
    unittest.main()
