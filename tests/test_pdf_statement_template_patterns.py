import json
import unittest

from services.pdf_statement_template_patterns import (
    build_statement_template_report,
    extract_statement_template_patterns,
    match_statement_template_candidate,
)


def context(label, *, family="income_statement", block="income_statement_other", role="component"):
    return {
        "sample_id": "case_test",
        "row_id": f"case_test:{label}:current",
        "source_row_id": f"case_test:{label}",
        "original_label": label,
        "normalized_label": label.lower(),
        "statement_family": family,
        "section_block": block,
        "row_role": role,
        "is_main_statement": True,
        "is_notes_context": False,
        "context_confidence": 0.92,
    }


class PdfStatementTemplatePatternTests(unittest.TestCase):
    def patterns(self, contexts):
        return extract_statement_template_patterns(contexts)

    def test_extracts_supported_statement_patterns(self):
        contexts = [
            context("Gross profit", block="profit_loss", role="subtotal"),
            context("Cash flows from investing activities", family="cash_flow", block="cash_flow_investing", role="heading"),
        ]
        report = build_statement_template_report(contexts)

        self.assertEqual(report["run_metadata"]["feature"], "18E-B")
        self.assertGreaterEqual(report["summary"]["supported_template_patterns"], 2)
        self.assertEqual(report["summary"]["safe_for_auto_apply_count"], 0)

    def test_cost_of_sales_maps_to_cost_of_sales_not_revenue(self):
        patterns = self.patterns([context("Less : Cost of sales", block="cost_of_sales")])
        candidate = match_statement_template_candidate(context("Less : Cost of sales", block="cost_of_sales"), patterns)

        self.assertEqual(candidate["target_qname"], "ifrs-smes:CostOfSales")
        self.assertEqual(candidate["confidence_bucket"], "review_required")
        self.assertIn("statement_template_candidate_requires_review", candidate["blocking_reasons"])

    def test_cash_flow_bank_balances_maps_to_cash_equivalents(self):
        ctx = context("Bank balances", family="cash_flow", block="cash_flow_reconciliation")
        candidate = match_statement_template_candidate(ctx, self.patterns([ctx]))

        self.assertEqual(candidate["target_qname"], "ifrs-smes:CashAndCashEquivalents")
        self.assertNotEqual(candidate["target_qname"], "ssmt:CashAndBankBalances")

    def test_note_title_condition_must_match_when_present(self):
        ctx = context("Tax expense", family="notes", block="notes_tax")
        patterns = self.patterns([ctx])

        self.assertIsNone(match_statement_template_candidate(ctx, patterns, note_link={"note_title": "Property, plant and equipment"}))
        candidate = match_statement_template_candidate(ctx, patterns, note_link={"note_title": "Taxation"})
        self.assertEqual(candidate["target_qname"], "ifrs-smes:IncomeTaxExpenseContinuingOperations")
        self.assertIn("note_linked_candidate_requires_review", candidate["blocking_reasons"])

    def test_patterns_serialize_to_json(self):
        report = build_statement_template_report([context("Audit fee")])

        encoded = json.dumps(report, default=str)
        self.assertIn("18E-B", encoded)
        self.assertIn("AuditorsRemuneration", encoded)


if __name__ == "__main__":
    unittest.main()
