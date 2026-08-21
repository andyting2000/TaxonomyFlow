import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from services.fewshot_qwen_mapping import (
    build_baseline_comparison,
    build_fewshot_example_store,
    build_fewshot_qwen_prompt,
    build_guardrail_analysis_report,
    build_guardrail_context,
    deterministic_case_split,
    retrieve_similar_examples,
    write_fewshot_qwen_reports,
)


class FewShotQwenMappingTests(unittest.TestCase):
    def _rows(self):
        return [
            {
                "source_case_id": "case_001",
                "extracted_row_id": "r1",
                "extracted_label": "Revenue",
                "extracted_value": "100",
                "statement_type": "Statement of Profit or Loss",
                "correct_concept_qname": "ifrs-smes:Revenue",
                "correct_template_field_id": "ifrs-smes:Revenue",
                "gold_alignment_evidence": {"value_match": True, "period_match": True, "unit_evidence": True},
            },
            {
                "source_case_id": "case_002",
                "extracted_row_id": "r2",
                "extracted_label": "Other receivables",
                "extracted_value": "200",
                "statement_type": "Statement of Financial Position",
                "correct_concept_qname": "ifrs-smes:TradeAndOtherCurrentReceivables",
                "correct_template_field_id": "ifrs-smes:TradeAndOtherCurrentReceivables",
                "gold_alignment_evidence": {"value_match": True},
            },
            {
                "source_case_id": "case_003",
                "extracted_row_id": "r3",
                "extracted_label": "Other payable",
                "extracted_value": "300",
                "statement_type": "Statement of Financial Position",
                "correct_concept_qname": "ifrs-smes:TradeAndOtherCurrentPayables",
                "correct_template_field_id": "ifrs-smes:TradeAndOtherCurrentPayables",
                "gold_alignment_evidence": {"value_match": True},
            },
        ]

    def _fixture(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        cases = root / "pairs"
        for case_id, label in (("case_001", "Revenue"), ("case_002", "Other receivables")):
            case = cases / case_id
            case.mkdir(parents=True)
            report = root / f"{case_id}.json"
            report.write_text(
                json.dumps(
                    {
                        "candidates": [
                            {
                                "original_candidate_id": f"{case_id}:row",
                                "row_type": "numeric_fact",
                                "label": label,
                                "value": "100",
                                "statement_section": "Statement of Profit or Loss",
                                "page_number": 3,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (case / "metadata.json").write_text(json.dumps({"azure_di_normalized_extraction_report": str(report)}), encoding="utf-8")
        alignment = root / "alignment.json"
        alignment.write_text(
            json.dumps(
                {
                    "alignments": [
                        {
                            "source_case_id": "case_001",
                            "extracted_row_id": "case_001:row",
                            "extracted_label": "Revenue",
                            "extracted_value": "100",
                            "statement_type": "Statement of Profit or Loss",
                            "row_type": "numeric_fact",
                            "alignment_status": "strong",
                            "correct_concept_qname": "ifrs-smes:Revenue",
                            "correct_template_field_id": "ifrs-smes:Revenue",
                            "evidence": {"value_match": True},
                        },
                        {
                            "source_case_id": "case_002",
                            "extracted_row_id": "case_002:row",
                            "extracted_label": "Other receivables",
                            "extracted_value": "100",
                            "statement_type": "Statement of Profit or Loss",
                            "row_type": "numeric_fact",
                            "alignment_status": "strong",
                            "correct_concept_qname": "ifrs-smes:Revenue",
                            "correct_template_field_id": "ifrs-smes:Revenue",
                            "evidence": {"value_match": True},
                        },
                    ],
                    "ambiguous_alignments": [],
                }
            ),
            encoding="utf-8",
        )
        baseline_accuracy = root / "baseline_accuracy.json"
        baseline_accuracy.write_text(json.dumps({"qwen_mapping": {"coverage": 0.5, "accuracy": 0.5, "accuracy_when_predicted": 1.0}}), encoding="utf-8")
        baseline_predictions = root / "baseline_predictions.json"
        baseline_predictions.write_text(
            json.dumps(
                {
                    "strict_scoring_rows": [
                        {
                            "source_case_id": "case_002",
                            "extracted_label": "Other receivables",
                            "statement_type": "Statement of Profit or Loss",
                            "correct_concept_qname": "ifrs-smes:Revenue",
                            "correct_template_field_id": "ifrs-smes:Revenue",
                            "qwen_prediction": {
                                "predicted_concept_qname": None,
                                "predicted_template_field_id": None,
                                "candidate_concepts": [{"template_field_id": "ifrs-smes:Revenue"}],
                            },
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        return root, cases, alignment, baseline_accuracy, baseline_predictions

    def test_holdout_split_is_deterministic(self):
        split = deterministic_case_split(["case_003", "case_001", "case_002"], train_case_count=2)
        self.assertEqual(split["train_cases"], ["case_001", "case_002"])
        self.assertEqual(split["holdout_cases"], ["case_003"])

    def test_retrieval_excludes_target_row_and_holdout_case(self):
        store = build_fewshot_example_store(self._rows(), train_cases=["case_001", "case_002", "case_003"])
        target = {"source_case_id": "case_002", "extracted_row_id": "r2", "extracted_label": "Other receivable", "statement_type": "Statement of Financial Position"}
        examples = retrieve_similar_examples(target_row=target, example_store=store, limit=5)
        self.assertTrue(examples)
        self.assertNotIn("case_002", {row["source_case_id"] for row in examples})
        self.assertNotIn("r2", {row.get("extracted_row_id") for row in examples})

    def test_holdout_case_examples_are_not_in_prompt(self):
        store = build_fewshot_example_store(self._rows(), train_cases=["case_001"])
        target = {"source_case_id": "case_002", "extracted_row_id": "r2", "extracted_label": "Revenue", "statement_type": "Statement of Profit or Loss"}
        examples = retrieve_similar_examples(target_row=target, example_store=store, limit=5)
        self.assertEqual({row["source_case_id"] for row in examples}, {"case_001"})

    def test_retrieval_filters_weak_generic_examples(self):
        rows = [
            {
                "source_case_id": "case_001",
                "extracted_row_id": "generic",
                "extracted_label": "Total liabilities",
                "extracted_value": "999",
                "statement_type": "Statement of Financial Position",
                "correct_concept_qname": "ifrs-smes:Liabilities",
                "correct_template_field_id": "ifrs-smes:Liabilities",
                "gold_alignment_evidence": {"value_match": True},
            },
            {
                "source_case_id": "case_003",
                "extracted_row_id": "specific",
                "extracted_label": "Other receivables",
                "extracted_value": "200",
                "statement_type": "Statement of Financial Position",
                "correct_concept_qname": "ssmt-mpers:OtherCurrentMiscellaneousNontradeReceivables",
                "correct_template_field_id": "ssmt-mpers:OtherCurrentMiscellaneousNontradeReceivables",
                "gold_alignment_evidence": {"value_match": True},
            },
        ]
        store = build_fewshot_example_store(rows, train_cases=["case_001", "case_003"])
        target = {
            "source_case_id": "case_002",
            "extracted_row_id": "target",
            "extracted_label": "Other receivables",
            "statement_type": "Statement of Financial Position",
        }
        examples = retrieve_similar_examples(target_row=target, example_store=store, limit=5)
        self.assertEqual([row["extracted_label"] for row in examples], ["Other receivables"])

    def test_guardrail_context_warns_when_specific_example_concept_is_absent(self):
        context = build_guardrail_context(
            target_row={
                "extracted_label": "Other receivables",
                "statement_type": "Notes to the Financial Statements",
            },
            candidate_concepts=[
                {"template_field_id": "ssmt-mpers:OtherCurrentReceivables", "label": "Other current receivables"},
                {"template_field_id": "ifrs-smes:TradeAndOtherCurrentReceivables", "label": "Trade and other current receivables"},
            ],
            fewshot_examples=[
                {
                    "extracted_label": "Other receivables",
                    "correct_template_field_id": "ssmt-mpers:OtherCurrentMiscellaneousNontradeReceivables",
                    "retrieval_score": 0.89,
                }
            ],
        )
        self.assertEqual(
            context["absent_similar_example_concepts"][0]["example_concept"],
            "ssmt-mpers:OtherCurrentMiscellaneousNontradeReceivables",
        )
        self.assertTrue(any("broader substitute" in warning for warning in context["candidate_warnings"]))
        self.assertTrue(any("broad-substitution risk" in warning for warning in context["candidate_warnings"]))

    def test_prompt_payload_excludes_target_gold_xml_and_evaluation_labels(self):
        target = {
            "source_case_id": "case_002",
            "extracted_row_id": "r2",
            "extracted_label": "Revenue",
            "extracted_value": "100",
            "statement_type": "Statement of Profit or Loss",
            "row_type": "numeric_fact",
            "page_number": 1,
            "correct_concept_qname": "secret:TargetGold",
            "correct_template_field_id": "secret:TargetTemplate",
            "reference_xml": "<xml>secret</xml>",
            "evaluation_label": "correct",
        }
        prompt = build_fewshot_qwen_prompt(
            target_row=target,
            candidate_concepts=[{"template_field_id": "ifrs-smes:Revenue", "label": "Revenue"}],
            fewshot_examples=[{"extracted_label": "Sales", "correct_template_field_id": "ifrs-smes:Revenue"}],
        )
        self.assertNotIn("secret:TargetGold", prompt)
        self.assertNotIn("secret:TargetTemplate", prompt)
        self.assertNotIn("<xml>secret</xml>", prompt)
        self.assertNotIn("evaluation_label", prompt)
        self.assertIn("few_shot_examples", prompt)
        self.assertIn("candidate_concepts", prompt)
        self.assertIn("guardrail_context", prompt)
        self.assertIn("Return strict JSON only", prompt)
        self.assertIn("broader summary concept", prompt)
        self.assertIn("return selected_template_field_id as null", prompt)

    def test_guardrail_analysis_identifies_wrong_rows(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        predictions = root / "predictions.json"
        accuracy = root / "accuracy.json"
        comparison = root / "comparison.json"
        predictions.write_text(
            json.dumps(
                {
                    "strict_scoring_rows": [
                        {
                            "source_case_id": "case_005",
                            "extracted_row_id": "candidate:65:65",
                            "extracted_label": "Other receivables",
                            "statement_type": "Notes to the Financial Statements",
                            "correct_concept_qname": "ssmt-mpers:OtherCurrentMiscellaneousNontradeReceivables",
                            "fewshot_qwen_prediction": {
                                "predicted_concept_qname": "ssmt-mpers:OtherCurrentReceivables",
                                "predicted_template_field_id": "ssmt-mpers:OtherCurrentReceivables",
                                "confidence": 0.97,
                                "confidence_tier": "high",
                                "reason": "Broad receivable analogy",
                                "candidate_concepts": [
                                    {"template_field_id": "ssmt-mpers:OtherCurrentReceivables", "label": "Other current receivables"},
                                    {"template_field_id": "ifrs-smes:TradeAndOtherCurrentReceivables", "label": "Trade and other current receivables"},
                                ],
                                "few_shot_examples": [
                                    {
                                        "source_case_id": "case_003",
                                        "extracted_label": "Other receivables",
                                        "correct_template_field_id": "ssmt-mpers:OtherCurrentMiscellaneousNontradeReceivables",
                                        "retrieval_score": 0.89,
                                    }
                                ],
                            },
                        },
                        {
                            "source_case_id": "case_006",
                            "extracted_row_id": "candidate:16:16",
                            "extracted_label": "Other payable",
                            "statement_type": "Statement of Financial Position",
                            "correct_concept_qname": "ssmt-mpers:CurrentNontradePayables",
                            "fewshot_qwen_prediction": {
                                "predicted_concept_qname": "ifrs-smes:TradeAndOtherCurrentPayables",
                                "predicted_template_field_id": "ifrs-smes:TradeAndOtherCurrentPayables",
                                "confidence": 0.97,
                                "confidence_tier": "high",
                                "reason": "Broad payable analogy",
                                "candidate_concepts": [
                                    {"template_field_id": "ifrs-smes:TradeAndOtherCurrentPayables", "label": "Trade and other current payables"}
                                ],
                                "few_shot_examples": [],
                            },
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        accuracy.write_text(
            json.dumps(
                {
                    "strict_scoring_rows": 29,
                    "fewshot_qwen_mapping": {
                        "predicted_rows": 23,
                        "coverage": 0.7931,
                        "correct": 20,
                        "accuracy": 0.6897,
                        "accuracy_when_predicted": 0.8696,
                        "wrong_concept": 3,
                        "no_prediction": 5,
                    },
                }
            ),
            encoding="utf-8",
        )
        comparison.write_text(
            json.dumps(
                {
                    "baseline_qwen_same_holdout": {"coverage": 0.5517},
                    "delta_vs_same_holdout_baseline": {"coverage": 0.2414},
                }
            ),
            encoding="utf-8",
        )
        analysis, guardrail_comparison = build_guardrail_analysis_report(
            predictions_report_path=predictions,
            accuracy_report_path=accuracy,
            comparison_report_path=comparison,
        )
        self.assertEqual(analysis["summary"]["wrong_concept_rows"], 2)
        self.assertEqual(analysis["summary"]["candidate_missing_wrong_rows"], 2)
        self.assertEqual(analysis["summary"]["broad_substitution_wrong_rows"], 2)
        self.assertEqual(
            {row["likely_error_source"] for row in analysis["wrong_concept_rows"]},
            {"candidate_missing_broad_substitution"},
        )
        self.assertFalse(analysis["run_metadata"]["external_llm_called"])
        self.assertEqual(guardrail_comparison["projected_after_guardrails"]["wrong_concept"], 1)

    def test_hallucinated_selected_template_field_is_rejected(self):
        class HallucinatingClient:
            async def complete(self, prompt, *, config):
                return {
                    "selected_template_field_id": "fake:Invented",
                    "confidence": 0.99,
                    "reason": "Invented",
                    "ranked_candidates": [],
                    "requires_human_confirmation": True,
                    "rejection_reason": None,
                }

        root, cases, alignment, baseline_accuracy, baseline_predictions = self._fixture()
        result = asyncio.run(
            write_fewshot_qwen_reports(
                golden_dir=cases,
                output_dir=root / "reports",
                alignment_report_path=alignment,
                baseline_accuracy_report_path=baseline_accuracy,
                baseline_predictions_report_path=baseline_predictions,
                use_live_llm=True,
                llm_client=HallucinatingClient(),
                train_case_count=1,
                rate_limit_backoff_seconds=0,
            )
        )
        self.assertEqual(result["accuracy"]["fewshot_qwen_mapping"]["hallucinated_concept_rejected"], 1)

    def test_baseline_comparison_report_renders(self):
        report = build_baseline_comparison(
            metadata={"external_llm_called": False},
            fewshot_score={"coverage": 0.7, "accuracy": 0.6, "accuracy_when_predicted": 0.9, "wrong_concept": 1, "no_prediction": 2, "correct": 6},
            baseline_full={"coverage": 0.6, "accuracy": 0.5, "accuracy_when_predicted": 0.8, "wrong_concept": 2, "no_prediction": 3, "correct": 5},
            baseline_holdout={"coverage": 0.5, "accuracy": 0.4, "accuracy_when_predicted": 0.8, "wrong_concept": 1, "no_prediction": 4, "correct": 4},
            holdout_rows=10,
        )
        self.assertEqual(report["delta_vs_same_holdout_baseline"]["coverage"], 0.2)

    def test_reports_render_json_and_markdown_without_db_mutation(self):
        root, cases, alignment, baseline_accuracy, baseline_predictions = self._fixture()
        result = asyncio.run(
            write_fewshot_qwen_reports(
                golden_dir=cases,
                output_dir=root / "reports",
                alignment_report_path=alignment,
                baseline_accuracy_report_path=baseline_accuracy,
                baseline_predictions_report_path=baseline_predictions,
                use_live_llm=False,
                train_case_count=1,
            )
        )
        self.assertFalse(result["accuracy"]["run_metadata"]["database_mutated"])
        self.assertFalse(result["accuracy"]["run_metadata"]["external_llm_called"])
        self.assertFalse(result["accuracy"]["run_metadata"]["auditor_xml_sent_to_external_provider"])
        for path in result["paths"].values():
            self.assertTrue(Path(path).exists())


if __name__ == "__main__":
    unittest.main()
