import json
import unittest

from services.statement_concept_candidate_dictionary import (
    build_statement_concept_candidate_dictionary_report,
    match_statement_concept_candidate,
    statement_concept_candidate_entries,
)


def context(label, *, family="income_statement", section="profit_loss", **overrides):
    payload = {
        "sample_id": "case_test",
        "row_id": f"case_test:{label}:current",
        "original_label": label,
        "normalized_label": label.lower(),
        "statement_family": family,
        "statement_title": "Statement of Comprehensive Income",
        "section_block": section,
        "row_role": "component",
        "is_main_statement": family != "notes",
        "is_notes_context": family == "notes",
    }
    payload.update(overrides)
    return payload


class StatementConceptCandidateDictionaryTests(unittest.TestCase):
    def test_revenue_candidate_requires_income_statement_context(self):
        entries = statement_concept_candidate_entries()

        match = match_statement_concept_candidate(
            context("Revenue", section="revenue"),
            entries,
        )
        self.assertIsNotNone(match)
        self.assertEqual(match["target_qname"], "ifrs-smes:Revenue")
        self.assertEqual(match["confidence_bucket"], "review_required")
        self.assertIn("dictionary_candidate_requires_review", match["blocking_reasons"])

        no_match = match_statement_concept_candidate(
            context("Revenue", family="financial_position", section="current_assets"),
            entries,
        )
        self.assertIsNone(no_match)

    def test_tax_expense_and_tax_payable_stay_statement_specific(self):
        entries = statement_concept_candidate_entries()

        tax_expense = match_statement_concept_candidate(
            context("Tax expense", section="tax_expense"),
            entries,
        )
        self.assertEqual(tax_expense["target_qname"], "ifrs-smes:IncomeTaxExpenseContinuingOperations")

        tax_payable = match_statement_concept_candidate(
            context("Tax payable", family="financial_position", section="current_liabilities"),
            entries,
        )
        self.assertEqual(tax_payable["target_qname"], "ifrs-smes:CurrentTaxLiabilitiesCurrent")
        self.assertNotEqual(tax_payable["target_qname"], tax_expense["target_qname"])

    def test_notes_tax_candidate_is_blocked_by_hotfix(self):
        entries = statement_concept_candidate_entries()

        match = match_statement_concept_candidate(
            context(
                "Provision for taxation",
                family="notes",
                section="notes_tax",
                is_main_statement=False,
                is_notes_context=True,
            ),
            entries,
        )

        self.assertEqual(match["dictionary_entry_id"], "18E-B2-note-tax-expense")
        self.assertTrue(match["candidate_blocked"])
        self.assertEqual(match["confidence_bucket"], "no_match")
        self.assertIn("notes_context_requires_review", match["blocking_reasons"])
        self.assertIn("missing_note_link_confirmation", match["blocking_reasons"])

    def test_dictionary_report_serializes_to_json(self):
        report = build_statement_concept_candidate_dictionary_report(
            contexts=[
                context("Trade and other receivables", family="financial_position", section="current_assets"),
                context("Trade and other payables", family="financial_position", section="current_liabilities"),
            ]
        )

        self.assertGreaterEqual(report["summary"]["dictionary_entry_count"], 1)
        self.assertEqual(report["summary"]["safe_for_auto_apply"], False)
        encoded = json.dumps(report, default=str)
        self.assertIn("18E-B-2", encoded)
        self.assertIn("TradeAndOtherCurrentReceivables", encoded)


if __name__ == "__main__":
    unittest.main()
