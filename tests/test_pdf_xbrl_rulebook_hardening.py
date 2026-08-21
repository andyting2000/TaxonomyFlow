import json
import unittest
from decimal import Decimal

from services.pdf_xbrl_deterministic_alignment import PdfRowValue, canonical_label
from services.pdf_xbrl_rulebook_hardening import (
    analyze_false_positive,
    build_hardening_reports,
    build_integration_plan,
    build_outlier_replay_report,
    classify_rule_readiness,
)


def rule(
    label,
    qname="ifrs-smes:CurrentAssets",
    *,
    family="financial_position",
    tier="strong",
    samples=2,
    high=2,
    medium=0,
    conflicts=None,
    context=None,
):
    return {
        "rule_id": f"rule:{label}:{qname}",
        "normalized_label_pattern": canonical_label(label),
        "aliases": [canonical_label(label)],
        "target_qname": qname,
        "target_concept_label": qname.split(":")[-1],
        "statement_family": family,
        "period_type_hint": "instant" if family == "financial_position" else "duration",
        "sample_support_count": samples,
        "sample_ids": [f"case_{index:03d}" for index in range(1, samples + 1)],
        "observation_count": high + medium,
        "high_confidence_count": high,
        "medium_confidence_count": medium,
        "score_max": 96 if high else 80,
        "evidence_summary": {
            "label_support": bool(high),
            "zero_value_count": 0,
            "nonzero_value_count": high + medium,
        },
        "confidence_tier": tier,
        "rule_status": "active",
        "conflict_reasons": conflicts or [],
        "required_context_conditions": context or {},
        "blocking_conditions": {},
    }


def performance(*, predictions=4, good=4, false=0):
    return {
        "predictions": predictions,
        "qname_value_matches": good,
        "false_positive_count": false,
        "not_evaluable_count": 0,
        "precision_on_evaluable": round(good / (good + false), 4) if good + false else None,
        "coverage_rate": 0.01,
    }


def row_value(label="Unmatched label"):
    return PdfRowValue(
        sample_id="case_006",
        company_name="Outlier",
        pdf_row_id="row:1:current",
        source_pdf_row_id="row:1",
        pdf_label=label,
        pdf_value="100",
        numeric_value=Decimal("100"),
        value_role="current",
        expected_year=2024,
        pdf_statement_type="Statement of Financial Position",
        pdf_statement_family="financial_position",
        pdf_page=None,
        pdf_row_order=1,
        row_type="numeric_fact",
    )


class PdfXbrlRulebookHardeningTests(unittest.TestCase):
    def test_high_precision_rule_with_no_false_positives_becomes_production_candidate(self):
        result = classify_rule_readiness(rule("Cash and bank balances"), performance(predictions=5, good=5, false=0), total_observations=100)

        self.assertEqual(result["readiness"], "production_candidate")

    def test_rule_with_advisory_precision_and_limited_support_becomes_advisory_candidate(self):
        item = rule("Special deposit", samples=1, high=0, medium=2, tier="usable")
        result = classify_rule_readiness(item, performance(predictions=10, good=9, false=1), total_observations=100)

        self.assertEqual(result["readiness"], "advisory_candidate")

    def test_rule_below_advisory_precision_is_downgraded(self):
        item = rule("Add other income", qname="ifrs-smes:OtherIncome", family="income_statement", tier="usable")
        result = classify_rule_readiness(item, performance(predictions=6, good=5, false=1), total_observations=100)

        self.assertEqual(result["readiness"], "downgrade_to_review_required")

    def test_false_positive_root_cause_is_classified(self):
        analyzed = analyze_false_positive(
            {
                "sample_id": "case_003",
                "pdf_label": "Total current assets",
                "normalized_label": "total current assets",
                "pdf_value": "154021",
                "pdf_statement_family": "financial_position",
                "predicted_qname": "ifrs-smes:CurrentAssets",
                "matched_rule_id": "fold-rule",
                "rule_confidence_tier": "strong",
                "evaluation_status": "qname_exists_but_value_mismatch",
                "error_reason": "predicted qname exists but no matching value/period fact was found",
            }
        )

        self.assertEqual(analyzed["error_type"], "subtotal/component confusion")
        self.assertEqual(analyzed["recommended_fix"], "require section block")

    def test_generic_label_conflict_triggers_review_only(self):
        item = rule("Total", conflicts=["generic_label_requires_review"])
        result = classify_rule_readiness(item, performance(predictions=3, good=3, false=0), total_observations=100)

        self.assertEqual(result["readiness"], "review_only")

    def test_outlier_replay_is_reported_separately(self):
        report = build_outlier_replay_report(
            dataset_dir=".",
            expanded_rulebook={"rules": [rule("Cash and bank balances", qname="ssmt:CashAndBankBalances")]},
            sample_data_by_id={"case_006": {"company_name": "Outlier", "row_values": [row_value()], "facts": []}},
            outlier_sample_ids=["case_006"],
        )

        self.assertEqual(report["summary"]["sample_count"], 1)
        self.assertFalse(report["summary"]["outlier_metrics_mixed_into_main_precision"])
        self.assertEqual(report["summary"]["false_positive_count"], 0)

    def test_integration_plan_contains_no_auto_apply_boundaries(self):
        plan = build_integration_plan(
            readiness_summary={
                "production_candidate_count": 1,
                "advisory_candidate_count": 5,
                "downgrade_to_review_required_count": 1,
            },
            replay_summary={"active_rule_precision_on_evaluable": 0.93, "active_rule_coverage_rate": 0.055},
            outlier_summary={"rules_remain_safe_on_outlier": True},
        )

        self.assertFalse(plan["summary"]["auto_apply_approved"])
        self.assertFalse(plan["summary"]["confirmed_tag_id_automation_approved"])
        self.assertIn("confirmed_tag_id", " ".join(plan["design"]["no_auto_apply_boundaries"]))

    def test_hardening_reports_serialize_valid_json(self):
        expanded = {"rules": [rule("Cash")]}
        replay = {
            "expanded_leave_one_out": {
                "aggregate": {
                    "pdf_observations": 100,
                    "active_rule_predictions": 4,
                    "active_rule_qname_value_matches": 4,
                    "active_rule_false_positive_count": 0,
                    "active_rule_precision_on_evaluable": 1.0,
                    "active_rule_coverage_rate": 0.04,
                }
            }
        }
        reports = build_hardening_reports(
            dataset_dir="not-a-real-dataset",
            expanded_rulebook=expanded,
            expansion_replay=replay,
        )

        encoded = json.dumps(reports, default=str)
        self.assertIn("hardening", encoded)
        self.assertIn("integration_plan", encoded)


if __name__ == "__main__":
    unittest.main()
