import unittest

from services.extraction_v2_schema import (
    ExtractionV2Candidate,
    candidate_from_text_line,
    normalize_row_type,
)


class ExtractionV2SchemaTests(unittest.TestCase):
    def test_numeric_fact_candidate_validates(self):
        candidate = ExtractionV2Candidate(
            case_id="001",
            source_pdf="benchmark_cases/001/a.pdf",
            page_number=1,
            extraction_method="native_text",
            row_type="numeric_fact",
            statement_section="Statement of Financial Position",
            label="Cash",
            value="1,234",
            warnings=None,
        )
        self.assertEqual(candidate.row_type, "numeric_fact")
        self.assertEqual(candidate.warnings, [])

    def test_comparative_numeric_fact_candidate_validates(self):
        candidate = ExtractionV2Candidate(
            case_id="001",
            source_pdf="benchmark_cases/001/a.pdf",
            page_number=1,
            extraction_method="native_table_heuristic",
            row_type="comparative_numeric_fact",
            statement_section="Statement of Financial Position",
            label="Cash",
            value="1,234",
            previous_value="1,000",
            current_year=2024,
            prior_year=2023,
            warnings=[],
        )
        self.assertEqual(candidate.row_type, "comparative_numeric_fact")
        self.assertEqual(candidate.current_year, 2024)
        self.assertEqual(candidate.prior_year, 2023)

    def test_long_paragraph_becomes_text_block_not_numeric_fact(self):
        line = (
            "The Company controls its credit risk by applying credit approvals and monitoring "
            "procedures for customers requiring credit over a certain amount during the "
            "financial year and does not treat this disclosure paragraph as a table row."
        )
        candidate = candidate_from_text_line(
            line,
            case_id="001",
            source_pdf="benchmark_cases/001/a.pdf",
            page_number=3,
        )
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.row_type, "text_block")
        self.assertIsNone(candidate.value)
        self.assertIn("text_block_not_numeric", candidate.warnings)

    def test_invalid_row_type_is_normalized_safely(self):
        self.assertEqual(normalize_row_type("not-a-row-type"), "unknown")
        candidate = ExtractionV2Candidate(
            case_id="001",
            source_pdf="a.pdf",
            page_number=1,
            extraction_method="not-real",
            row_type="not-real",
            statement_section=None,
        )
        self.assertEqual(candidate.row_type, "unknown")
        self.assertEqual(candidate.extraction_method, "unknown")

    def test_warnings_are_list_like_and_stable(self):
        candidate = ExtractionV2Candidate(
            case_id="001",
            source_pdf="a.pdf",
            page_number=1,
            extraction_method="native_text",
            row_type="numeric_fact",
            statement_section=None,
            label="Cash",
            value=None,
            warnings="manual_warning",
        )
        self.assertIn("manual_warning", candidate.warnings)
        self.assertIn("no_value_detected", candidate.warnings)


if __name__ == "__main__":
    unittest.main()
