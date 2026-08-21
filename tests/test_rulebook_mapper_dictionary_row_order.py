import unittest
from decimal import Decimal

from services.pdf_statement_row_order_alignment import (
    build_statement_row_order_alignments,
    row_order_alignment_index,
)
from services.pdf_xbrl_deterministic_alignment import PdfRowValue, canonical_label
from services.pdf_xbrl_rulebook_mapper import apply_dictionary_row_order_mapping
from services.statement_concept_candidate_dictionary import statement_concept_candidate_entries


def row_value(label, *, family="income_statement", value="100", order=1):
    statement = {
        "financial_position": "Statement of Financial Position",
        "income_statement": "Statement of Comprehensive Income",
        "cash_flow": "Statement of Cash Flows",
        "notes": "Notes to the Financial Statements",
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


def context(row, *, section="profit_loss", role="component", **overrides):
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
        "is_main_statement": row.pdf_statement_family != "notes",
        "is_notes_context": row.pdf_statement_family == "notes",
        "is_cash_flow": row.pdf_statement_family == "cash_flow",
        "context_confidence": 0.92,
        "context_reasons": ["test_context"],
    }
    payload.update(overrides)
    return payload


def base_record(row, *, predicted_qname=None, bucket="no_match"):
    return {
        "sample_id": row.sample_id,
        "pdf_row_id": row.pdf_row_id,
        "pdf_label": row.pdf_label,
        "pdf_value": row.pdf_value,
        "normalized_label": canonical_label(row.pdf_label),
        "predicted_qname": predicted_qname,
        "predicted_concept_label": None,
        "confidence_score": 0.9 if predicted_qname else 0.0,
        "confidence_bucket": bucket,
        "match_reasons": ["fixture"] if predicted_qname else [],
        "blocking_reasons": [],
        "safe_for_auto_apply": False,
        "requires_human_review": True,
    }


class RulebookMapperDictionaryRowOrderTests(unittest.TestCase):
    def test_dictionary_and_row_order_agreement_adds_review_required_candidate(self):
        before_tax = row_value("Loss before tax", order=1)
        tax = row_value("Tax expense", order=2)
        after_tax = row_value("Loss for the financial year", order=3)
        contexts = [
            context(before_tax, section="profit_loss_before_tax", role="subtotal"),
            context(tax, section="tax_expense"),
            context(after_tax, section="profit_loss", role="total"),
        ]
        alignment = row_order_alignment_index(build_statement_row_order_alignments(contexts))[(tax.sample_id, tax.pdf_row_id)]

        suggestion = apply_dictionary_row_order_mapping(
            base_record(tax),
            contexts[1],
            statement_concept_candidate_entries(),
            row_order_alignment=alignment,
        )

        self.assertEqual(suggestion["predicted_qname"], "ifrs-smes:IncomeTaxExpenseContinuingOperations")
        self.assertEqual(suggestion["confidence_bucket"], "review_required")
        self.assertEqual(suggestion["candidate_generation_method"], "dictionary_row_order_agreement")
        self.assertEqual(suggestion["context_dictionary_agreement"], "dictionary_row_order_agree")
        self.assertTrue(suggestion["dictionary_row_order_optimization_applied"])
        self.assertFalse(suggestion["safe_for_auto_apply"])
        self.assertTrue(suggestion["requires_human_review"])
        self.assertIn("dictionary_row_order_candidate_requires_review", suggestion["blocking_reasons"])

    def test_existing_prediction_conflict_is_downgraded_to_review_required(self):
        gross_profit = row_value("Gross profit", order=1)
        ctx = context(gross_profit, section="profit_loss", role="subtotal")

        suggestion = apply_dictionary_row_order_mapping(
            base_record(gross_profit, predicted_qname="ifrs-smes:Revenue", bucket="advisory_high"),
            ctx,
            statement_concept_candidate_entries(),
            row_order_alignment=None,
        )

        self.assertEqual(suggestion["predicted_qname"], "ifrs-smes:Revenue")
        self.assertEqual(suggestion["confidence_bucket"], "review_required")
        self.assertIn("dictionary_candidate_conflicts_with_existing_prediction", suggestion["blocking_reasons"])
        self.assertEqual(suggestion["dictionary_conflict_candidate"]["target_qname"], "ifrs-smes:GrossProfit")
        self.assertFalse(suggestion["safe_for_auto_apply"])


if __name__ == "__main__":
    unittest.main()
