import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from services.pdf_xbrl_deterministic_alignment import PdfRowValue
from services.tightened_mapper_evaluation import (
    analyze_blocked_candidates,
    build_label_family_metrics,
    build_readiness_matrix,
    build_source_metrics,
    build_statement_family_metrics,
    build_tightened_mapper_reports,
    classify_evaluation_result,
    evaluate_candidate_record,
    write_reports,
)


def row_value(label, value="100", *, sample="case_test", family="financial_position", year=2025):
    statement = {
        "financial_position": "Statement of Financial Position",
        "income_statement": "Statement of Comprehensive Income",
        "cash_flow": "Statement of Cash Flows",
        "notes": "Notes to the Financial Statements",
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


def fact(qname, value="100", *, fact_id="fact-1", year=2025, period="instant"):
    payload = {
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
        payload["instant"] = f"{year}-12-31"
        payload["period"]["instant"] = payload["instant"]
    else:
        payload["period_start"] = f"{year}-01-01"
        payload["period_end"] = f"{year}-12-31"
        payload["period"].update({"start": payload["period_start"], "end": payload["period_end"]})
    return payload


def candidate(row, qname="ifrs-smes:CurrentAssets", *, source="statement_concept_dictionary", status=None):
    return {
        "sample_id": row.sample_id,
        "company_name": row.company_name,
        "pdf_row_id": row.pdf_row_id,
        "pdf_label": row.pdf_label,
        "normalized_label": row.pdf_label.lower(),
        "pdf_value": row.pdf_value,
        "pdf_statement_family": row.pdf_statement_family,
        "pdf_statement_type": row.pdf_statement_type,
        "candidate_generation_method": source,
        "predicted_qname": qname,
        "predicted_concept_label": qname.split(":")[-1] if qname else None,
        "confidence_bucket": "review_required" if qname else "no_match",
        "requires_human_review": True,
        "safe_for_auto_apply": False,
        "row_context": {
            "statement_family": row.pdf_statement_family,
            "statement_title": row.pdf_statement_type,
            "section_block": "current_assets",
            "row_role": "total",
            "context_confidence": 0.95,
            "is_notes_context": row.pdf_statement_family == "notes",
        },
        "evaluation_status": status or ("not_evaluable" if not qname else None),
    }


class TightenedMapperEvaluationTests(unittest.TestCase):
    def test_exact_qname_value_period_match_classified_correctly(self):
        row = row_value("Total current assets")
        evaluated = evaluate_candidate_record(candidate(row), row, [fact("ifrs-smes:CurrentAssets")])

        self.assertEqual(evaluated["evaluation_status"], "exact_qname_value_period_match")
        self.assertEqual(classify_evaluation_result(evaluated["evaluation_status"])["risk_level"], "low")

    def test_qname_value_match_with_period_uncertainty_classified_correctly(self):
        row = row_value("Total current assets", year=2025)
        evaluated = evaluate_candidate_record(candidate(row), row, [fact("ifrs-smes:CurrentAssets", year=2024)])

        self.assertEqual(evaluated["evaluation_status"], "qname_value_match_period_uncertain")
        self.assertEqual(classify_evaluation_result(evaluated["evaluation_status"])["result_class"], "match")

    def test_qname_exists_but_value_mismatch_classified_correctly(self):
        row = row_value("Total current assets", value="100")
        evaluated = evaluate_candidate_record(candidate(row), row, [fact("ifrs-smes:CurrentAssets", "200")])

        self.assertEqual(evaluated["evaluation_status"], "qname_exists_but_value_mismatch")
        self.assertTrue(classify_evaluation_result(evaluated["evaluation_status"])["counts_as_false_positive"])

    def test_value_exists_under_different_qname_classified_correctly(self):
        row = row_value("Total current assets", value="100")
        evaluated = evaluate_candidate_record(candidate(row), row, [fact("ifrs-smes:Assets", "100")])

        self.assertEqual(evaluated["evaluation_status"], "value_exists_but_different_qname")
        self.assertTrue(classify_evaluation_result(evaluated["evaluation_status"])["counts_as_false_positive"])

    def test_predicted_qname_missing_classified_correctly(self):
        row = row_value("Total current assets", value="100")
        evaluated = evaluate_candidate_record(candidate(row), row, [fact("ifrs-smes:Assets", "999")])

        self.assertEqual(evaluated["evaluation_status"], "predicted_qname_not_found_in_xbrl")
        self.assertEqual(classify_evaluation_result(evaluated["evaluation_status"])["risk_level"], "critical")

    def test_ambiguous_xbrl_support_classified_correctly(self):
        row = row_value("Total current assets", value="100")
        evaluated = evaluate_candidate_record(
            candidate(row),
            row,
            [
                fact("ifrs-smes:CurrentAssets", "100", fact_id="fact-1"),
                fact("ifrs-smes:CurrentAssets", "100", fact_id="fact-2"),
            ],
        )

        self.assertEqual(evaluated["evaluation_status"], "ambiguous_xbrl_support")
        self.assertTrue(classify_evaluation_result(evaluated["evaluation_status"])["counts_as_ambiguous"])

    def test_blocked_false_positive_classified_as_correctly_blocked(self):
        row = row_value("Total current assets", value="100")
        blocked = candidate(row, qname=None)
        blocked["blocked_dictionary_candidate"] = {
            "dictionary_id": "dict-1",
            "target_qname": "ifrs-smes:CurrentAssets",
            "target_concept_label": "Current Assets",
            "blocking_reasons": ["fixture_block"],
        }

        report = analyze_blocked_candidates(
            [blocked],
            row_values=[row],
            facts_by_sample={row.sample_id: [fact("ifrs-smes:CurrentAssets", "200")]},
        )

        self.assertEqual(report["summary"]["correctly_blocked_false_positive_count"], 1)
        self.assertEqual(report["blocked_candidates"][0]["blocked_candidate_classification"], "correctly_blocked_false_positive")

    def test_blocked_true_positive_classified_as_overblocked(self):
        row = row_value("Total current assets", value="100")
        blocked = candidate(row, qname=None)
        blocked["blocked_dictionary_candidate"] = {
            "dictionary_id": "dict-1",
            "target_qname": "ifrs-smes:CurrentAssets",
            "target_concept_label": "Current Assets",
            "blocking_reasons": ["fixture_block"],
        }

        report = analyze_blocked_candidates(
            [blocked],
            row_values=[row],
            facts_by_sample={row.sample_id: [fact("ifrs-smes:CurrentAssets", "100")]},
        )

        self.assertEqual(report["summary"]["overblocked_true_positive_count"], 1)
        self.assertEqual(report["blocked_candidates"][0]["blocked_candidate_classification"], "overblocked_true_positive")

    def test_source_level_precision_computed_correctly(self):
        rows = [row_value("Revenue", family="income_statement"), row_value("Other income", family="income_statement", value="200")]
        records = [
            candidate(rows[0], "ifrs-smes:Revenue", source="statement_concept_dictionary", status="exact_qname_value_period_match"),
            candidate(rows[1], "ifrs-smes:OtherIncome", source="statement_concept_dictionary", status="qname_exists_but_value_mismatch"),
        ]

        source = {item["name"]: item for item in build_source_metrics(records)}

        self.assertEqual(source["dictionary"]["candidate_count"], 2)
        self.assertEqual(source["dictionary"]["precision_on_evaluable"], 0.5)

    def test_statement_family_precision_computed_correctly(self):
        rows = [row_value("Total current assets"), row_value("Trade receivables")]
        records = [
            candidate(rows[0], status="exact_qname_value_period_match"),
            candidate(rows[1], "ifrs-smes:TradeAndOtherCurrentReceivables", status="value_exists_but_different_qname"),
        ]

        families = {item["name"]: item for item in build_statement_family_metrics(records)}

        self.assertEqual(families["Statement of Financial Position"]["candidate_count"], 2)
        self.assertEqual(families["Statement of Financial Position"]["precision_on_evaluable"], 0.5)

    def test_label_family_precision_computed_correctly(self):
        rows = [row_value("Revenue", family="income_statement"), row_value("Sales", family="income_statement", value="200")]
        records = [
            candidate(rows[0], "ifrs-smes:Revenue", status="exact_qname_value_period_match"),
            candidate(rows[1], "ifrs-smes:Revenue", status="qname_exists_but_value_mismatch"),
        ]

        labels = {item["name"]: item for item in build_label_family_metrics(records)}

        self.assertEqual(labels["revenue"]["candidate_count"], 2)
        self.assertEqual(labels["revenue"]["precision_on_evaluable"], 0.5)

    def test_readiness_matrix_never_recommends_auto_apply(self):
        row = row_value("Revenue", family="income_statement")
        records = [candidate(row, "ifrs-smes:Revenue", status="exact_qname_value_period_match")]
        source = build_source_metrics(records)
        statements = build_statement_family_metrics(records)
        labels = build_label_family_metrics(records)

        matrix = build_readiness_matrix(
            source_metrics=source,
            statement_family_metrics=statements,
            label_family_metrics=labels,
        )

        self.assertFalse(matrix["summary"]["auto_apply_recommended"])
        self.assertTrue(all(entry["auto_apply_recommended"] is False for entry in matrix["matrix"]))
        self.assertTrue(all(entry["confirmed_tag_id_automation_recommended"] is False for entry in matrix["matrix"]))

    def test_raw_xml_gold_and_evaluation_labels_are_excluded_from_reports(self):
        row = row_value("Revenue", family="income_statement")
        record = candidate(row, "ifrs-smes:Revenue", status="exact_qname_value_period_match")
        record.update(
            {
                "raw_xml": "<fact>secret</fact>",
                "gold_answer": "ifrs-smes:Revenue",
                "evaluation_label": "gold",
                "matched_xbrl_value": "100",
            }
        )

        reports = build_tightened_mapper_reports([record], include_not_evaluable=True)
        encoded = json.dumps(reports)

        self.assertNotIn("raw_xml", encoded)
        self.assertNotIn("gold_answer", encoded)
        self.assertNotIn("evaluation_label", encoded)
        self.assertNotIn("matched_xbrl_value", encoded)
        self.assertIn("evaluation_status", encoded)

    def test_reports_serialize_valid_json(self):
        row = row_value("Revenue", family="income_statement")
        reports = build_tightened_mapper_reports(
            [candidate(row, "ifrs-smes:Revenue", status="exact_qname_value_period_match")],
            include_not_evaluable=True,
        )

        with tempfile.TemporaryDirectory() as temp:
            paths = write_reports(reports, output_dir=temp)
            for key, path in paths.items():
                if key.endswith("_json"):
                    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
                    self.assertIn("run_metadata", loaded)


if __name__ == "__main__":
    unittest.main()
