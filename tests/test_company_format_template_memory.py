import json
import unittest

from services.company_format_template_memory import (
    build_company_format_template_memory,
    build_company_format_template_memory_report,
    match_company_format_memory_candidate,
)
from services.pdf_xbrl_deterministic_alignment import canonical_label


def context(label, *, family="income_statement", section="profit_loss", role="total", main=True, notes=False):
    return {
        "sample_id": "case_test",
        "row_id": f"case_test:{canonical_label(label)}:current",
        "original_label": label,
        "normalized_label": canonical_label(label),
        "statement_family": family,
        "section_block": section,
        "row_role": role,
        "is_main_statement": main,
        "is_notes_context": notes,
        "context_confidence": 0.9,
    }


def evaluated_record(label, qname, *, sample="case_001", family="income_statement", section="profit_loss", role="total"):
    ctx = context(label, family=family, section=section, role=role)
    ctx["sample_id"] = sample
    ctx["row_id"] = f"{sample}:{canonical_label(label)}:current"
    return {
        "sample_id": sample,
        "pdf_row_id": ctx["row_id"],
        "pdf_label": label,
        "normalized_label": canonical_label(label),
        "predicted_qname": qname,
        "evaluation_status": "exact_qname_value_period_match",
        "row_context": ctx,
        "safe_for_auto_apply": False,
        "requires_human_review": True,
    }


class CompanyFormatTemplateMemoryTests(unittest.TestCase):
    def test_builds_recurring_pl_format_memory_from_repeated_rows(self):
        entries = build_company_format_template_memory(
            [
                evaluated_record("Loss for the year", "ifrs-smes:ProfitLoss", sample="case_001"),
                evaluated_record("Loss for the year", "ifrs-smes:ProfitLoss", sample="case_002"),
            ]
        )

        self.assertTrue(any(entry["preferred_qname"] == "ifrs-smes:ProfitLoss" for entry in entries))

    def test_builds_recurring_sfp_format_memory_from_repeated_rows(self):
        entries = build_company_format_template_memory(
            [
                evaluated_record(
                    "Total current assets",
                    "ifrs-smes:CurrentAssets",
                    sample="case_001",
                    family="financial_position",
                    section="current_assets",
                ),
                evaluated_record(
                    "Total current assets",
                    "ifrs-smes:CurrentAssets",
                    sample="case_002",
                    family="financial_position",
                    section="current_assets",
                ),
            ]
        )

        self.assertTrue(any(entry["statement_family"] == "financial_position" for entry in entries))

    def test_builds_recurring_cash_flow_format_memory_from_repeated_rows(self):
        entries = build_company_format_template_memory(
            [
                evaluated_record(
                    "Cash and cash equivalents at end of year",
                    "ifrs-smes:CashAndCashEquivalents",
                    sample="case_001",
                    family="cash_flow",
                    section="cash_flow_reconciliation",
                    role="component",
                ),
                evaluated_record(
                    "Cash and cash equivalents at end of year",
                    "ifrs-smes:CashAndCashEquivalents",
                    sample="case_002",
                    family="cash_flow",
                    section="cash_flow_reconciliation",
                    role="component",
                ),
            ]
        )

        self.assertTrue(any(entry["preferred_qname"] == "ifrs-smes:CashAndCashEquivalents" for entry in entries))

    def test_format_memory_does_not_generate_qname_from_row_position_alone(self):
        entries = [
            {
                "memory_entry_id": "fixture",
                "statement_family": "financial_position",
                "section_block": "current_assets",
                "expected_row_role": "total",
                "normalized_label_pattern": "total current assets",
                "label_aliases": ["total current assets"],
                "preferred_qname": "ifrs-smes:CurrentAssets",
            }
        ]

        candidate = match_company_format_memory_candidate(
            context("Amount", family="financial_position", section="current_assets", role="total"),
            entries,
        )

        self.assertIsNone(candidate)

    def test_format_memory_candidate_requires_label_and_context_agreement(self):
        entries = [
            {
                "memory_entry_id": "fixture",
                "statement_family": "financial_position",
                "section_block": "current_assets",
                "expected_row_role": "total",
                "normalized_label_pattern": "total current assets",
                "label_aliases": ["total current assets"],
                "preferred_qname": "ifrs-smes:CurrentAssets",
            }
        ]

        wrong_context = match_company_format_memory_candidate(
            context("Total current assets", family="income_statement", section="profit_loss", role="total"),
            entries,
        )
        right_context = match_company_format_memory_candidate(
            context("Total current assets", family="financial_position", section="current_assets", role="total"),
            entries,
        )

        self.assertIsNone(wrong_context)
        self.assertEqual(right_context["target_qname"], "ifrs-smes:CurrentAssets")
        self.assertEqual(right_context["confidence_bucket"], "review_required")

    def test_reports_serialize_valid_json(self):
        report = build_company_format_template_memory_report(
            [
                evaluated_record("Loss for the year", "ifrs-smes:ProfitLoss", sample="case_001"),
                evaluated_record("Loss for the year", "ifrs-smes:ProfitLoss", sample="case_002"),
            ]
        )

        encoded = json.dumps(report, default=str)
        self.assertIn("format_memory_entries", encoded)
        self.assertEqual(report["summary"]["safe_for_auto_apply_count"], 0)


if __name__ == "__main__":
    unittest.main()
