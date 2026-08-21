import json
import unittest

from services.pdf_statement_row_order_alignment import (
    build_statement_row_order_alignment_report,
    build_statement_row_order_alignments,
    row_order_alignment_index,
    row_order_candidate_for_context,
)


def row(label, order, *, row_id=None, family="income_statement", section="profit_loss", role="component"):
    row_id = row_id or f"case_test:r{order}:current"
    return {
        "sample_id": "case_test",
        "row_id": row_id,
        "source_row_id": row_id.replace(":current", ""),
        "original_label": label,
        "normalized_label": label.lower(),
        "statement_family": family,
        "statement_title": "Statement of Comprehensive Income",
        "section_block": section,
        "row_role": role,
        "row_order": order,
        "is_main_statement": family != "notes",
        "is_notes_context": family == "notes",
    }


class PdfStatementRowOrderAlignmentTests(unittest.TestCase):
    def test_tax_after_profit_before_tax_gets_income_tax_candidate(self):
        contexts = [
            row("Loss before tax", 1, section="profit_loss_before_tax", role="subtotal"),
            row("Tax expense", 2, section="tax_expense"),
            row("Loss for the financial year", 3, section="profit_loss", role="total"),
        ]

        alignments = build_statement_row_order_alignments(contexts)
        by_row = row_order_alignment_index(alignments)
        tax_alignment = by_row[("case_test", "case_test:r2:current")]

        self.assertEqual(tax_alignment["expected_qname"], "ifrs-smes:IncomeTaxExpenseContinuingOperations")
        self.assertIn("tax_after_profit_loss_before_tax", tax_alignment["row_order_reasons"])
        self.assertEqual(tax_alignment["safe_for_auto_apply"], False)

        candidate = row_order_candidate_for_context(contexts[1], tax_alignment)
        self.assertEqual(candidate["target_qname"], "ifrs-smes:IncomeTaxExpenseContinuingOperations")
        self.assertEqual(candidate["confidence_bucket"], "review_required")

    def test_cash_flow_bank_balances_are_not_balance_sheet_cash_candidate(self):
        contexts = [
            row(
                "Bank balances",
                1,
                family="cash_flow",
                section="cash_flow_reconciliation",
            )
        ]

        alignment = build_statement_row_order_alignments(contexts)[0]

        self.assertEqual(alignment["expected_qname"], "ifrs-smes:CashAndCashEquivalents")
        self.assertNotEqual(alignment["expected_qname"], "ssmt:CashAndBankBalances")
        self.assertIn("cash_flow_reconciliation_not_balance_sheet_cash", alignment["row_order_reasons"])

    def test_row_order_report_serializes_to_json(self):
        report = build_statement_row_order_alignment_report(
            [
                row("Trade and other payables", 1, family="financial_position", section="current_liabilities"),
                row("Total equity and liabilities", 2, family="financial_position", section="equity", role="total"),
            ]
        )

        self.assertEqual(report["summary"]["safe_for_auto_apply"], False)
        self.assertGreaterEqual(report["summary"]["row_order_alignments"], 2)
        encoded = json.dumps(report, default=str)
        self.assertIn("18E-B-2", encoded)
        self.assertIn("EquityAndLiabilities", encoded)


if __name__ == "__main__":
    unittest.main()
