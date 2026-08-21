import unittest
from decimal import Decimal

from services.shadow_text_table_extractor import (
    classify_text_line,
    detect_suspicious_sign,
    mark_duplicate_warnings,
    parse_amount,
    parse_table_row,
)


class ShadowTextTableExtractionTests(unittest.TestCase):
    def test_amount_parsing(self):
        self.assertEqual(parse_amount("1,234"), Decimal("1234"))
        self.assertEqual(parse_amount("(1,234)"), Decimal("-1234"))
        self.assertEqual(parse_amount("-1,234"), Decimal("-1234"))
        self.assertEqual(parse_amount("RM 1,234"), Decimal("1234"))

    def test_auto_slash_and_punctuation_robustness(self):
        candidate = parse_table_row("Profit / (loss) before taxation RM (1,234)")
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.label, "Profit / (loss) before taxation")
        self.assertEqual(candidate.value, "RM (1,234)")

    def test_table_row_current_value(self):
        candidate = parse_table_row("Cash and bank balances 1,234", page_number=2)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.label, "Cash and bank balances")
        self.assertEqual(candidate.value, "1,234")
        self.assertIsNone(candidate.previous_value)
        self.assertEqual(candidate.row_type, "numeric_fact")
        self.assertEqual(candidate.page_number, 2)

    def test_table_row_current_and_prior_value(self):
        candidate = parse_table_row("Revenue 12,345 10,000")
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.label, "Revenue")
        self.assertEqual(candidate.value, "12,345")
        self.assertEqual(candidate.previous_value, "10,000")
        self.assertIn("possible_prior_year_confusion", candidate.warnings)

    def test_long_paragraph_is_text_block(self):
        paragraph = (
            "The Company controls its credit risk by applying credit approvals and "
            "monitoring procedures for all customers requiring credit over a certain "
            "amount during the financial year."
        )
        candidate = classify_text_line(paragraph)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.row_type, "text_block")
        self.assertIn("text_block_not_numeric", candidate.warnings)

    def test_duplicate_warnings(self):
        first = parse_table_row("Cash and bank balances 1,234")
        second = parse_table_row("Cash and bank balances 1,234")
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        mark_duplicate_warnings([first, second])
        self.assertIn("possible_duplicate", first.warnings)
        self.assertIn("possible_duplicate", second.warnings)

    def test_suspicious_sign_detection(self):
        self.assertTrue(detect_suspicious_sign("Cash and bank balances", "(1,234)"))
        self.assertFalse(detect_suspicious_sign("Loss for the financial year", "(1,234)"))


if __name__ == "__main__":
    unittest.main()
