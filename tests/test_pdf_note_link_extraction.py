import json
import unittest

from services.pdf_note_link_extraction import (
    build_note_link_report,
    extract_note_headings,
    extract_note_links_for_case,
    extract_note_references_from_label,
    extract_note_references_from_row,
    note_link_index,
)


def row(label, *, row_type="comparative_numeric_fact", section="Statement of Financial Position", note_values=None):
    return {
        "row_type": row_type,
        "statement_section": section,
        "label": label,
        "value": "100",
        "previous_value": "90" if row_type == "comparative_numeric_fact" else None,
        "current_year": 2024,
        "prior_year": 2023,
        "page_number": 5,
        "original_candidate_id": f"case_test:candidate:{label}",
        "provenance": {
            "row_index": 5,
            "ignored_note_values": note_values or [],
            "cells": [
                {"column_index": 0, "content": label},
                {"column_index": 1, "header": "Note", "content": (note_values or [""])[0]},
                {"column_index": 2, "content": "100"},
                {"column_index": 3, "content": "90"},
            ],
        },
    }


class PdfNoteLinkExtractionTests(unittest.TestCase):
    def test_extracts_note_references_from_label(self):
        self.assertEqual(extract_note_references_from_label("Cash and cash equivalents (NOTE 9)"), ["9"])
        self.assertEqual(extract_note_references_from_label("Tax expense - note 12"), ["12"])

    def test_extracts_note_references_from_provenance_note_column(self):
        notes, reasons = extract_note_references_from_row(row("Share capital", note_values=["4"]))

        self.assertEqual(notes, ["4"])
        self.assertIn("provenance_ignored_note_values", reasons)

    def test_extracts_note_headings_from_numbered_sections(self):
        rows = [
            {"row_type": "heading", "statement_section": "6. Amount Due To Director", "label": "6. AMOUNT DUE TO DIRECTOR", "page_number": 24},
            {"row_type": "heading", "statement_section": "Notes to the Financial Statements", "label": "NOTES TO THE FINANCIAL STATEMENTS - 31 DECEMBER 2024", "page_number": 17},
        ]
        headings = extract_note_headings(rows)

        self.assertEqual(headings["6"]["note_title"], "Amount Due To Director")
        self.assertNotIn("31", headings)

    def test_links_note_references_to_row_value_contexts(self):
        rows = [
            row("Share capital", note_values=["4"]),
            {"row_type": "heading", "statement_section": "4. Share Capital", "label": "4. SHARE CAPITAL", "page_number": 14},
        ]
        links = extract_note_links_for_case(sample_id="case_test", company_name="Example", rows=rows)

        self.assertEqual(len(links), 2)
        self.assertTrue(all(link["note_number"] == "4" for link in links))
        self.assertTrue(all(link["note_title"] == "Share Capital" for link in links))
        self.assertGreaterEqual(links[0]["note_link_confidence"], 0.8)

    def test_note_link_index_uses_row_value_key(self):
        rows = [row("Tax expense (Note 9)", row_type="numeric_fact", section="Statement of Comprehensive Income")]
        links = extract_note_links_for_case(sample_id="case_test", company_name="Example", rows=rows)
        index = note_link_index(links)

        self.assertIn(("case_test", links[0]["row_id"]), index)

    def test_note_link_report_serializes_to_json(self):
        report = build_note_link_report(dataset_dir="benchmark_mbrs_pairs", include_samples=["case_001"])

        encoded = json.dumps(report, default=str)
        self.assertIn("18E-B", encoded)
        self.assertGreater(report["summary"]["total_note_links"], 0)


if __name__ == "__main__":
    unittest.main()
