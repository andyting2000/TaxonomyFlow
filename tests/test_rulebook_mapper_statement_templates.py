import json
import unittest
from decimal import Decimal

from services.pdf_statement_template_patterns import extract_statement_template_patterns
from services.pdf_xbrl_deterministic_alignment import PdfRowValue, canonical_label
from services.pdf_xbrl_rulebook_mapper import (
    apply_statement_template_mapping,
    map_row_values_with_statement_templates,
)


def row_value(label, *, family="income_statement", value="100"):
    statement = {
        "financial_position": "Statement of Financial Position",
        "income_statement": "Statement of Comprehensive Income",
        "cash_flow": "Statement of Cash Flows",
        "notes": "Notes to the Financial Statements",
    }.get(family)
    return PdfRowValue(
        sample_id="case_test",
        company_name="Example Sdn. Bhd.",
        pdf_row_id=f"case_test:{label}:current",
        source_pdf_row_id=f"case_test:{label}",
        pdf_label=label,
        pdf_value=value,
        numeric_value=Decimal(value),
        value_role="current",
        expected_year=2024,
        pdf_statement_type=statement,
        pdf_statement_family=family,
        pdf_page=1,
        pdf_row_order=1,
        row_type="numeric_fact",
    )


def context(row, **overrides):
    payload = {
        "sample_id": row.sample_id,
        "row_id": row.pdf_row_id,
        "source_row_id": row.source_pdf_row_id,
        "original_label": row.pdf_label,
        "normalized_label": canonical_label(row.pdf_label),
        "statement_family": row.pdf_statement_family,
        "statement_title": row.pdf_statement_type,
        "section_block": "unknown",
        "row_role": "component",
        "is_main_statement": row.pdf_statement_family != "notes",
        "is_notes_context": row.pdf_statement_family == "notes",
        "is_cash_flow": row.pdf_statement_family == "cash_flow",
        "context_confidence": 0.92,
        "context_reasons": ["test_context"],
    }
    payload.update(overrides)
    return payload


class RulebookMapperStatementTemplateTests(unittest.TestCase):
    def map_one(self, row, ctx, *, note_links=()):
        patterns = extract_statement_template_patterns([ctx])
        return map_row_values_with_statement_templates([row], [], [ctx], patterns, note_links)[0]

    def test_template_adds_review_required_cash_flow_cash_equivalents_candidate(self):
        row = row_value("Cash and cash equivalents at end of period", family="cash_flow")
        suggestion = self.map_one(row, context(row, section_block="cash_flow_reconciliation"))

        self.assertEqual(suggestion["predicted_qname"], "ifrs-smes:CashAndCashEquivalents")
        self.assertEqual(suggestion["confidence_bucket"], "review_required")
        self.assertTrue(suggestion["statement_template_optimization_applied"])
        self.assertFalse(suggestion["safe_for_auto_apply"])

    def test_template_does_not_map_cash_flow_bank_balances_to_balance_sheet_cash(self):
        row = row_value("Bank balances", family="cash_flow")
        suggestion = self.map_one(row, context(row, section_block="cash_flow_reconciliation"))

        self.assertEqual(suggestion["predicted_qname"], "ifrs-smes:CashAndCashEquivalents")
        self.assertNotEqual(suggestion["predicted_qname"], "ssmt:CashAndBankBalances")

    def test_statement_template_conflict_downgrades_existing_prediction_to_review(self):
        row = row_value("Gross profit")
        ctx = context(row, section_block="profit_loss", row_role="subtotal")
        base = {
            "pdf_row_id": row.pdf_row_id,
            "sample_id": row.sample_id,
            "predicted_qname": "ifrs-smes:Revenue",
            "predicted_concept_label": "Revenue",
            "confidence_score": 0.9,
            "confidence_bucket": "advisory_high",
            "blocking_reasons": [],
            "match_reasons": ["fixture"],
            "safe_for_auto_apply": False,
            "requires_human_review": True,
        }

        suggestion = apply_statement_template_mapping(base, ctx, extract_statement_template_patterns([ctx]))

        self.assertEqual(suggestion["predicted_qname"], "ifrs-smes:Revenue")
        self.assertEqual(suggestion["confidence_bucket"], "review_required")
        self.assertIn("template_candidate_conflicts_with_existing_prediction", suggestion["blocking_reasons"])
        self.assertEqual(suggestion["template_conflict_candidate"]["target_qname"], "ifrs-smes:GrossProfit")

    def test_note_link_candidate_is_review_required(self):
        row = row_value("Tax expense", family="notes")
        ctx = context(row, section_block="notes_tax", is_main_statement=False, is_notes_context=True)
        note_link = {
            "sample_id": row.sample_id,
            "row_id": row.pdf_row_id,
            "note_number": "9",
            "note_title": "Taxation",
            "note_link_confidence": 0.9,
        }
        suggestion = self.map_one(row, ctx, note_links=[note_link])

        self.assertEqual(suggestion["predicted_qname"], "ifrs-smes:IncomeTaxExpenseContinuingOperations")
        self.assertEqual(suggestion["confidence_bucket"], "review_required")
        self.assertEqual(suggestion["note_link"]["note_number"], "9")
        self.assertIn("notes_context_requires_review", suggestion["blocking_reasons"])

    def test_template_output_serializes_to_json(self):
        row = row_value("Audit fee")
        suggestion = self.map_one(row, context(row, section_block="administrative_expenses"))

        encoded = json.dumps(suggestion, default=str)
        self.assertIn("statement_template_optimization_applied", encoded)
        self.assertIn("AuditorsRemuneration", encoded)


if __name__ == "__main__":
    unittest.main()
