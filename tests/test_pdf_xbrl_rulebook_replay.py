import json
import unittest
from decimal import Decimal

from services.pdf_xbrl_deterministic_alignment import PdfRowValue
from services.pdf_xbrl_rulebook_replay import (
    build_replay_reports,
    evaluate_prediction,
    leave_one_out_replay,
    replay_row_value,
)


def row_value(label, value="100", *, sample="case_001", family="financial_position", year=2025):
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
        expected_year=year,
        pdf_statement_type=statement,
        pdf_statement_family=family,
        pdf_page=None,
        pdf_row_order=1,
        row_type="numeric_fact",
    )


def rule(pattern, qname, *, aliases=None, family="financial_position", tier="strong", status="active", period="instant"):
    return {
        "rule_id": f"rule:{pattern}:{qname}",
        "normalized_label_pattern": pattern,
        "observed_labels": [pattern],
        "aliases": aliases or [pattern],
        "target_qname": qname,
        "target_concept_label": qname.split(":")[-1],
        "statement_family": family,
        "period_type_hint": period,
        "observation_count": 2,
        "sample_support_count": 2,
        "confidence_tier": tier,
        "rule_status": status,
        "conflict_reasons": [],
    }


def fact(qname, value="100", *, fact_id="fact-1", year=2025, period="instant"):
    base = {
        "fact_id": fact_id,
        "qname": qname,
        "normalized_value": value,
        "value": value,
        "context_ref": f"ctx-{fact_id}",
        "unit_ref": "MYR",
        "is_numeric": True,
        "is_nil": False,
        "period": {"type": period},
    }
    if period == "instant":
        base["instant"] = f"{year}-12-31"
        base["period"]["instant"] = base["instant"]
    else:
        base["period_start"] = f"{year}-01-01"
        base["period_end"] = f"{year}-12-31"
        base["period"].update({"start": base["period_start"], "end": base["period_end"]})
    return base


def alignment(label, qname, *, sample="case_001", family="financial_position", value="100", bucket="high"):
    return {
        "sample_id": sample,
        "company_name": "Example Sdn. Bhd.",
        "pdf_row_id": f"{sample}:{label}:current",
        "pdf_label": label,
        "pdf_value": value,
        "pdf_value_role": "current",
        "pdf_expected_year": 2025,
        "pdf_statement_family": family,
        "pdf_statement_type": "Statement of Financial Position" if family == "financial_position" else "Statement of Comprehensive Income",
        "xbrl_fact_id": f"{sample}:fact:{qname}",
        "xbrl_qname": qname,
        "xbrl_label": qname.split(":")[-1],
        "xbrl_value": value,
        "xbrl_context_id": "ctx",
        "xbrl_period": {"type": "instant", "instant": "2025-12-31"},
        "score": 95,
        "confidence_bucket": bucket,
        "match_reasons": ["value_exact", "exact_normalized_label", "statement_family_match"],
        "conflict_reasons": [],
        "competing_candidates": [],
        "candidate_count": 1,
    }


class PdfXbrlRulebookReplayTests(unittest.TestCase):
    def test_exact_rule_label_match_produces_predicted_qname(self):
        prediction = replay_row_value(
            row_value("Total current assets"),
            [rule("total current assets", "ifrs-smes:CurrentAssets")],
        )

        self.assertEqual(prediction["predicted_qname"], "ifrs-smes:CurrentAssets")
        self.assertEqual(prediction["replay_confidence"], "strong_rule_match")

    def test_observed_alias_match_produces_predicted_qname(self):
        prediction = replay_row_value(
            row_value("Other payables"),
            [rule("trade and other payables", "ssmt-mpers:OtherCurrentNontradePayables", aliases=["other payables"])],
        )

        self.assertEqual(prediction["predicted_qname"], "ssmt-mpers:OtherCurrentNontradePayables")

    def test_statement_family_mismatch_blocks_rule_match(self):
        prediction = replay_row_value(
            row_value("Revenue", family="income_statement"),
            [rule("revenue", "ifrs-smes:Revenue", family="financial_position")],
        )

        self.assertIsNone(prediction["predicted_qname"])
        self.assertEqual(prediction["replay_confidence"], "no_rule_match")
        self.assertIn("statement family", prediction["replay_reason"])

    def test_no_matching_rule_produces_no_rule_match(self):
        prediction = replay_row_value(row_value("Inventories"), [rule("total current assets", "ifrs-smes:CurrentAssets")])

        self.assertIsNone(prediction["predicted_qname"])
        self.assertEqual(prediction["replay_confidence"], "no_rule_match")

    def test_conflicting_rules_produce_conflicting_rule_match(self):
        prediction = replay_row_value(
            row_value("Cash"),
            [
                rule("cash", "ifrs-smes:Cash"),
                rule("cash", "ifrs-smes:CashAndCashEquivalents"),
            ],
        )

        self.assertEqual(prediction["replay_confidence"], "conflicting_rule_match")
        self.assertIsNone(prediction["predicted_qname"])
        self.assertEqual(len(prediction["competing_rules"]), 2)

    def test_exact_qname_value_period_match_is_detected(self):
        row = row_value("Total current assets")
        prediction = replay_row_value(row, [rule("total current assets", "ifrs-smes:CurrentAssets")])
        evaluated = evaluate_prediction(prediction, row, [fact("ifrs-smes:CurrentAssets", "100")])

        self.assertEqual(evaluated["evaluation_status"], "exact_qname_value_period_match")
        self.assertEqual(evaluated["matched_xbrl_fact_id"], "fact-1")

    def test_qname_exists_but_value_mismatch_is_detected(self):
        row = row_value("Total current assets", value="100")
        prediction = replay_row_value(row, [rule("total current assets", "ifrs-smes:CurrentAssets")])
        evaluated = evaluate_prediction(prediction, row, [fact("ifrs-smes:CurrentAssets", "200")])

        self.assertEqual(evaluated["evaluation_status"], "qname_exists_but_value_mismatch")

    def test_value_exists_under_different_qname_is_detected(self):
        row = row_value("Total current assets", value="100")
        prediction = replay_row_value(row, [rule("total current assets", "ifrs-smes:CurrentAssets")])
        evaluated = evaluate_prediction(prediction, row, [fact("ifrs-smes:Assets", "100")])

        self.assertEqual(evaluated["evaluation_status"], "value_exists_but_different_qname")
        self.assertEqual(evaluated["matched_xbrl_qname"], "ifrs-smes:Assets")

    def test_repeated_facts_create_ambiguous_xbrl_support(self):
        row = row_value("Total current assets", value="100")
        prediction = replay_row_value(row, [rule("total current assets", "ifrs-smes:CurrentAssets")])
        evaluated = evaluate_prediction(
            prediction,
            row,
            [
                fact("ifrs-smes:CurrentAssets", "100", fact_id="fact-1"),
                fact("ifrs-smes:CurrentAssets", "100", fact_id="fact-2"),
            ],
        )

        self.assertEqual(evaluated["evaluation_status"], "ambiguous_xbrl_support")

    def test_leave_one_out_excludes_holdout_sample_from_rulebook_training(self):
        samples = {
            "case_001": {"row_values": [row_value("Total current assets", sample="case_001")], "facts": [fact("ifrs-smes:CurrentAssets")]},
            "case_002": {"row_values": [row_value("Total current assets", sample="case_002")], "facts": [fact("ifrs-smes:CurrentAssets")]},
        }
        result = leave_one_out_replay(
            alignments=[
                alignment("Total current assets", "ifrs-smes:CurrentAssets", sample="case_001"),
                alignment("Total current assets", "ifrs-smes:CurrentAssets", sample="case_002"),
            ],
            sample_ids=["case_001", "case_002"],
            sample_loader=lambda sample_id: samples[sample_id],
        )

        for fold in result["folds"]:
            self.assertNotIn(fold["holdout_sample"], fold["train_sample_ids"])

    def test_outlier_result_is_reported_separately(self):
        sample_data = {
            "case_001": {"row_values": [row_value("Total current assets", sample="case_001")], "facts": [fact("ifrs-smes:CurrentAssets")]},
            "case_006": {"row_values": [row_value("Total current assets", sample="case_006")], "facts": [fact("ifrs-smes:CurrentAssets")]},
        }
        report = build_replay_reports(
            dataset_dir="unused",
            alignment_report={
                "discovery": {
                    "included_samples": [{"sample_id": "case_001", "company_name": "Example"}],
                    "excluded_samples": [{"sample_id": "case_006", "reason": "outlier_excluded_by_default"}],
                },
                "alignments": [alignment("Total current assets", "ifrs-smes:CurrentAssets", sample="case_001")],
            },
            rulebook_report={"rules": [rule("total current assets", "ifrs-smes:CurrentAssets")]},
            include_outlier=True,
            skip_leave_one_out=True,
            sample_data_by_id=sample_data,
        )

        self.assertEqual(report["full"]["summary"]["outlier"]["sample_count"], 1)
        self.assertEqual(report["outlier"]["samples"][0]["sample_id"], "case_006")

    def test_replay_report_json_serializes(self):
        sample_data = {
            "case_001": {"row_values": [row_value("Total current assets", sample="case_001")], "facts": [fact("ifrs-smes:CurrentAssets")]},
        }
        report = build_replay_reports(
            dataset_dir="unused",
            alignment_report={
                "discovery": {"included_samples": [{"sample_id": "case_001", "company_name": "Example"}]},
                "alignments": [alignment("Total current assets", "ifrs-smes:CurrentAssets", sample="case_001")],
            },
            rulebook_report={"rules": [rule("total current assets", "ifrs-smes:CurrentAssets")]},
            include_outlier=False,
            skip_leave_one_out=True,
            sample_data_by_id=sample_data,
        )

        encoded = json.dumps(report, default=str)
        self.assertIn("ifrs-smes:CurrentAssets", encoded)


if __name__ == "__main__":
    unittest.main()
