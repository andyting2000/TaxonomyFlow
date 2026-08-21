import json
import unittest
from decimal import Decimal

from services.pdf_statement_row_order_alignment import row_order_candidate_for_context
from services.pdf_xbrl_deterministic_alignment import PdfRowValue, canonical_label
from services.pdf_xbrl_rulebook_mapper import apply_dictionary_row_order_mapping
from services.statement_concept_candidate_dictionary import (
    build_statement_concept_candidate_dictionary_report,
    match_statement_concept_candidate,
    statement_concept_candidate_entries,
)


def row_value(label, *, family="income_statement", value="100", order=1):
    statement = {
        "financial_position": "Statement of Financial Position",
        "income_statement": "Statement of Comprehensive Income",
        "cash_flow": "Statement of Cash Flows",
        "notes": "Notes to the Financial Statements",
        "changes_in_equity": "Statement of Changes in Equity",
    }.get(family)
    return PdfRowValue(
        sample_id="case_test",
        company_name="Example Sdn. Bhd.",
        pdf_row_id=f"case_test:r{order}:current",
        source_pdf_row_id=f"case_test:r{order}",
        pdf_label=label,
        pdf_value=value,
        numeric_value=Decimal(value),
        value_role="current",
        expected_year=2024,
        pdf_statement_type=statement,
        pdf_statement_family=family,
        pdf_page=1,
        pdf_row_order=order,
        row_type="numeric_fact",
    )


def context(row, *, section="profit_loss", role="component", confidence=0.92, **overrides):
    payload = {
        "sample_id": row.sample_id,
        "row_id": row.pdf_row_id,
        "source_row_id": row.source_pdf_row_id,
        "original_label": row.pdf_label,
        "normalized_label": canonical_label(row.pdf_label),
        "statement_family": row.pdf_statement_family,
        "statement_title": row.pdf_statement_type,
        "section_block": section,
        "row_role": role,
        "row_order": row.pdf_row_order,
        "is_main_statement": row.pdf_statement_family not in {"notes", None},
        "is_notes_context": row.pdf_statement_family == "notes",
        "is_cash_flow": row.pdf_statement_family == "cash_flow",
        "context_confidence": confidence,
        "context_reasons": ["test_context"],
    }
    payload.update(overrides)
    return payload


def base_record(row):
    return {
        "sample_id": row.sample_id,
        "pdf_row_id": row.pdf_row_id,
        "pdf_label": row.pdf_label,
        "pdf_value": row.pdf_value,
        "normalized_label": canonical_label(row.pdf_label),
        "predicted_qname": None,
        "predicted_concept_label": None,
        "confidence_score": 0.0,
        "confidence_bucket": "no_match",
        "match_reasons": [],
        "blocking_reasons": [],
        "safe_for_auto_apply": False,
        "requires_human_review": True,
    }


class RulebookMapperDictionaryTighteningTests(unittest.TestCase):
    def test_low_context_confidence_blocks_dictionary_candidate(self):
        row = row_value("Revenue")
        candidate = match_statement_concept_candidate(
            context(row, section="revenue", confidence=0.2),
            statement_concept_candidate_entries(),
        )

        self.assertTrue(candidate["candidate_blocked"])
        self.assertIn("low_context_confidence_blocks_dictionary_candidate", candidate["blocking_reasons"])

    def test_note_detail_rows_are_blocked_from_main_statement_dictionary_concepts(self):
        row = row_value("Provision for taxation", family="notes")
        candidate = match_statement_concept_candidate(
            context(row, family="notes", section="notes_tax", role="note_detail", is_main_statement=False, is_notes_context=True),
            statement_concept_candidate_entries(),
        )

        self.assertTrue(candidate["candidate_blocked"])
        self.assertIn("note_detail_main_statement_concept_blocked", candidate["blocking_reasons"])
        self.assertIn("missing_note_link_confirmation", candidate["blocking_reasons"])

    def test_mapper_records_blocking_reasons_without_emitting_qname(self):
        row = row_value("Other operating expenses")
        ctx = context(row, section="administrative_expenses")
        alignment = {
            "alignment_id": "alignment-1",
            "sample_id": row.sample_id,
            "row_id": row.pdf_row_id,
            "expected_qname": "ifrs-smes:AdministrativeExpense",
            "expected_concept_label": "Administrative expense",
            "expected_concept_family": "operating_expense",
            "row_order_confidence": 0.68,
            "row_order_reasons": ["fixture"],
        }

        suggestion = apply_dictionary_row_order_mapping(
            base_record(row),
            ctx,
            statement_concept_candidate_entries(),
            row_order_alignment=alignment,
        )

        self.assertIsNone(suggestion["predicted_qname"])
        self.assertEqual(suggestion["confidence_bucket"], "no_match")
        self.assertIn("administrative_expense_component_dictionary_blocked", suggestion["blocked_candidate_reasons"])
        self.assertIn("row_order_confidence_below_hotfix_threshold", suggestion["blocked_candidate_reasons"])
        self.assertFalse(suggestion["safe_for_auto_apply"])

    def test_row_order_only_generic_label_is_blocked(self):
        row = row_value("Total", family="financial_position")
        ctx = context(row, family="financial_position", section="equity_and_liabilities", role="total")
        candidate = row_order_candidate_for_context(
            ctx,
            {
                "alignment_id": "alignment-2",
                "expected_qname": "ifrs-smes:EquityAndLiabilities",
                "expected_concept_label": "Equity and liabilities",
                "expected_concept_family": "equity_liabilities_total",
                "row_order_confidence": 0.78,
                "row_order_reasons": [],
                "previous_label": None,
                "next_label": None,
                "canonical_position": "sfp_final_total",
            },
        )

        self.assertTrue(candidate["candidate_blocked"])
        self.assertIn("generic_label_without_previous_next_anchors", candidate["blocking_reasons"])

    def test_tax_expense_does_not_map_in_balance_sheet_tax_context(self):
        row = row_value("Tax payable", family="financial_position")
        candidate = match_statement_concept_candidate(
            context(row, family="financial_position", section="current_liabilities"),
            statement_concept_candidate_entries(),
        )

        self.assertEqual(candidate["target_qname"], "ifrs-smes:CurrentTaxLiabilitiesCurrent")
        self.assertNotEqual(candidate["target_qname"], "ifrs-smes:IncomeTaxExpenseContinuingOperations")

    def test_receivables_and_payables_require_matching_sections(self):
        receivable = row_value("Trade and other receivables", family="financial_position")
        payable = row_value("Trade and other payables", family="financial_position")

        self.assertIsNone(
            match_statement_concept_candidate(
                context(receivable, family="financial_position", section="current_liabilities"),
                statement_concept_candidate_entries(),
            )
        )
        self.assertIsNone(
            match_statement_concept_candidate(
                context(payable, family="financial_position", section="current_assets"),
                statement_concept_candidate_entries(),
            )
        )

    def test_cash_contexts_do_not_cross_statement_families(self):
        cash_flow = row_value("Cash and cash equivalents at end of year", family="cash_flow")
        cash_flow_candidate = match_statement_concept_candidate(
            context(cash_flow, family="cash_flow", section="cash_flow_reconciliation"),
            statement_concept_candidate_entries(),
        )
        self.assertEqual(cash_flow_candidate["target_qname"], "ifrs-smes:CashAndCashEquivalents")
        self.assertNotEqual(cash_flow_candidate["target_qname"], "ssmt:CashAndBankBalances")

        balance_sheet = row_value("Bank balances", family="financial_position")
        self.assertIsNone(
            match_statement_concept_candidate(
                context(balance_sheet, family="financial_position", section="current_assets"),
                statement_concept_candidate_entries(),
            )
        )

    def test_total_equity_and_profit_loss_require_final_context(self):
        total = row_value("Total equity and liabilities", family="financial_position")
        self.assertIsNone(
            match_statement_concept_candidate(
                context(total, family="financial_position", section="equity_and_liabilities", role="component"),
                statement_concept_candidate_entries(),
            )
        )

        profit = row_value("Loss for the financial year")
        self.assertIsNone(
            match_statement_concept_candidate(
                context(profit, section="profit_loss", role="component"),
                statement_concept_candidate_entries(),
            )
        )
        candidate = match_statement_concept_candidate(
            context(profit, section="profit_loss", role="total"),
            statement_concept_candidate_entries(),
        )
        self.assertEqual(candidate["target_qname"], "ifrs-smes:ProfitLoss")

    def test_accruals_require_current_liabilities_context(self):
        row = row_value("Accruals", family="financial_position")

        self.assertIsNone(
            match_statement_concept_candidate(
                context(row, family="financial_position", section="administrative_expenses"),
                statement_concept_candidate_entries(),
            )
        )
        candidate = match_statement_concept_candidate(
            context(row, family="financial_position", section="current_liabilities"),
            statement_concept_candidate_entries(),
        )
        self.assertEqual(candidate["target_qname"], "ssmt-mpers:CurrentNontradeAccruals")

    def test_report_serializes_blocked_candidates(self):
        row = row_value("Revenue")
        report = build_statement_concept_candidate_dictionary_report(
            contexts=[context(row, section="revenue", confidence=0.1)]
        )

        encoded = json.dumps(report, default=str)
        self.assertIn("candidate_blocked", encoded)
        self.assertIn("low_context_confidence_blocks_dictionary_candidate", encoded)


if __name__ == "__main__":
    unittest.main()
