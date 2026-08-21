import json
from pathlib import Path
import unittest

from services.section_title_normalization import normalize_section_title
from services.toc_aware_document_structure import build_page_text_evidence
from services.toc_entry_extractor import extract_toc_entries, infer_toc_page_ranges


FIXTURES = Path(__file__).parent / "fixtures" / "toc_aware"


def fixture_lines(name, page_indexes):
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return [
        line
        for page in build_page_text_evidence(payload)
        if page["pdf_page_index"] in page_indexes
        for line in page["lines"]
    ]


class TocEntryExtractorTests(unittest.TestCase):
    def test_explicit_range_and_unicode_dashes_are_parsed_with_raw_text(self):
        entries = extract_toc_entries(
            [
                {"text": "Directors' Report .... 1 - 4", "pdf_page_index": 0},
                {"text": "Independent Auditors' Report .... 7 \u2013 10", "pdf_page_index": 0},
                {"text": "Notes to the Accounts .... 11 \u2014 14", "pdf_page_index": 0},
            ]
        )
        self.assertEqual([(row.printed_page_start, row.printed_page_end) for row in entries], [(1, 4), (7, 10), (11, 14)])
        self.assertEqual(entries[1].source_text, "Independent Auditors' Report .... 7 \u2013 10")
        self.assertEqual(entries[0].range_method, "explicit_range")

    def test_start_only_ranges_and_duplicate_starts_are_inferred_without_erasing_overlap(self):
        parsed = extract_toc_entries(
            [
                {"text": "Statement by Directors 5", "pdf_page_index": 0},
                {"text": "Statutory Declaration 5", "pdf_page_index": 0},
                {"text": "Statement of Financial Position 6", "pdf_page_index": 0},
            ]
        )
        inferred = infer_toc_page_ranges(parsed, final_printed_page=8)
        self.assertEqual([(row.printed_page_start, row.printed_page_end) for row in inferred], [(5, 5), (5, 5), (6, 8)])
        self.assertEqual(inferred[0].range_method, "inferred_shared_start")
        self.assertIn("duplicate_start_page", inferred[1].parse_warnings)

    def test_non_monotonic_starts_use_only_the_immediate_next_entry(self):
        parsed = extract_toc_entries(
            [
                {"text": "Directors Report 1", "pdf_page_index": 0},
                {
                    "text": "Statement of Financial Position 10",
                    "pdf_page_index": 0,
                },
                {"text": "Notes to Accounts 5", "pdf_page_index": 0},
            ]
        )

        inferred = infer_toc_page_ranges(parsed, final_printed_page=20)

        self.assertEqual(inferred[0].printed_page_end, 9)
        self.assertEqual(inferred[0].range_method, "inferred_from_next_start")
        self.assertIsNone(inferred[1].printed_page_end)
        self.assertTrue(
            any(
                token in warning
                for warning in inferred[1].parse_warnings
                for token in ("reset", "decrease", "non_monotonic")
            )
        )
        self.assertEqual(inferred[2].printed_page_end, 20)

    def test_numbered_layout_removes_numbering_from_title_but_preserves_source(self):
        entries = extract_toc_entries(fixture_lines("fixture_c_numbered_index.json", {0}))
        self.assertEqual(entries[0].raw_title, "DIRECTORS' REPORT")
        self.assertTrue(entries[0].source_text.startswith("1."))
        self.assertIn("leading_numbering_removed", entries[0].parse_warnings)

    def test_page_number_column_label_is_not_part_of_the_title(self):
        entry = extract_toc_entries(
            [
                {
                    "text": "Directors Report Page No. 1",
                    "pdf_page_index": 0,
                }
            ]
        )[0]

        self.assertEqual(entry.raw_title, "Directors Report")
        self.assertEqual(entry.printed_page_start, 1)
        self.assertEqual(entry.canonical_section_hint, "directors_report")

    def test_roman_to_arabic_change_is_not_treated_as_a_shared_page(self):
        parsed = extract_toc_entries(
            [
                {"text": "Company Information i", "pdf_page_index": 0},
                {"text": "Directors Report 1", "pdf_page_index": 0},
                {
                    "text": "Statement of Financial Position 2",
                    "pdf_page_index": 0,
                },
            ]
        )

        inferred = infer_toc_page_ranges(
            parsed,
            final_printed_page=3,
            final_numbering_scheme="arabic",
        )

        self.assertIsNone(inferred[0].printed_page_end)
        self.assertIn(
            "printed_page_numbering_regime_change",
            inferred[0].parse_warnings,
        )
        self.assertEqual(inferred[1].printed_page_end, 1)
        self.assertEqual(inferred[2].printed_page_end, 3)

    def test_page_evidence_preserves_numeric_source_order_after_nine_rows(self):
        source_lines = [
            {"content": "INDEX", "page_number": 1},
            *[
                {
                    "content": f"{number}. Section {number} {number}",
                    "page_number": 1,
                }
                for number in range(1, 13)
            ],
        ]
        payload = {
            "pages": [
                {
                    "page_number": 1,
                    "height": 1000,
                    "lines": source_lines,
                }
            ]
        }
        evidence = build_page_text_evidence(payload)
        entries = extract_toc_entries(evidence[0]["lines"])

        self.assertEqual(
            [entry.printed_page_start for entry in entries],
            list(range(1, 13)),
        )

    def test_malformed_noisy_entry_without_page_reference_is_rejected(self):
        entries = extract_toc_entries(fixture_lines("fixture_g_ocr_noisy.json", {0}))
        self.assertFalse(any("Cash Flows" in row.raw_title for row in entries))

    def test_roman_page_parser_does_not_consume_a_title_word_suffix(self):
        entries = extract_toc_entries(
            [{"text": "Risk Appendix", "pdf_page_index": 0}]
        )

        self.assertEqual(entries, [])

    def test_alias_normalization_keeps_income_statement_distinct_and_unknown_unforced(self):
        self.assertEqual(
            normalize_section_title("Balance Sheet").canonical_section_type,
            "statement_of_financial_position",
        )
        self.assertEqual(
            normalize_section_title("Income Statement").canonical_section_type,
            "income_statement",
        )
        self.assertEqual(
            normalize_section_title("Statement of Profit or Loss and Other Comprehensive Income").canonical_section_type,
            "statement_of_comprehensive_income",
        )
        self.assertEqual(
            normalize_section_title("Community Projects").canonical_section_type,
            "unknown_section",
        )


if __name__ == "__main__":
    unittest.main()
