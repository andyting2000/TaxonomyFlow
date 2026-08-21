import json
from pathlib import Path
import unittest

from schemas import TocEntry
from services.document_page_alignment import (
    detect_heading_anchors,
    evaluate_heading_anchor_match,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "toc_aware"
    / "fixture_l_real_pdf_job66_anchor_range.json"
)


def entry(title, canonical, printed):
    return TocEntry(
        entry_id=f"entry-{printed}",
        raw_title=title,
        normalized_title=" ".join(title.lower().replace("'", "").split()),
        canonical_section_hint=canonical,
        printed_page_start=printed,
        printed_page_end=printed,
        source_pdf_page_index=1,
        source_text=f"{title} {printed}",
        confidence=0.9,
    )


class HeadingAnchorCandidateSelectionJob66Tests(unittest.TestCase):
    def test_core_tokens_reject_generic_partial_titles(self):
        directors = evaluate_heading_anchor_match(
            entry("Statement by Directors", "statement_by_directors", 5),
            "DIRECTORS",
        )
        notes = evaluate_heading_anchor_match(
            entry(
                "Notes to the Financial Statements",
                "notes_to_financial_statements",
                15,
            ),
            "FINANCIAL STATEMENTS",
        )
        self.assertFalse(directors.trusted)
        self.assertIn("statement", directors.missing_expected_core_tokens)
        self.assertFalse(notes.trusted)
        self.assertIn("notes", notes.missing_expected_core_tokens)

    def test_controlled_singular_plural_and_canonical_prefixes_are_trusted(self):
        cases = (
            (
                entry("Statement by Directors", "statement_by_directors", 5),
                "STATEMENT BY DIRECTOR PURSUANT TO",
            ),
            (
                entry("Statutory Declaration", "statutory_declaration", 6),
                "STATUTORY DECLARATION PURSUANT TO",
            ),
            (
                entry("Independent Auditors' Report", "independent_auditors_report", 7),
                "INDEPENDENT AUDITORS' REPORT TO THE MEMBERS OF BEZLIFE",
            ),
            (
                entry(
                    "Notes to the Financial Statements",
                    "notes_to_financial_statements",
                    15,
                ),
                "NOTES TO THE FINANCIAL STATEMENTS - 31 DECEMBER 2024",
            ),
        )
        for expected, observed in cases:
            with self.subTest(observed=observed):
                result = evaluate_heading_anchor_match(expected, observed)
                self.assertTrue(result.trusted)
                self.assertEqual(result.match_tier, "B")
                self.assertEqual(result.match_method, "canonical_title_prefix")
                self.assertEqual(result.expected_core_token_coverage, 1.0)

    def test_exact_and_prefix_body_candidates_beat_cover_and_generic_candidates(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        entries = [
            entry("Directors' Report", "directors_report", 1),
            entry("Statement by Directors", "statement_by_directors", 5),
            entry("Statutory Declaration", "statutory_declaration", 6),
            entry("Independent Auditors' Report", "independent_auditors_report", 7),
            entry("Statement of Financial Position", "statement_of_financial_position", 11),
            entry("Statement of Comprehensive Income", "statement_of_comprehensive_income", 12),
            entry("Statement of Changes in Equity", "statement_of_changes_in_equity", 13),
            entry("Statement of Cash Flows", "statement_of_cash_flows", 14),
            entry(
                "Notes to the Financial Statements",
                "notes_to_financial_statements",
                15,
            ),
        ]

        anchors = detect_heading_anchors(entries, payload, toc_page_indexes=[1])
        selected = {
            anchor.toc_title: (anchor.matched_heading, anchor.pdf_page_index, anchor.match_tier)
            for anchor in anchors
        }
        self.assertEqual(selected["Directors' Report"], ("DIRECTORS' REPORT", 2, "A"))
        self.assertEqual(
            selected["Statement by Directors"],
            ("STATEMENT BY DIRECTOR PURSUANT TO", 6, "B"),
        )
        self.assertEqual(
            selected["Statutory Declaration"],
            ("STATUTORY DECLARATION PURSUANT TO", 7, "B"),
        )
        self.assertEqual(
            selected["Independent Auditors' Report"],
            ("INDEPENDENT AUDITORS' REPORT TO THE MEMBERS OF BEZLIFE", 8, "B"),
        )
        self.assertEqual(
            selected["Notes to the Financial Statements"],
            ("NOTES TO THE FINANCIAL STATEMENTS - 31 DECEMBER 2024", 16, "B"),
        )
        self.assertTrue(all(anchor.trusted for anchor in anchors))
        self.assertTrue(all("provisional_offset_match" in anchor.scoring_signals for anchor in anchors))


if __name__ == "__main__":
    unittest.main()
