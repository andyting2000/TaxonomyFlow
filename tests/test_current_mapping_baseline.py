import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from services.current_mapping_baseline import (
    build_qwen_prompt_for_record,
    load_golden_prediction_inputs,
    score_prediction_records,
    write_current_mapping_baseline_reports,
)


class CurrentMappingBaselineTests(unittest.TestCase):
    def _record(self, *, expected="ifrs-smes:Revenue", predicted="ifrs-smes:Revenue", candidates=None):
        return {
            "extracted_label": "Revenue",
            "statement_type": "Statement of Profit or Loss",
            "correct_concept_qname": expected,
            "correct_template_field_id": expected,
            "deterministic_prediction": {
                "predicted_concept_qname": predicted,
                "predicted_template_field_id": predicted,
                "candidate_concepts": candidates if candidates is not None else [{"template_field_id": expected}],
                "confidence_tier": "high",
            },
        }

    def _fixture(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        cases = root / "pairs"
        case = cases / "case_001"
        case.mkdir(parents=True)
        report = root / "normalized.json"
        report.write_text(
            json.dumps(
                {
                    "candidates": [
                        {
                            "original_candidate_id": "row-1",
                            "row_type": "numeric_fact",
                            "label": "Revenue",
                            "value": "100",
                            "statement_section": "Statement of Profit or Loss",
                            "page_number": 7,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (case / "metadata.json").write_text(
            json.dumps({"azure_di_normalized_extraction_report": str(report)}),
            encoding="utf-8",
        )
        alignment = root / "alignment.json"
        alignment.write_text(
            json.dumps(
                {
                    "alignments": [
                        {
                            "source_case_id": "case_001",
                            "extracted_row_id": "row-1",
                            "extracted_label": "Revenue",
                            "extracted_value": "100",
                            "statement_type": "Statement of Profit or Loss",
                            "row_type": "numeric_fact",
                            "alignment_status": "strong",
                            "correct_concept_qname": "ifrs-smes:Revenue",
                            "correct_template_field_id": "ifrs-smes:Revenue",
                        }
                    ],
                    "ambiguous_alignments": [
                        {
                            "source_case_id": "case_001",
                            "extracted_row_id": "row-2",
                            "extracted_label": "Amount",
                            "alignment_status": "ambiguous",
                            "reason": "multiple_plausible_reference_facts",
                            "candidate_facts": [{}, {}],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return root, cases, alignment

    def test_exact_qname_scoring(self):
        result = score_prediction_records([self._record()], predictor="deterministic")
        self.assertEqual(result["correct"], 1)
        self.assertEqual(result["accuracy"], 1.0)
        self.assertEqual(result["qname_exact_accuracy"], 1.0)
        self.assertEqual(result["template_field_id_exact_accuracy"], 1.0)

    def test_no_prediction_is_separate_from_wrong_concept(self):
        records = [
            self._record(predicted=None),
            self._record(predicted="ifrs-smes:Assets"),
        ]
        result = score_prediction_records(records, predictor="deterministic")
        self.assertEqual(result["no_prediction"], 1)
        self.assertEqual(result["wrong_concept"], 1)

    def test_candidate_missing_is_reported_separately(self):
        result = score_prediction_records(
            [self._record(predicted=None, candidates=[{"template_field_id": "ifrs-smes:Assets"}])],
            predictor="deterministic",
        )
        self.assertEqual(result["candidate_missing"], 1)
        self.assertEqual(result["no_prediction"], 1)

    def test_ambiguous_alignments_are_excluded_from_strict_scoring(self):
        _root, cases, alignment = self._fixture()
        strict, ambiguous, _metadata = load_golden_prediction_inputs(
            golden_dir=cases,
            alignment_report_path=alignment,
        )
        self.assertEqual(len(strict), 1)
        self.assertEqual(len(ambiguous), 1)
        self.assertEqual(strict[0]["page_number"], 7)

    def test_qwen_prompt_excludes_xml_and_gold_answers(self):
        row = {
            "source_case_id": "case_001",
            "extracted_row_id": "row-1",
            "extracted_label": "Revenue",
            "extracted_value": "100",
            "statement_type": "Statement of Profit or Loss",
            "row_type": "numeric_fact",
            "page_number": 7,
            "correct_concept_qname": "secret:GoldAnswer",
            "reference_xml": "<secret>auditor XML</secret>",
        }
        prompt = build_qwen_prompt_for_record(
            row,
            [{"template_field_id": "ifrs-smes:Revenue", "label": "Revenue"}],
        )
        self.assertNotIn("secret:GoldAnswer", prompt)
        self.assertNotIn("auditor XML", prompt)
        self.assertNotIn("correct_concept_qname", prompt)
        self.assertIn("ifrs-smes:Revenue", prompt)

    def test_no_live_reports_render_json_and_markdown_without_db_mutation(self):
        root, cases, alignment = self._fixture()
        output = root / "reports"
        result = asyncio.run(
            write_current_mapping_baseline_reports(
                golden_dir=cases,
                output_dir=output,
                alignment_report_path=alignment,
                use_live_llm=False,
            )
        )
        self.assertFalse(result["accuracy"]["run_metadata"]["database_mutated"])
        self.assertFalse(result["accuracy"]["run_metadata"]["external_llm_called"])
        self.assertFalse(result["accuracy"]["run_metadata"]["auditor_xml_sent_to_external_provider"])
        self.assertEqual(result["accuracy"]["qwen_mapping"]["status"], "blocked_live_llm_not_approved")
        for path in result["paths"].values():
            self.assertTrue(Path(path).exists())

    def test_rate_limit_partial_results_are_saved_safely(self):
        class RateLimitedClient:
            def __init__(self):
                self.calls = 0

            async def complete(self, prompt, *, config):
                self.calls += 1
                raise RuntimeError("429 Too Many Requests")

        root, cases, alignment = self._fixture()
        output = root / "reports"
        client = RateLimitedClient()
        result = asyncio.run(
            write_current_mapping_baseline_reports(
                golden_dir=cases,
                output_dir=output,
                alignment_report_path=alignment,
                use_live_llm=True,
                llm_client=client,
                max_rate_limit_retries=1,
                rate_limit_backoff_seconds=0,
            )
        )
        qwen = result["accuracy"]["qwen_mapping"]
        self.assertEqual(client.calls, 2)
        self.assertEqual(qwen["status"], "blocked_rate_limited")
        self.assertEqual(qwen["rows_blocked_by_rate_limit"], 1)
        self.assertEqual(qwen["provider_rate_limit_events"], 2)
        self.assertTrue(result["accuracy"]["run_metadata"]["external_llm_called"])
        self.assertTrue(Path(result["paths"]["predictions_json"]).exists())

    def test_hallucinated_live_concept_is_rejected(self):
        class HallucinatingClient:
            async def complete(self, prompt, *, config):
                return {
                    "selected_template_field_id": "fake:InventedConcept",
                    "confidence": 0.99,
                    "reason": "Invented value",
                    "ranked_candidates": [],
                    "requires_human_confirmation": True,
                    "rejection_reason": None,
                }

        root, cases, alignment = self._fixture()
        result = asyncio.run(
            write_current_mapping_baseline_reports(
                golden_dir=cases,
                output_dir=root / "reports",
                alignment_report_path=alignment,
                use_live_llm=True,
                llm_client=HallucinatingClient(),
                rate_limit_backoff_seconds=0,
            )
        )
        self.assertEqual(result["accuracy"]["qwen_mapping"]["hallucinated_concept_rejected"], 1)


if __name__ == "__main__":
    unittest.main()
