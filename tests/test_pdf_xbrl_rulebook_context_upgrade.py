import json
import unittest
from decimal import Decimal

from services.pdf_xbrl_deterministic_alignment import PdfRowValue, canonical_label
from services.pdf_xbrl_rulebook_context_upgrade import (
    evaluate_context_upgrade,
    expand_rulebook_entries,
    leave_one_out_expansion_replay,
)


def entry(
    label,
    qname,
    *,
    family="income_statement",
    period="duration",
    status="excluded",
    tier="excluded",
    high=2,
    medium=0,
    ambiguous=0,
    low=0,
    samples=2,
    score=95,
    zero=0,
    nonzero=2,
    label_support=True,
    conflicts=None,
):
    return {
        "rule_id": f"rule:{label}:{qname}:{family}",
        "normalized_label_pattern": canonical_label(label),
        "observed_labels": [label],
        "aliases": [label, canonical_label(label)],
        "target_qname": qname,
        "target_concept_label": qname.split(":")[-1],
        "statement_family": family,
        "statement_type_examples": ["Statement of Comprehensive Income" if family == "income_statement" else "Statement of Financial Position"],
        "period_type_hint": period,
        "context_hint": {},
        "sample_support_count": samples,
        "sample_ids": [f"case_{index:03d}" for index in range(1, samples + 1)],
        "observation_count": high + medium + ambiguous + low,
        "total_observation_count": high + medium + ambiguous + low,
        "high_confidence_count": high,
        "medium_confidence_count": medium,
        "ambiguous_observation_count": ambiguous,
        "low_confidence_count": low,
        "source_alignment_ids": [],
        "score_min": score,
        "score_max": score,
        "score_avg": float(score),
        "evidence_summary": {
            "label_support": label_support,
            "zero_value_count": zero,
            "nonzero_value_count": nonzero,
            "match_reasons": ["exact_normalized_label"] if label_support else ["token_or_sequence_similarity"],
        },
        "confidence_tier": tier,
        "rule_status": status,
        "exclusion_reason": None if status != "excluded" else "test_exclusion",
        "conflict_reasons": conflicts or [],
        "competing_qnames": [],
        "competing_label_patterns": [],
        "notes": [],
    }


def stats(label, qname, family, *, good=9, false=1):
    return {
        (canonical_label(label), qname, family): {
            "predictions": good + false,
            "qname_value_matches": good,
            "false_positive_count": false,
            "precision_on_evaluable": round(good / (good + false), 4),
        }
    }


def row_value(label, *, sample="case_001", family="financial_position", value="100"):
    statement = {
        "financial_position": "Statement of Financial Position",
        "income_statement": "Statement of Comprehensive Income",
        "cash_flow": "Statement of Cash Flows",
    }.get(family)
    return PdfRowValue(
        sample_id=sample,
        company_name="Example",
        pdf_row_id=f"{sample}:{label}:current",
        source_pdf_row_id=f"{sample}:{label}",
        pdf_label=label,
        pdf_value=value,
        numeric_value=Decimal(value),
        value_role="current",
        expected_year=2025,
        pdf_statement_type=statement,
        pdf_statement_family=family,
        pdf_page=None,
        pdf_row_order=1,
        row_type="numeric_fact",
    )


def fact(qname, value="100", *, year=2025, period="instant"):
    output = {
        "fact_id": f"fact:{qname}:{value}",
        "qname": qname,
        "normalized_value": value,
        "value": value,
        "context_ref": "ctx",
        "unit_ref": "MYR",
        "is_numeric": True,
        "is_nil": False,
        "period": {"type": period},
    }
    if period == "instant":
        output["instant"] = f"{year}-12-31"
        output["period"]["instant"] = output["instant"]
    else:
        output["period_start"] = f"{year}-01-01"
        output["period_end"] = f"{year}-12-31"
        output["period"].update({"start": output["period_start"], "end": output["period_end"]})
    return output


def alignment(label, qname, *, sample="case_001", family="financial_position", period="instant"):
    return {
        "sample_id": sample,
        "company_name": "Example",
        "pdf_row_id": f"{sample}:{label}:current",
        "pdf_label": label,
        "pdf_value": "100",
        "pdf_value_role": "current",
        "pdf_expected_year": 2025,
        "pdf_statement_family": family,
        "pdf_statement_type": "Statement of Financial Position",
        "xbrl_fact_id": f"{sample}:fact:{qname}",
        "xbrl_qname": qname,
        "xbrl_label": qname.split(":")[-1],
        "xbrl_value": "100",
        "xbrl_context_id": "ctx",
        "xbrl_period": {"type": period, "instant": "2025-12-31"},
        "score": 95,
        "confidence_bucket": "high",
        "match_reasons": ["value_exact", "exact_normalized_label", "statement_family_match"],
        "conflict_reasons": [],
        "competing_candidates": [],
        "candidate_count": 1,
    }


class PdfXbrlRulebookContextUpgradeTests(unittest.TestCase):
    def test_revenue_upgrades_only_with_profit_loss_context(self):
        item = entry("Revenue", "ifrs-smes:Revenue")
        decision = evaluate_context_upgrade(item, prior_replay_stats=stats("Revenue", "ifrs-smes:Revenue", "income_statement"))

        self.assertEqual(decision["upgraded_status"], "upgraded_strong")
        self.assertEqual(decision["required_context_conditions"]["statement_family"], "income_statement")

    def test_revenue_does_not_upgrade_in_balance_sheet_context(self):
        item = entry("Revenue", "ifrs-smes:Revenue", family="financial_position", period="instant")
        decision = evaluate_context_upgrade(item, prior_replay_stats=stats("Revenue", "ifrs-smes:Revenue", "financial_position"))

        self.assertEqual(decision["upgraded_status"], "still_excluded")
        self.assertIn("statement_family_not_allowed_for_context_spec", decision["blocking_reasons"])

    def test_tax_expense_does_not_upgrade_to_balance_sheet_tax_concepts(self):
        item = entry("Tax expense", "ifrs-smes:DeferredTaxAssets", family="financial_position", period="instant")
        decision = evaluate_context_upgrade(item, prior_replay_stats=stats("Tax expense", "ifrs-smes:DeferredTaxAssets", "financial_position"))

        self.assertEqual(decision["upgraded_status"], "still_excluded")
        self.assertIn("target_qname_not_allowed_for_context_spec", decision["blocking_reasons"])

    def test_trade_receivables_requires_assets_context(self):
        item = entry(
            "Trade and other receivables",
            "ifrs-smes:TradeAndOtherCurrentReceivables",
            family="financial_position",
            period="instant",
        )
        decision = evaluate_context_upgrade(
            item,
            prior_replay_stats=stats(
                "Trade and other receivables",
                "ifrs-smes:TradeAndOtherCurrentReceivables",
                "financial_position",
            ),
        )

        self.assertIn(decision["upgraded_status"], {"upgraded_strong", "upgraded_usable"})
        self.assertEqual(decision["required_context_conditions"]["statement_family"], "financial_position")

    def test_trade_receivables_does_not_upgrade_to_payables(self):
        item = entry(
            "Trade and other receivables",
            "ifrs-smes:TradeAndOtherCurrentPayables",
            family="financial_position",
            period="instant",
        )
        decision = evaluate_context_upgrade(item)

        self.assertEqual(decision["upgraded_status"], "still_excluded")
        self.assertIn("target_qname_not_allowed_for_context_spec", decision["blocking_reasons"])

    def test_ppe_requires_balance_sheet_context(self):
        item = entry(
            "Property, plant and equipment",
            "ifrs-smes:PropertyPlantAndEquipment",
            family="financial_position",
            period="instant",
            samples=1,
        )
        decision = evaluate_context_upgrade(item)

        self.assertEqual(decision["upgraded_status"], "upgraded_strong")
        self.assertEqual(decision["required_context_conditions"]["statement_family"], "financial_position")

    def test_ppe_does_not_upgrade_to_depreciation_expense(self):
        item = entry(
            "Property, plant and equipment",
            "ifrs-smes:DepreciationPropertyPlantAndEquipment",
            family="cash_flow",
            period="duration",
        )
        decision = evaluate_context_upgrade(item)

        self.assertEqual(decision["upgraded_status"], "still_excluded")
        self.assertIn("target_qname_not_allowed_for_context_spec", decision["blocking_reasons"])

    def test_bank_balances_requires_cash_compatible_context(self):
        item = entry(
            "Bank balances",
            "ssmt:CashAndBankBalances",
            family="financial_position",
            period="instant",
            high=0,
            ambiguous=8,
            samples=4,
            score=90,
            label_support=False,
            conflicts=["ambiguous_observations_present", "statement_family_conflict"],
        )
        decision = evaluate_context_upgrade(item)

        self.assertEqual(decision["upgraded_status"], "upgraded_usable")
        self.assertEqual(decision["required_context_conditions"]["period_type"], "instant")

    def test_total_current_assets_requires_total_semantics(self):
        item = entry(
            "Current assets",
            "ifrs-smes:CurrentAssets",
            family="financial_position",
            period="instant",
        )
        decision = evaluate_context_upgrade(item)
        self.assertEqual(decision["upgraded_status"], "still_excluded")

        total = entry(
            "Total current assets",
            "ifrs-smes:CurrentAssets",
            family="financial_position",
            period="instant",
        )
        upgraded = evaluate_context_upgrade(total)
        self.assertIn(upgraded["upgraded_status"], {"upgraded_strong", "upgraded_usable"})
        self.assertTrue(upgraded["required_context_conditions"]["requires_total_semantics"])

    def test_total_operating_expenses_requires_operating_expense_subtotal_context(self):
        item = entry("Operating expenses", "ifrs-smes:OtherExpenseByFunction")
        decision = evaluate_context_upgrade(item)
        self.assertEqual(decision["upgraded_status"], "still_excluded")

        total = entry("Total operating expenses", "ifrs-smes:OtherExpenseByFunction", high=0, medium=4, score=77)
        upgraded = evaluate_context_upgrade(
            total,
            prior_replay_stats=stats("Total operating expenses", "ifrs-smes:OtherExpenseByFunction", "income_statement", good=5, false=1),
        )
        self.assertEqual(upgraded["upgraded_status"], "upgraded_usable")
        self.assertTrue(upgraded["required_context_conditions"]["requires_total_semantics"])

    def test_zero_only_evidence_blocks_upgrade(self):
        item = entry("Other income", "ifrs-smes:OtherIncome", zero=2, nonzero=0)
        decision = evaluate_context_upgrade(item, prior_replay_stats=stats("Other income", "ifrs-smes:OtherIncome", "income_statement"))

        self.assertEqual(decision["upgraded_status"], "still_excluded")
        self.assertIn("zero_only_evidence", decision["blocking_reasons"])

    def test_qname_conflict_blocks_unless_context_filter_resolves_it(self):
        revenue = entry(
            "Revenue",
            "ifrs-smes:Revenue",
            conflicts=["label_statement_maps_to_multiple_qnames"],
        )
        blocked = evaluate_context_upgrade(revenue, prior_replay_stats=stats("Revenue", "ifrs-smes:Revenue", "income_statement"))
        self.assertEqual(blocked["upgraded_status"], "still_excluded")

        ppe = entry(
            "Property, plant and equipment",
            "ifrs-smes:PropertyPlantAndEquipment",
            family="financial_position",
            period="instant",
            samples=1,
            conflicts=["label_statement_maps_to_multiple_qnames"],
        )
        resolved = evaluate_context_upgrade(ppe)
        self.assertEqual(resolved["upgraded_status"], "upgraded_strong")

    def test_leave_one_out_training_excludes_holdout_sample(self):
        sample_data = {
            "case_001": {
                "row_values": [row_value("Total current assets", sample="case_001")],
                "facts": [fact("ifrs-smes:CurrentAssets")],
            },
            "case_002": {
                "row_values": [row_value("Total current assets", sample="case_002")],
                "facts": [fact("ifrs-smes:CurrentAssets")],
            },
        }
        result = leave_one_out_expansion_replay(
            alignments=[
                alignment("Total current assets", "ifrs-smes:CurrentAssets", sample="case_001"),
                alignment("Total current assets", "ifrs-smes:CurrentAssets", sample="case_002"),
            ],
            sample_ids=["case_001", "case_002"],
            sample_loader=lambda sample_id: sample_data[sample_id],
            expand=True,
        )

        for fold in result["folds"]:
            self.assertNotIn(fold["holdout_sample"], fold["train_sample_ids"])

    def test_upgraded_rulebook_serializes_valid_json(self):
        result = expand_rulebook_entries(
            [
                entry(
                    "Property, plant and equipment",
                    "ifrs-smes:PropertyPlantAndEquipment",
                    family="financial_position",
                    period="instant",
                    samples=1,
                )
            ]
        )

        encoded = json.dumps(result, default=str)
        self.assertIn("ifrs-smes:PropertyPlantAndEquipment", encoded)


if __name__ == "__main__":
    unittest.main()
