import json
import tempfile
import unittest
from pathlib import Path

from scripts.evaluate_supervisor_scaffold_17d import write_reports
from services.supervisor_mapping_review import (
    assert_supervisor_payload_is_leakage_safe,
    build_supervisor_prompt,
    build_supervisor_review_payload,
    mock_supervisor_review,
    validate_supervisor_response,
)


def _card(concept, label, *, statement="Statement of Financial Position", families=None, quality="strong"):
    return {
        "concept_qname": concept,
        "template_field_id": concept,
        "canonical_label": label,
        "statement_families_observed": [statement],
        "common_extracted_labels": [label],
        "normalized_label_patterns": [label.lower()],
        "accounting_synonyms": [],
        "semantic_families": list(families or []),
        "typical_value_nature": "positive",
        "common_sections": [statement],
        "example_mappings": [
            {
                "extracted_label": label,
                "statement_type": statement,
                "mapped_concept_qname": concept,
                "mapped_template_field_id": concept,
                "source_case_id": "case_001",
                "evidence_reason": "fixture",
            }
        ],
        "do_not_confuse_with": [],
        "guardrail_notes": [],
        "source_case_ids": ["case_001"],
        "support_count": 3,
        "quality": quality,
    }


def _playbook():
    return {
        "run_metadata": {"feature": "17D-pre", "external_llm_called": False},
        "concept_cards": [
            _card("ifrs-smes:CashAndCashEquivalents", "Cash and cash equivalents", families=["cash"]),
            _card("ifrs-smes:CurrentAssets", "Current assets", families=["asset", "broad_subtotal"]),
            _card(
                "ifrs-smes:CashFlowsFromUsedInOperatingActivities",
                "Cash flows from operating activities",
                statement="Statement of Cash Flows",
                families=["cash", "cash_flow"],
            ),
            _card(
                "ifrs-smes:OtherExpenseByFunction",
                "Other expenses",
                statement="Statement of Comprehensive Income",
                families=["expense"],
            ),
            _card(
                "ssmt-mpers:OtherCurrentMiscellaneousNontradeReceivables",
                "Other current non-trade receivables",
                families=["asset", "receivable"],
            ),
        ],
    }


def _row(label="Cash and cash equivalents", statement="Statement of Financial Position"):
    return {
        "source_case_id": "case_001",
        "extracted_row_id": "row-1",
        "extracted_label": label,
        "extracted_value": "1000",
        "statement_type": statement,
        "row_type": "numeric_fact",
        "page_number": 1,
        "correct_concept_qname": "forbidden:Correct",
        "correct_template_field_id": "forbidden:Correct",
        "auditor_xml": "<xml/>",
        "parsed_xml_fact": {"hidden": True},
        "target_gold_answer": "hidden",
        "evaluation_label": "hidden",
    }


def _mapper(selected="ifrs-smes:CashAndCashEquivalents", *, candidates=None, statement="Statement of Financial Position"):
    if candidates is None:
        candidates = [
            {
                "template_field_id": selected,
                "concept_qname": selected,
                "label": "Cash and cash equivalents",
                "statement_type": statement,
                "deterministic_score": 0.97,
            }
        ]
    return {
        "status": "suggested",
        "predicted_template_field_id": selected,
        "predicted_concept_qname": selected,
        "confidence": 0.97,
        "confidence_tier": "high",
        "reason": "fixture mapper reason",
        "candidate_concepts": candidates,
        "ranked_candidates": [{"template_field_id": selected, "confidence": 0.97, "reason": "top"}],
    }


class SupervisorMappingReviewTests(unittest.TestCase):
    def test_payload_includes_mapper_suggestion_and_retrieved_cards(self):
        row = _row()
        mapper = _mapper()
        payload = build_supervisor_review_payload(row, mapper_suggestion=mapper, playbook=_playbook())

        self.assertEqual(payload["mapper_suggestion"]["selected_template_field_id"], "ifrs-smes:CashAndCashEquivalents")
        self.assertTrue(payload["candidate_concepts"])
        self.assertTrue(payload["retrieved_concept_cards"])

    def test_payload_excludes_auditor_xml_parsed_facts_target_answers_and_evaluation_labels(self):
        payload = build_supervisor_review_payload(_row(), mapper_suggestion=_mapper(), playbook=_playbook())
        text = json.dumps(payload, sort_keys=True).lower()

        assert_supervisor_payload_is_leakage_safe(payload)
        self.assertNotIn("auditor_xml", text)
        self.assertNotIn("parsed_xml_fact", text)
        self.assertNotIn("target_gold_answer", text)
        self.assertNotIn("correct_concept_qname", text)
        self.assertNotIn("correct_template_field_id", text)
        self.assertNotIn("evaluation_label", text)

    def test_prompt_instructs_review_not_mapping_and_returns_json(self):
        payload = build_supervisor_review_payload(_row(), mapper_suggestion=_mapper(), playbook=_playbook())
        prompt = build_supervisor_prompt(payload)

        self.assertIn("reviewing a mapping suggestion", prompt)
        self.assertIn("Do not invent XBRL concepts", prompt)
        self.assertIn("Return strict JSON only", prompt)

    def test_strict_output_schema_validation_accepts_valid_output(self):
        valid = {
            "review_decision": "agree",
            "risk_level": "low",
            "reason": "Supported.",
            "issues": [],
            "recommended_action": "accept",
            "confidence_adjustment": "keep",
            "safe_to_accept": True,
        }

        self.assertEqual(validate_supervisor_response(valid)["review_decision"], "agree")

    def test_strict_output_schema_validation_rejects_invalid_values(self):
        invalid = {
            "review_decision": "maybe",
            "risk_level": "low",
            "reason": "bad",
            "issues": [],
            "recommended_action": "accept",
            "confidence_adjustment": "keep",
            "safe_to_accept": False,
        }

        with self.assertRaises(ValueError):
            validate_supervisor_response(invalid)

    def test_strict_output_schema_rejects_unsafe_accept(self):
        invalid = {
            "review_decision": "needs_human_review",
            "risk_level": "medium",
            "reason": "bad",
            "issues": [{"type": "weak_label_match", "description": "weak"}],
            "recommended_action": "keep_for_human_review",
            "confidence_adjustment": "decrease",
            "safe_to_accept": True,
        }

        normalized = validate_supervisor_response(invalid)
        self.assertFalse(normalized["safe_to_accept"])
        self.assertIn(
            "non_agree_cannot_be_safe_accept",
            normalized["normalization_diagnostics"]["normalization_reasons"],
        )

    def test_broad_substitute_forces_safe_accept_false_and_medium_risk(self):
        response = {
            "review_decision": "agree",
            "risk_level": "low",
            "reason": "Looks close.",
            "issues": [{"type": "broad_substitute", "description": "Too broad."}],
            "recommended_action": "accept",
            "confidence_adjustment": "keep",
            "safe_to_accept": True,
        }

        normalized = validate_supervisor_response(response)

        self.assertEqual(normalized["review_decision"], "agree")
        self.assertEqual(normalized["risk_level"], "medium")
        self.assertEqual(normalized["recommended_action"], "keep_for_human_review")
        self.assertEqual(normalized["confidence_adjustment"], "decrease")
        self.assertFalse(normalized["safe_to_accept"])
        self.assertIn(
            "broad_substitute_requires_human_review",
            normalized["normalization_diagnostics"]["normalization_reasons"],
        )

    def test_ambiguous_label_forces_safe_accept_false_and_medium_risk(self):
        response = {
            "review_decision": "agree",
            "risk_level": "low",
            "reason": "Looks close.",
            "issues": [{"type": "ambiguous_label", "description": "Ambiguous."}],
            "recommended_action": "accept",
            "confidence_adjustment": "keep",
            "safe_to_accept": True,
        }

        normalized = validate_supervisor_response(response)

        self.assertEqual(normalized["risk_level"], "medium")
        self.assertEqual(normalized["recommended_action"], "keep_for_human_review")
        self.assertFalse(normalized["safe_to_accept"])
        self.assertIn(
            "ambiguous_label_requires_human_review",
            normalized["normalization_diagnostics"]["normalization_reasons"],
        )

    def test_candidate_not_supported_forces_safe_accept_false(self):
        response = {
            "review_decision": "agree",
            "risk_level": "low",
            "reason": "Looks close.",
            "issues": [{"type": "candidate_not_supported", "description": "Not in candidates."}],
            "recommended_action": "accept",
            "confidence_adjustment": "keep",
            "safe_to_accept": True,
        }

        normalized = validate_supervisor_response(response)

        self.assertFalse(normalized["safe_to_accept"])
        self.assertIn(
            "issue_type_requires_human_review",
            normalized["normalization_diagnostics"]["normalization_reasons"],
        )

    def test_missing_concept_card_forces_safe_accept_false_unless_obvious_deterministic_evidence(self):
        response = {
            "review_decision": "agree",
            "risk_level": "low",
            "reason": "Looks close.",
            "issues": [{"type": "missing_concept_card", "description": "No card."}],
            "recommended_action": "accept",
            "confidence_adjustment": "keep",
            "safe_to_accept": True,
        }
        weak_payload = build_supervisor_review_payload(
            _row(),
            mapper_suggestion=_mapper(
                candidates=[
                    {
                        "template_field_id": "ifrs-smes:CashAndCashEquivalents",
                        "concept_qname": "ifrs-smes:CashAndCashEquivalents",
                        "label": "Cash and cash equivalents",
                        "statement_type": "Statement of Financial Position",
                        "deterministic_score": 0.70,
                        "deterministic_method": "weak",
                    }
                ]
            ),
            playbook=_playbook(),
        )
        obvious_payload = build_supervisor_review_payload(_row(), mapper_suggestion=_mapper(), playbook=_playbook())

        weak = validate_supervisor_response(response, payload=weak_payload)
        obvious = validate_supervisor_response(response, payload=obvious_payload)

        self.assertFalse(weak["safe_to_accept"])
        self.assertTrue(obvious["safe_to_accept"])

    def test_medium_risk_or_non_accept_action_normalizes_safe_accept_false(self):
        medium = {
            "review_decision": "agree",
            "risk_level": "medium",
            "reason": "Medium risk.",
            "issues": [],
            "recommended_action": "accept",
            "confidence_adjustment": "keep",
            "safe_to_accept": True,
        }
        non_accept = {
            **medium,
            "risk_level": "low",
            "recommended_action": "keep_for_human_review",
        }

        self.assertFalse(validate_supervisor_response(medium)["safe_to_accept"])
        normalized = validate_supervisor_response(non_accept)
        self.assertFalse(normalized["safe_to_accept"])
        self.assertIn(
            "recommended_action_not_accept_cannot_be_safe_accept",
            normalized["normalization_diagnostics"]["normalization_reasons"],
        )

    def test_safe_accept_guardrail_reason_is_visible_when_no_issue_was_returned(self):
        payload = build_supervisor_review_payload(
            _row(),
            mapper_suggestion={
                **_mapper(),
                "confidence": 0.89,
            },
            playbook=_playbook(),
        )
        response = {
            "review_decision": "agree",
            "risk_level": "low",
            "reason": "Supported, but should still be calibrated.",
            "issues": [],
            "recommended_action": "accept",
            "confidence_adjustment": "keep",
            "safe_to_accept": True,
        }

        normalized = validate_supervisor_response(response, payload=payload)

        self.assertFalse(normalized["safe_to_accept"])
        self.assertIn(
            "mapper_confidence_below_safe_threshold",
            normalized["normalization_diagnostics"]["normalization_reasons"],
        )
        self.assertEqual(normalized["issues"][0]["type"], "other")
        self.assertIn("Safe flag withheld by guardrail", normalized["issues"][0]["description"])
        self.assertIn("mapper confidence was below the safe-accept threshold", normalized["issues"][0]["description"])

    def test_strict_output_schema_rejects_replacement_concept_outside_candidates(self):
        payload = build_supervisor_review_payload(_row(), mapper_suggestion=_mapper(), playbook=_playbook())
        invalid = {
            "review_decision": "needs_human_review",
            "risk_level": "medium",
            "reason": "Suggests an unlisted replacement.",
            "issues": [{"type": "weak_label_match", "description": "weak"}],
            "recommended_action": "keep_for_human_review",
            "confidence_adjustment": "decrease",
            "safe_to_accept": False,
            "replacement_concept_qname": "ifrs-smes:InventedConcept",
        }

        with self.assertRaises(ValueError):
            validate_supervisor_response(invalid, payload=payload)

    def test_mock_reviewer_returns_agree_for_strongly_supported_mapping(self):
        payload = build_supervisor_review_payload(_row(), mapper_suggestion=_mapper(), playbook=_playbook())
        review = mock_supervisor_review(payload)

        self.assertEqual(review["review_decision"], "agree")
        self.assertTrue(review["safe_to_accept"])

    def test_mock_reviewer_flags_broad_substitute(self):
        candidates = [
            {
                "template_field_id": "ifrs-smes:CurrentAssets",
                "concept_qname": "ifrs-smes:CurrentAssets",
                "label": "Current assets",
                "statement_type": "Statement of Financial Position",
            }
        ]
        payload = build_supervisor_review_payload(
            _row("Cash and cash equivalents"),
            mapper_suggestion=_mapper("ifrs-smes:CurrentAssets", candidates=candidates),
            playbook=_playbook(),
        )
        review = mock_supervisor_review(payload)

        self.assertIn("broad_substitute", {issue["type"] for issue in review["issues"]})
        self.assertEqual(review["review_decision"], "disagree")

    def test_mock_reviewer_flags_missing_concept_card(self):
        candidates = [
            {
                "template_field_id": "ifrs-smes:ProfitLossBeforeTax",
                "concept_qname": "ifrs-smes:ProfitLossBeforeTax",
                "label": "Profit before tax",
                "statement_type": "Statement of Comprehensive Income",
            }
        ]
        payload = build_supervisor_review_payload(
            _row("Tax expense", "Statement of Comprehensive Income"),
            mapper_suggestion=_mapper("ifrs-smes:ProfitLossBeforeTax", candidates=candidates, statement="Statement of Comprehensive Income"),
            playbook=_playbook(),
        )
        review = mock_supervisor_review(payload)

        self.assertIn("missing_concept_card", {issue["type"] for issue in review["issues"]})
        self.assertEqual(review["review_decision"], "needs_human_review")

    def test_mock_reviewer_flags_statement_family_mismatch(self):
        candidates = [
            {
                "template_field_id": "ifrs-smes:CashFlowsFromUsedInOperatingActivities",
                "concept_qname": "ifrs-smes:CashFlowsFromUsedInOperatingActivities",
                "label": "Cash flows from operating activities",
                "statement_type": "Statement of Cash Flows",
            }
        ]
        payload = build_supervisor_review_payload(
            _row("Cash and cash equivalents", "Statement of Financial Position"),
            mapper_suggestion=_mapper("ifrs-smes:CashFlowsFromUsedInOperatingActivities", candidates=candidates, statement="Statement of Cash Flows"),
            playbook=_playbook(),
        )
        review = mock_supervisor_review(payload)

        self.assertIn("statement_family_mismatch", {issue["type"] for issue in review["issues"]})
        self.assertEqual(review["review_decision"], "disagree")

    def test_mock_reviewer_flags_selected_candidate_not_in_candidates(self):
        candidates = [
            {
                "template_field_id": "ifrs-smes:CurrentAssets",
                "concept_qname": "ifrs-smes:CurrentAssets",
                "label": "Current assets",
                "statement_type": "Statement of Financial Position",
            }
        ]
        payload = build_supervisor_review_payload(
            _row(),
            mapper_suggestion=_mapper("ifrs-smes:CashAndCashEquivalents", candidates=candidates),
            playbook=_playbook(),
        )
        review = mock_supervisor_review(payload)

        self.assertIn("candidate_not_supported", {issue["type"] for issue in review["issues"]})
        self.assertEqual(review["review_decision"], "disagree")

    def test_mock_reviewer_flags_person_or_company_name(self):
        payload = build_supervisor_review_payload(
            _row("ABC SDN BHD"),
            mapper_suggestion=_mapper(
                "ssmt-mpers:OtherCurrentMiscellaneousNontradeReceivables",
                candidates=[
                    {
                        "template_field_id": "ssmt-mpers:OtherCurrentMiscellaneousNontradeReceivables",
                        "concept_qname": "ssmt-mpers:OtherCurrentMiscellaneousNontradeReceivables",
                        "label": "Other current non-trade receivables",
                        "statement_type": "Statement of Financial Position",
                    }
                ],
            ),
            playbook=_playbook(),
        )
        review = mock_supervisor_review(payload)

        self.assertIn("person_or_company_name", {issue["type"] for issue in review["issues"]})

    def test_mock_reviewer_flags_note_number_row(self):
        payload = build_supervisor_review_payload(_row("Note 7"), mapper_suggestion=_mapper(), playbook=_playbook())
        review = mock_supervisor_review(payload)

        self.assertIn("note_number", {issue["type"] for issue in review["issues"]})

    def test_reports_are_generated_and_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_reports(golden_dir="benchmark_mbrs_pairs", reports_dir=tmp, mock=True)
            for path in paths.values():
                self.assertTrue(Path(path).exists())
            scaffold = json.loads(Path(paths["scaffold_json"]).read_text(encoding="utf-8"))
            payloads = json.loads(Path(paths["payload_examples_json"]).read_text(encoding="utf-8"))

        self.assertGreater(scaffold["summary"]["total_reviewed"], 0)
        self.assertFalse(scaffold["run_metadata"]["external_llm_called"])
        self.assertTrue(payloads["payload_examples"])


if __name__ == "__main__":
    unittest.main()
