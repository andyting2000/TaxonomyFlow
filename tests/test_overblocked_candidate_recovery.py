import json
import tempfile
import unittest
from pathlib import Path

from scripts.recover_overblocked_candidates_18e_d_hotfix_1 import build_recovery_reports, write_recovery_reports
from services.pdf_xbrl_deterministic_alignment import canonical_label
from services.pdf_xbrl_rulebook_mapper import apply_overblocked_candidate_recovery


def base_record(
    label,
    target_qname,
    *,
    family="income_statement",
    section="profit_loss",
    role="total",
    source="dictionary",
    existing_qname=None,
    confidence=0.95,
    is_main=True,
    is_notes=False,
    is_cash_flow=False,
    extra_context=None,
):
    field = "blocked_dictionary_candidate" if source == "dictionary" else "blocked_row_order_candidate"
    id_field = "dictionary_id" if source == "dictionary" else "row_order_id"
    context = {
        "statement_family": family,
        "statement_title": "Statement of Comprehensive Income",
        "section_block": section,
        "row_role": role,
        "is_main_statement": is_main,
        "is_notes_context": is_notes,
        "is_cash_flow": is_cash_flow,
        "context_confidence": confidence,
        "context_reasons": ["test_context"],
    }
    context.update(extra_context or {})
    return {
        "sample_id": "case_test",
        "company_name": "Example Sdn. Bhd.",
        "pdf_row_id": f"case_test:{canonical_label(label)}:current",
        "pdf_label": label,
        "normalized_label": canonical_label(label),
        "pdf_value": "100",
        "predicted_qname": existing_qname,
        "predicted_concept_label": existing_qname.split(":")[-1] if existing_qname else None,
        "confidence_bucket": "review_required" if existing_qname else "no_match",
        "confidence_score": 0.5 if existing_qname else 0.0,
        "requires_human_review": True,
        "safe_for_auto_apply": False,
        "match_reasons": [],
        "blocking_reasons": ["fixture_block"],
        "row_context": context,
        "evaluation_status": "exact_qname_value_period_match" if existing_qname else None,
        field: {
            id_field: "fixture-candidate",
            "target_qname": target_qname,
            "target_concept_label": target_qname.split(":")[-1],
            "concept_family": target_qname.split(":")[-1].lower(),
            "confidence_score": 0.62,
            "candidate_blocked": True,
            "match_reasons": ["fixture_candidate"],
            "blocking_reasons": ["fixture_block"],
        },
    }


def first_decision(record):
    return record["overblocked_recovery_decisions"][0]


class OverblockedCandidateRecoveryTests(unittest.TestCase):
    def test_profit_loss_final_pl_row_can_be_recovered(self):
        record = base_record("Loss for the financial year", "ifrs-smes:ProfitLoss")

        recovered = apply_overblocked_candidate_recovery(record)

        self.assertEqual(recovered["predicted_qname"], "ifrs-smes:ProfitLoss")
        self.assertEqual(recovered["confidence_bucket"], "review_required")
        self.assertEqual(first_decision(recovered)["classification"], "recovered_low_risk")

    def test_profit_loss_is_not_recovered_for_cash_flow_operating_profit(self):
        record = base_record(
            "Profit from operating activities",
            "ifrs-smes:ProfitLoss",
            family="cash_flow",
            section="cash_flow_operating",
            role="component",
            is_cash_flow=True,
        )

        recovered = apply_overblocked_candidate_recovery(record)

        self.assertIsNone(recovered["predicted_qname"])
        self.assertFalse(first_decision(recovered)["can_recover"])

    def test_profit_loss_is_not_recovered_for_retained_earnings_movement(self):
        record = base_record(
            "Retained earnings - loss for the financial year",
            "ifrs-smes:ProfitLoss",
            family="changes_in_equity",
            section="changes_in_equity",
            role="component",
        )

        recovered = apply_overblocked_candidate_recovery(record)

        self.assertIsNone(recovered["predicted_qname"])
        self.assertIn("main_income_statement_context", first_decision(recovered)["evidence_conditions_failed"])

    def test_income_tax_expense_can_be_recovered_in_pl_after_profit_before_tax(self):
        record = base_record(
            "Income tax expense",
            "ifrs-smes:IncomeTaxExpenseContinuingOperations",
            section="tax_expense",
            role="component",
            extra_context={"previous_label": "Profit before tax"},
        )

        recovered = apply_overblocked_candidate_recovery(record)

        self.assertEqual(recovered["predicted_qname"], "ifrs-smes:IncomeTaxExpenseContinuingOperations")
        self.assertEqual(first_decision(recovered)["classification"], "recovered_low_risk")

    def test_tax_payable_is_not_recovered_as_income_tax_expense(self):
        record = base_record(
            "Tax payable",
            "ifrs-smes:IncomeTaxExpenseContinuingOperations",
            family="financial_position",
            section="current_liabilities",
        )

        recovered = apply_overblocked_candidate_recovery(record)

        self.assertIsNone(recovered["predicted_qname"])
        self.assertIn("main_income_statement_context", first_decision(recovered)["evidence_conditions_failed"])

    def test_deferred_tax_is_not_recovered_as_income_tax_expense(self):
        record = base_record(
            "Deferred tax expense",
            "ifrs-smes:IncomeTaxExpenseContinuingOperations",
            section="tax_expense",
            role="component",
        )

        recovered = apply_overblocked_candidate_recovery(record)

        self.assertIsNone(recovered["predicted_qname"])
        self.assertIn("not_balance_sheet_tax_asset_or_liability", first_decision(recovered)["evidence_conditions_failed"])

    def test_other_income_exact_pl_row_can_be_recovered(self):
        record = base_record("Other income", "ifrs-smes:OtherIncome", section="other_income", role="component")

        recovered = apply_overblocked_candidate_recovery(record)

        self.assertEqual(recovered["predicted_qname"], "ifrs-smes:OtherIncome")
        self.assertEqual(first_decision(recovered)["classification"], "recovered_low_risk")

    def test_other_income_is_not_recovered_for_finance_income_or_revenue(self):
        finance = base_record("Finance income", "ifrs-smes:OtherIncome", section="other_income", role="component")
        revenue = base_record("Revenue", "ifrs-smes:OtherIncome", section="other_income", role="component")

        self.assertIsNone(apply_overblocked_candidate_recovery(finance)["predicted_qname"])
        self.assertIsNone(apply_overblocked_candidate_recovery(revenue)["predicted_qname"])

    def test_note_detail_tax_rows_remain_blocked_without_note_link_confirmation(self):
        record = base_record(
            "Tax expenses for the year",
            "ifrs-smes:IncomeTaxExpenseContinuingOperations",
            family="notes",
            section="notes_tax",
            role="note_detail",
            is_main=False,
            is_notes=True,
            confidence=0.55,
        )

        recovered = apply_overblocked_candidate_recovery(record)

        self.assertIsNone(recovered["predicted_qname"])
        self.assertIn("not_note_detail_tax", first_decision(recovered)["evidence_conditions_failed"])

    def test_receivables_and_payables_remain_blocked_outside_recovery_scope(self):
        receivable = base_record(
            "Trade and other receivables",
            "ifrs-smes:TradeAndOtherCurrentReceivables",
            family="financial_position",
            section="current_assets",
        )
        payable = base_record(
            "Trade and other payables",
            "ifrs-smes:TradeAndOtherCurrentPayables",
            family="financial_position",
            section="current_liabilities",
        )

        self.assertIsNone(apply_overblocked_candidate_recovery(receivable)["predicted_qname"])
        self.assertIsNone(apply_overblocked_candidate_recovery(payable)["predicted_qname"])

    def test_recovered_candidates_are_review_required_only_and_never_auto_apply(self):
        record = base_record("Loss for the financial year", "ifrs-smes:ProfitLoss")

        recovered = apply_overblocked_candidate_recovery(record)

        self.assertEqual(recovered["confidence_bucket"], "review_required")
        self.assertTrue(recovered["requires_human_review"])
        self.assertFalse(recovered["safe_for_auto_apply"])
        self.assertFalse(first_decision(recovered)["safe_for_auto_apply"])

    def test_reports_serialize_valid_json(self):
        record = base_record("Other income", "ifrs-smes:OtherIncome", section="other_income", role="component")
        analysis = {
            "blocked_candidates": [
                {
                    "sample_id": record["sample_id"],
                    "pdf_row_id": record["pdf_row_id"],
                    "pdf_label": record["pdf_label"],
                    "normalized_label": record["normalized_label"],
                    "target_qname": "ifrs-smes:OtherIncome",
                    "blocked_source": "dictionary",
                    "blocked_candidate_classification": "overblocked_true_positive",
                    "evaluation_status": "exact_qname_value_period_match",
                    "risk_level": "medium",
                    "blocking_reasons": ["fixture_block"],
                }
            ]
        }
        record["evaluation_status"] = "exact_qname_value_period_match"

        reports = build_recovery_reports([record], blocked_analysis=analysis, generated_at="2026-06-23T00:00:00Z")

        with tempfile.TemporaryDirectory() as temp:
            paths = write_recovery_reports(reports, output_dir=temp)
            for key, path in paths.items():
                if key.endswith("_json"):
                    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
                    self.assertIn("run_metadata", loaded)


if __name__ == "__main__":
    unittest.main()
