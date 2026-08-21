import unittest

from services.extraction_v2_pipeline import (
    build_report,
    detect_statement_section,
    extract_candidates_from_lines,
    parse_v2_amount,
)


def parse_lines(lines, **kwargs):
    candidates, _state, _warnings = extract_candidates_from_lines(
        lines,
        case_id=kwargs.get("case_id", "case-001"),
        source_pdf=kwargs.get("source_pdf", "benchmark_cases/case/source.pdf"),
        page_number=kwargs.get("page_number", 1),
        initial_section=kwargs.get("initial_section"),
    )
    return candidates


class ExtractionV2NumericTextBlockTests(unittest.TestCase):
    def test_label_plus_current_value(self):
        candidates = parse_lines(["Statement of Profit or Loss", "Revenue 300,000"])
        numeric = [candidate for candidate in candidates if candidate.row_type == "numeric_fact"]
        self.assertEqual(len(numeric), 1)
        self.assertEqual(numeric[0].label, "Revenue")
        self.assertEqual(numeric[0].value, "300000")
        self.assertEqual(numeric[0].statement_section, "Statement of Profit or Loss")

    def test_label_plus_current_and_prior_value(self):
        candidates = parse_lines(["2025 2024", "Trade receivables 1,234,567 1,000,000"])
        comparative = [candidate for candidate in candidates if candidate.row_type == "comparative_numeric_fact"]
        self.assertEqual(len(comparative), 1)
        self.assertEqual(comparative[0].label, "Trade receivables")
        self.assertEqual(comparative[0].value, "1234567")
        self.assertEqual(comparative[0].previous_value, "1000000")
        self.assertEqual(comparative[0].current_year, 2025)
        self.assertEqual(comparative[0].prior_year, 2024)

    def test_parentheses_negative_values(self):
        candidates = parse_lines(["Accumulated depreciation (25,000) (18,000)"])
        candidate = next(item for item in candidates if item.row_type == "comparative_numeric_fact")
        self.assertEqual(candidate.value, "-25000")
        self.assertEqual(candidate.previous_value, "-18000")
        self.assertNotIn("possible_sign_issue", candidate.warnings)

    def test_minus_sign_negative_value(self):
        self.assertEqual(parse_v2_amount("-1,234"), "-1234")
        candidates = parse_lines(["Administrative expenses -12,345"])
        candidate = next(item for item in candidates if item.row_type == "numeric_fact")
        self.assertEqual(candidate.value, "-12345")

    def test_rm_and_comma_amount_parsing(self):
        self.assertEqual(parse_v2_amount("RM 1,234"), "1234")
        candidates = parse_lines(["Cash and bank balances RM 15,000"])
        candidate = next(item for item in candidates if item.row_type == "numeric_fact")
        self.assertEqual(candidate.value, "15000")

    def test_dash_and_zero_handling(self):
        self.assertEqual(parse_v2_amount("-"), "0")
        self.assertEqual(parse_v2_amount("0"), "0")
        candidates = parse_lines(["Deferred tax assets -"])
        candidate = next(item for item in candidates if item.row_type in {"numeric_fact", "subtotal_or_total"})
        self.assertEqual(candidate.value, "0")
        self.assertIn("low_confidence_table_row", candidate.warnings)

    def test_long_paragraph_becomes_text_block_not_numeric(self):
        paragraph = (
            "The company manages its financial risk through credit approvals, regular monitoring "
            "of outstanding balances, and review of market conditions by management throughout the "
            "financial year. This disclosure is narrative and should not become a financial table row."
        )
        candidates = parse_lines(["Notes to the Financial Statements", paragraph])
        text_blocks = [candidate for candidate in candidates if candidate.row_type == "text_block"]
        self.assertEqual(len(text_blocks), 1)
        self.assertIsNone(text_blocks[0].value)
        self.assertIn("text_block_not_numeric", text_blocks[0].warnings)
        self.assertFalse([candidate for candidate in candidates if candidate.row_type == "numeric_fact"])

    def test_heading_remains_heading_not_text_block(self):
        candidates = parse_lines(["STATEMENT OF FINANCIAL POSITION"])
        self.assertEqual(candidates[0].row_type, "heading")
        self.assertEqual(candidates[0].statement_section, "Statement of Financial Position")

    def test_directors_report_paragraph_grouping(self):
        lines = [
            "Directors' Report",
            "The directors hereby present their report and audited financial statements",
            "for the financial year ended 31 December 2025.",
            "The principal activity of the company is trading and related services.",
        ]
        candidates = parse_lines(lines)
        text_blocks = [candidate for candidate in candidates if candidate.row_type == "text_block"]
        self.assertEqual(len(text_blocks), 1)
        self.assertEqual(text_blocks[0].statement_section, "Directors Report")
        self.assertIn("principal activity", text_blocks[0].text.lower())

    def test_notes_accounting_policy_paragraph_grouping(self):
        lines = [
            "Notes to the Financial Statements",
            "Basis of Preparation",
            "The financial statements have been prepared in accordance with the applicable",
            "financial reporting framework and under the historical cost convention.",
            "The accounting policies are consistently applied unless otherwise stated.",
        ]
        candidates = parse_lines(lines)
        text_blocks = [candidate for candidate in candidates if candidate.row_type == "text_block"]
        self.assertEqual(len(text_blocks), 1)
        self.assertEqual(text_blocks[0].statement_section, "Notes to the Financial Statements")

    def test_section_detection_for_common_sections(self):
        self.assertEqual(detect_statement_section("Statement of Financial Position"), "Statement of Financial Position")
        self.assertEqual(detect_statement_section("Statement of Profit or Loss"), "Statement of Profit or Loss")
        self.assertEqual(detect_statement_section("Notes to the Financial Statements"), "Notes to the Financial Statements")

    def test_prior_year_confusion_warning_when_headers_ambiguous(self):
        candidates = parse_lines(["Cash and bank balances 15,000 12,000"])
        candidate = next(item for item in candidates if item.row_type == "comparative_numeric_fact")
        self.assertIn("possible_prior_year_confusion", candidate.warnings)

    def test_suspicious_sign_warning_where_appropriate(self):
        candidates = parse_lines(["Cash and bank balances (15,000)"])
        candidate = next(item for item in candidates if item.row_type == "numeric_fact")
        self.assertIn("possible_sign_issue", candidate.warnings)

    def test_report_summary_counts_numeric_and_text_blocks(self):
        candidates = parse_lines(
            [
                "Statement of Profit or Loss",
                "Revenue 300,000",
                "Notes to the Financial Statements",
                "The company has material accounting policy disclosures that are grouped into",
                "one paragraph for later mapping to text-block concepts in benchmark analysis.",
            ]
        )
        case_report = {
            "case_id": "case-001",
            "case_dir": "benchmark_cases/case-001",
            "source_pdf": "source.pdf",
            "reference_available": True,
            "reference_path": "source.xml",
            "reference_type": "xml",
            "status": "ok",
            "stages": [],
            "pages_analyzed": 1,
            "candidate_count": len(candidates),
            "row_type_counts": {},
            "warning_counts": {},
            "warnings": [],
            "candidates": [candidate.to_dict() for candidate in candidates],
        }
        report = build_report([case_report], cases_dir="benchmark_cases", output_json="report.json", limit_pages=None, use_openai=False)
        self.assertGreater(report["aggregate_metrics"]["numeric_fact_count"], 0)
        self.assertGreater(report["aggregate_metrics"]["text_block_count"], 0)


if __name__ == "__main__":
    unittest.main()
