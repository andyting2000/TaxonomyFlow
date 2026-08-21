import json
import unittest
from decimal import Decimal

from services.pdf_xbrl_deterministic_alignment import PdfRowValue, canonical_label
from services.pdf_xbrl_rulebook_mapper import build_mapper_reports, load_hardened_mapper_rules, map_row_value


def row_value(label, *, family="financial_position", value="100", sample="case_001"):
    statement = {
        "financial_position": "Statement of Financial Position",
        "income_statement": "Statement of Comprehensive Income",
        "cash_flow": "Statement of Cash Flows",
    }.get(family)
    return PdfRowValue(
        sample_id=sample,
        company_name="Example Sdn. Bhd.",
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


def readiness_rule(
    label,
    qname="ifrs-smes:CurrentAssets",
    *,
    readiness="advisory_candidate",
    family="financial_position",
    tier="strong",
    conflicts=None,
    performance=None,
):
    return {
        "rule_id": f"rule:{label}:{qname}",
        "normalized_label_pattern": canonical_label(label),
        "target_qname": qname,
        "target_concept_label": qname.split(":")[-1],
        "statement_family": family,
        "confidence_tier": tier,
        "sample_support_count": 2,
        "observation_count": 2,
        "readiness": readiness,
        "classification_reasons": ["test readiness"],
        "risk_flags": {
            "zero_only_evidence": False,
            "qname_conflict": False,
            "statement_family_conflict": False,
            "generic_label": False,
            "generic_without_context": False,
            "context_conditions_required": False,
            "stable_support": True,
            "strong_concept_evidence": tier == "strong",
            "conflict_reasons": conflicts or [],
        },
        "performance": performance
        or {
            "predictions": 2,
            "qname_value_matches": 2,
            "false_positive_count": 0,
            "precision_on_evaluable": 1.0,
            "coverage_rate": 0.02,
        },
        "required_context_conditions": {},
        "blocking_conditions": {},
    }


def hardened_report(rules, *, false_positives=None):
    return {
        "run_metadata": {"feature": "18D-B"},
        "summary": {},
        "rule_readiness": rules,
        "false_positive_root_causes": false_positives or [],
    }


class PdfXbrlRulebookMapperTests(unittest.TestCase):
    def test_advisory_candidate_rule_produces_advisory_suggestion(self):
        rules = load_hardened_mapper_rules(hardened_report([readiness_rule("Bank balances", "ssmt:CashAndBankBalances")]))
        suggestion = map_row_value(row_value("Bank balances"), rules)

        self.assertEqual(suggestion["confidence_bucket"], "advisory_high")
        self.assertEqual(suggestion["predicted_qname"], "ssmt:CashAndBankBalances")
        self.assertFalse(suggestion["safe_for_auto_apply"])

    def test_downgraded_rule_produces_review_required_suggestion(self):
        rules = load_hardened_mapper_rules(
            hardened_report(
                [
                    readiness_rule(
                        "Add other income",
                        "ifrs-smes:OtherIncome",
                        readiness="downgrade_to_review_required",
                        family="income_statement",
                        tier="usable",
                    )
                ]
            )
        )
        suggestion = map_row_value(row_value("Add : Other income", family="income_statement"), rules)

        self.assertEqual(suggestion["confidence_bucket"], "review_required")
        self.assertEqual(suggestion["rule_readiness"], "downgraded")
        self.assertIn("hardened_rule_requires_review", suggestion["blocking_reasons"])

    def test_excluded_rule_produces_no_suggestion(self):
        rules = load_hardened_mapper_rules(hardened_report([readiness_rule("Cash", "ifrs-smes:Cash", readiness="exclude")]))
        suggestion = map_row_value(row_value("Cash"), rules)

        self.assertEqual(suggestion["confidence_bucket"], "no_match")
        self.assertIsNone(suggestion["predicted_qname"])
        self.assertIn("matched excluded rule only", suggestion["blocking_reasons"])

    def test_multiple_matching_rules_produce_conflict(self):
        rules = load_hardened_mapper_rules(
            hardened_report(
                [
                    readiness_rule("Cash", "ifrs-smes:Cash"),
                    readiness_rule("Cash", "ifrs-smes:CashAndCashEquivalents"),
                ]
            )
        )
        suggestion = map_row_value(row_value("Cash"), rules)

        self.assertEqual(suggestion["confidence_bucket"], "conflict")
        self.assertIsNone(suggestion["predicted_qname"])
        self.assertEqual(len(suggestion["competing_rules"]), 2)

    def test_generic_label_without_context_downgrades_to_review_required(self):
        rules = load_hardened_mapper_rules(hardened_report([readiness_rule("Other", "ifrs-smes:OtherIncome", family=None)]))
        suggestion = map_row_value(row_value("Other", family=None), rules)

        self.assertEqual(suggestion["confidence_bucket"], "review_required")
        self.assertIn("generic_label_requires_review", suggestion["blocking_reasons"])
        self.assertIn("missing_section_context", suggestion["blocking_reasons"])

    def test_known_false_positive_risk_downgrades_to_review_required(self):
        report = hardened_report(
            [readiness_rule("Special deposit", "ssmt-mpers:OtherCurrentNontradeDeposits")],
            false_positives=[
                {
                    "sample_id": "case_003",
                    "pdf_label": "Special deposit",
                    "normalized_label": "special deposit",
                    "pdf_statement_family": "financial_position",
                    "predicted_qname": "ssmt-mpers:OtherCurrentNontradeDeposits",
                    "error_type": "value matched wrong concept",
                    "recommended_fix": "leave for human review",
                }
            ],
        )
        rules = load_hardened_mapper_rules(report)
        suggestion = map_row_value(row_value("Special deposit"), rules, false_positive_index={("special deposit", "ssmt-mpers:OtherCurrentNontradeDeposits", "financial_position"): report["false_positive_root_causes"]})

        self.assertEqual(suggestion["confidence_bucket"], "review_required")
        self.assertIn("known_false_positive_risk", suggestion["blocking_reasons"])
        self.assertEqual(suggestion["false_positive_risk_notes"][0]["error_type"], "value matched wrong concept")

    def test_safe_for_auto_apply_is_always_false(self):
        reports = build_mapper_reports(
            dataset_dir="unused",
            hardened_rulebook=hardened_report([readiness_rule("Bank balances", "ssmt:CashAndBankBalances")]),
            sample_data_by_id={"case_001": {"row_values": [row_value("Bank balances"), row_value("Unmatched label")]}},
        )

        self.assertTrue(reports["summary"]["summary"]["no_suggestion_safe_for_auto_apply"])
        for suggestion in reports["suggestions"]["suggestions"]:
            self.assertFalse(suggestion["safe_for_auto_apply"])

    def test_no_db_mutation_occurs(self):
        reports = build_mapper_reports(
            dataset_dir="unused",
            hardened_rulebook=hardened_report([readiness_rule("Bank balances", "ssmt:CashAndBankBalances")]),
            sample_data_by_id={"case_001": {"row_values": [row_value("Bank balances")]}},
        )

        self.assertFalse(reports["summary"]["summary"]["safety"]["database_mutated"])
        self.assertFalse(reports["summary"]["summary"]["safety"]["production_behavior_changed"])

    def test_mapper_output_serializes_valid_json(self):
        reports = build_mapper_reports(
            dataset_dir="unused",
            hardened_rulebook=hardened_report([readiness_rule("Bank balances", "ssmt:CashAndBankBalances")]),
            sample_data_by_id={"case_001": {"row_values": [row_value("Bank balances")]}},
        )

        encoded = json.dumps(reports, default=str)
        self.assertIn("ssmt:CashAndBankBalances", encoded)

    def test_report_json_validates(self):
        reports = build_mapper_reports(
            dataset_dir="unused",
            hardened_rulebook=hardened_report([readiness_rule("Bank balances", "ssmt:CashAndBankBalances")]),
            sample_data_by_id={"case_001": {"row_values": [row_value("Bank balances"), row_value("Unmatched label")]}},
        )

        for key in ("suggestions", "summary", "conflicts", "no_match"):
            payload = json.loads(json.dumps(reports[key], default=str))
            self.assertEqual(payload["run_metadata"]["feature"], "18D-C")


if __name__ == "__main__":
    unittest.main()
