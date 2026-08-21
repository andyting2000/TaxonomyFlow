import json
import tempfile
import unittest
from pathlib import Path

from services.mapper_comparison_analysis import (
    build_reports,
    compare_records,
    load_deterministic_report,
    load_qwen_report,
    normalize_deterministic_record,
    write_reports,
)


def deterministic_row(row_id, label, value, qname=None, *, family="financial_position", bucket=None):
    return {
        "sample_id": "case_005",
        "company_name": "Example Sdn. Bhd.",
        "pdf_row_id": row_id,
        "pdf_label": label,
        "normalized_label": label.lower(),
        "pdf_value": value,
        "pdf_statement_family": family,
        "pdf_statement_type": {
            "financial_position": "Statement of Financial Position",
            "income_statement": "Statement of Comprehensive Income",
            "cash_flow": "Statement of Cash Flows",
        }.get(family, "Notes to the Financial Statements"),
        "pdf_period": {"value_role": row_id.rsplit(":", 1)[-1], "expected_year": 2024},
        "suggestion_source": "pdf_xbrl_rulebook",
        "predicted_qname": qname,
        "confidence_bucket": bucket or ("advisory_high" if qname else "no_match"),
        "confidence_score": 0.97 if qname else 0.0,
        "safe_for_auto_apply": False,
        "requires_human_review": True,
        "match_reasons": ["fixture"] if qname else [],
        "blocking_reasons": [] if qname else ["no matching hardened rule"],
        "row_context": {
            "statement_family": family,
            "row_role": "component",
            "is_notes_context": False,
        },
        "evaluation_status": "exact_qname_value_period_match" if qname else "not_evaluable",
        "xbrl_support_status": "supported" if qname else "no_prediction",
    }


def qwen_strict_row(row_id, label, value, qname=None, *, previous_value=None, statement="Statement of Financial Position"):
    prediction = {
        "status": "suggested" if qname else "rejected",
        "predicted_concept_qname": qname,
        "predicted_template_field_id": qname,
        "confidence": 0.96 if qname else 0.0,
        "confidence_tier": "high" if qname else None,
        "reason": "fixture reason" if qname else "no_safe_mapping_returned_by_model",
    }
    return {
        "source_case_id": "case_005",
        "extracted_row_id": row_id,
        "extracted_label": label,
        "extracted_value": value,
        "previous_value": previous_value,
        "statement_type": statement,
        "correct_concept_qname": qname or "ifrs-smes:SomeExpectedConcept",
        "correct_template_field_id": qname or "ifrs-smes:SomeExpectedConcept",
        "fewshot_qwen_prediction": prediction,
    }


class MapperComparisonAnalysisTests(unittest.TestCase):
    def test_loads_reports_expands_qwen_periods_and_compares_metrics(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            deterministic_path = root / "deterministic.json"
            qwen_path = root / "golden_mbrs_fewshot_qwen_predictions_17b.json"
            deterministic_path.write_text(
                json.dumps(
                    {
                        "run_metadata": {"feature": "18E-B"},
                        "summary": {"total_pdf_row_value_observations": 5},
                        "suggestions": [
                            deterministic_row(
                                "case_005:candidate:14:14:current",
                                "Property, plant and equipment",
                                "822238",
                                "ifrs-smes:PropertyPlantAndEquipment",
                            ),
                            deterministic_row(
                                "case_005:candidate:15:15:current",
                                "Revenue",
                                "1000",
                                "ifrs-smes:Revenue",
                            ),
                            deterministic_row("case_005:candidate:16:16:current", "Other payable", "200"),
                            deterministic_row("case_005:candidate:17:17:current", "Accruals", "300"),
                            deterministic_row(
                                "case_005:candidate:18:18:current",
                                "Bank balances",
                                "400",
                                "ifrs-smes:CashAndCashEquivalents",
                            ),
                        ],
                    }
                ),
                encoding="utf-8",
            )
            qwen_path.write_text(
                json.dumps(
                    {
                        "strict_scoring_rows": [
                            qwen_strict_row(
                                "case_005:candidate:14:14",
                                "Property, plant and equipment",
                                "822238",
                                "ifrs-smes:PropertyPlantAndEquipment",
                                previous_value="843687",
                            ),
                            qwen_strict_row("case_005:candidate:15:15", "Revenue", "1000", "ifrs-smes:Revenue"),
                            qwen_strict_row(
                                "case_005:candidate:16:16",
                                "Other payable",
                                "200",
                                "ifrs-smes:TradeAndOtherCurrentPayables",
                            ),
                            qwen_strict_row("case_005:candidate:17:17", "Accruals", "300", None),
                            qwen_strict_row(
                                "case_005:candidate:18:18",
                                "Bank balances",
                                "400",
                                "ifrs-smes:IncreaseDecreaseInCashAndCashEquivalents",
                                statement="Statement of Cash Flows",
                            ),
                        ]
                    }
                ),
                encoding="utf-8",
            )

            deterministic = load_deterministic_report(deterministic_path)
            qwen = load_qwen_report(qwen_report=qwen_path)
            reports = build_reports(deterministic, qwen)
            summary = reports["summary"]["summary"]

        self.assertEqual(len(qwen["records"]), 6)
        self.assertEqual(summary["total_observations"], 5)
        self.assertEqual(summary["deterministic_touched"], 3)
        self.assertEqual(summary["qwen_touched"], 4)
        self.assertEqual(summary["both_agree_same_qname"], 2)
        self.assertEqual(summary["both_suggest_conflict"], 1)
        self.assertEqual(summary["qwen_only"], 1)
        self.assertEqual(summary["both_no_match"], 1)
        self.assertEqual(summary["combined_touched"], 4)
        self.assertEqual(summary["conflict_type_counts"]["balance_sheet_vs_cash_flow_confusion"], 1)
        self.assertFalse(reports["hybrid_policy"]["summary"]["safe_for_auto_apply"])
        self.assertTrue(reports["hybrid_policy"]["summary"]["human_review_final"])

    def test_missing_qwen_report_is_graceful_when_allowed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            deterministic_path = root / "deterministic.json"
            deterministic_path.write_text(
                json.dumps({"suggestions": [deterministic_row("case_005:candidate:1:1:current", "Revenue", "100")]}),
                encoding="utf-8",
            )
            deterministic = load_deterministic_report(deterministic_path)
            qwen = load_qwen_report(report_dir=root / "missing", allow_missing=True)
            reports = build_reports(deterministic, qwen)

        self.assertEqual(qwen["status"], "missing")
        self.assertEqual(reports["summary"]["summary"]["qwen_report_status"], "missing")
        self.assertIn("18E-C-prep", reports["summary"]["recommendation"]["recommended_next_feature"])

    def test_ambiguous_alignment_is_not_comparable(self):
        det = normalize_deterministic_record(
            deterministic_row("case_005:candidate:99:99:current", "Other income", "123"),
            index=0,
        )
        qwen_records = [
            {
                "sample_id": "case_005",
                "row_id": "case_005:other-a:current",
                "base_row_id": "case_005:other-a",
                "normalized_label": "other income",
                "value_key": "123",
                "statement_family": "income_statement",
                "qname": "ifrs-smes:OtherIncome",
                "status": "suggested",
                "comparable": True,
            },
            {
                "sample_id": "case_005",
                "row_id": "case_005:other-b:current",
                "base_row_id": "case_005:other-b",
                "normalized_label": "other income",
                "value_key": "123",
                "statement_family": "income_statement",
                "qname": "ifrs-smes:OtherGainsLosses",
                "status": "suggested",
                "comparable": True,
            },
        ]

        records, _ = compare_records([det], qwen_records)

        self.assertEqual(records[0]["qwen_alignment_status"], "ambiguous_alignment")
        self.assertEqual(records[0]["comparison_status"], "not_comparable")
        self.assertEqual(records[0]["qwen_status"], "ambiguous_alignment")

    def test_write_reports_outputs_requested_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            deterministic = {
                "status": "loaded",
                "source_file": "det.json",
                "records": [
                    normalize_deterministic_record(
                        deterministic_row("case_005:candidate:1:1:current", "Revenue", "100", "ifrs-smes:Revenue"),
                        index=0,
                    )
                ],
            }
            qwen = {"status": "missing", "source_file": None, "source_format": None, "records": []}
            reports = build_reports(deterministic, qwen)
            paths = write_reports(reports, output_dir=root)

            for key in (
                "comparison_json",
                "summary_json",
                "conflicts_json",
                "uncovered_json",
                "hybrid_policy_json",
            ):
                payload = json.loads(Path(paths[key]).read_text(encoding="utf-8"))
                self.assertIn("run_metadata", payload)
            self.assertTrue((root / "hybrid_mapper_policy_18e_c.md").exists())


if __name__ == "__main__":
    unittest.main()

