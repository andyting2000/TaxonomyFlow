import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.azure_di_manual_mapping_review import (
    build_handoff_contract_report,
    build_manual_mapping_review_reports,
    render_contract_markdown,
    render_policy_markdown,
    render_queue_markdown,
    render_summary_markdown,
    run_manual_mapping_review,
)


def suggestion(qname="ssmt:CashAndBankBalances", label="Cash and bank balances", **overrides):
    payload = {
        "concept_qname": qname,
        "concept_label": label,
        "concept_type": overrides.pop("concept_type", "numeric"),
        "statement_family": overrides.pop("statement_family", "financial_position"),
        "is_numeric_concept": overrides.pop("is_numeric_concept", True),
        "is_text_block_concept": overrides.pop("is_text_block_concept", False),
        "score": overrides.pop("score", 0.92),
        "confidence_tier": overrides.pop("confidence_tier", "high"),
        "evidence": overrides.pop(
            "evidence",
            {
                "section_match": True,
                "section_family_mismatch": False,
                "row_type_match": True,
                "concept_type_match": True,
            },
        ),
        "warnings": [],
        "mapping_decision_status": "suggested_only",
        "source": "deterministic_local_metadata",
    }
    payload.update(overrides)
    return payload


def record(mapping_input_id="13V-MAP-0001", **overrides):
    top = overrides.pop("top_suggestion", suggestion())
    suggestions = overrides.pop("suggestions", [top] if top else [])
    payload = {
        "mapping_input_id": mapping_input_id,
        "source_candidate_id": f"source-{mapping_input_id}",
        "case_id": "Shield-Plus",
        "page_number": 7,
        "row_type": "comparative_numeric_fact",
        "label": "Cash and bank balances",
        "value": "100",
        "previous_value": "90",
        "text_preview": "",
        "statement_section": "Statement of Financial Position",
        "gate_status": "auto_mappable_candidate",
        "requires_confirmation": False,
        "mapping_status": "high_confidence_suggestion",
        "top_suggestion": top,
        "suggestions": suggestions,
        "blockers": [],
        "warning_flags": [],
        "audit_trail": {
            "source": "14A",
            "mapping_decision_status": "suggested_only",
            "final_mapping_approved": False,
        },
    }
    payload.update(overrides)
    return payload


def mapping_report(records):
    return {
        "run_metadata": {"database_mutated": False},
        "mapping_record_count": len(records),
        "mapping_records": records,
        "status_counts": {},
    }


def confidence_report():
    return {
        "status_counts": {
            "high_confidence_suggestion": 1,
            "medium_confidence_suggestion": 1,
            "low_confidence_suggestion": 1,
            "ambiguous_multiple_suggestions": 1,
            "no_safe_suggestion": 1,
        },
        "confidence_tier_counts": {"high": 1, "medium": 1, "low": 1, "none": 2},
    }


def gap_report():
    return {
        "labels_with_no_safe_suggestion": [{"mapping_input_id": "no-safe", "label": "No safe"}],
        "labels_still_ambiguous": [{"mapping_input_id": "ambiguous", "label": "Ambiguous"}],
    }


class AzureDIManualMappingReviewTests(unittest.TestCase):
    def build(self, records):
        return build_manual_mapping_review_reports(
            mapping_report=mapping_report(records),
            confidence_report=confidence_report(),
            gap_report=gap_report(),
            run_id="test_14b",
            input_paths={"mapping_report": "memory"},
        )

    def test_high_confidence_mapping_becomes_ready_for_review_approval(self):
        queue, _policy, _contract, _summary = self.build([record()])
        self.assertEqual(queue["queue_items"][0]["workflow_status"], "ready_for_review_approval")

    def test_medium_confidence_suggest_only_mapping_becomes_needs_confirmation(self):
        item = record(
            "medium-suggest",
            mapping_status="medium_confidence_suggestion",
            gate_status="suggest_mapping_only",
            requires_confirmation=True,
            top_suggestion=suggestion(score=0.78, confidence_tier="medium"),
        )
        queue, _policy, _contract, _summary = self.build([item])
        self.assertEqual(queue["queue_items"][0]["workflow_status"], "needs_confirmation")

    def test_ambiguous_mapping_becomes_needs_human_concept_choice(self):
        item = record(
            "ambiguous",
            mapping_status="ambiguous_multiple_suggestions",
            suggestions=[
                suggestion("ssmt:OtherReceivables", "Other receivables", score=0.91),
                suggestion("ifrs-smes:TradeAndOtherReceivables", "Trade and other receivables", score=0.90),
            ],
        )
        queue, _policy, _contract, _summary = self.build([item])
        self.assertEqual(queue["queue_items"][0]["workflow_status"], "needs_human_concept_choice")

    def test_no_safe_mapping_becomes_enrichment_or_blocked(self):
        item = record(
            "no-safe",
            mapping_status="no_safe_suggestion",
            top_suggestion=None,
            suggestions=[],
            blockers=["generic_or_weak_label"],
        )
        queue, _policy, _contract, _summary = self.build([item])
        self.assertIn(queue["queue_items"][0]["workflow_status"], {"needs_alias_or_metadata_enrichment", "blocked_from_xbrl"})

    def test_low_confidence_numeric_mapping_becomes_high_priority(self):
        item = record(
            "low-numeric",
            mapping_status="low_confidence_suggestion",
            top_suggestion=suggestion(score=0.34, confidence_tier="low"),
        )
        queue, _policy, _contract, _summary = self.build([item])
        self.assertEqual(queue["queue_items"][0]["priority"], "high")

    def test_text_block_uncertainty_becomes_medium_priority(self):
        item = record(
            "text-low",
            row_type="text_block",
            value=None,
            previous_value=None,
            label="Directors report",
            mapping_status="low_confidence_suggestion",
            top_suggestion=suggestion(
                "ssmt:DisclosureOfDirectorsReportExplanatory",
                "Disclosure of Director's Report [text block]",
                concept_type="text_block",
                is_numeric_concept=False,
                is_text_block_concept=True,
                score=0.42,
                confidence_tier="low",
            ),
        )
        queue, _policy, _contract, _summary = self.build([item])
        self.assertEqual(queue["queue_items"][0]["priority"], "medium")

    def test_concept_type_mismatch_becomes_blocked_from_xbrl(self):
        item = record(
            "mismatch",
            top_suggestion=suggestion(
                "ssmt:DisclosureOfDirectorsReportExplanatory",
                "Disclosure of Director's Report [text block]",
                concept_type="text_block",
                is_numeric_concept=False,
                is_text_block_concept=True,
                evidence={"section_match": True, "row_type_match": False, "concept_type_match": False},
            ),
        )
        queue, _policy, _contract, _summary = self.build([item])
        self.assertEqual(queue["queue_items"][0]["workflow_status"], "blocked_from_xbrl")

    def test_reviewer_decision_options_include_core_options(self):
        queue, _policy, _contract, _summary = self.build([record()])
        options = set(queue["queue_items"][0]["reviewer_decision_options"])
        self.assertIn("approve_suggested_concept", options)
        self.assertIn("reject_mapping", options)
        self.assertIn("mark_as_context_only", options)
        self.assertIn("request_alias_enrichment", options)
        self.assertIn("require_manual_taxonomy_mapping", options)

    def test_ambiguous_suggestions_preserve_all_concept_options(self):
        suggestions = [
            suggestion("a:ConceptOne", "Concept one", score=0.9),
            suggestion("b:ConceptTwo", "Concept two", score=0.89),
        ]
        queue, _policy, _contract, _summary = self.build(
            [record("ambiguous", mapping_status="ambiguous_multiple_suggestions", suggestions=suggestions, top_suggestion=suggestions[0])]
        )
        self.assertEqual(len(queue["queue_items"][0]["suggestions"]), 2)

    def test_reviewed_mapping_handoff_contract_requires_reviewer_approval(self):
        contract = build_handoff_contract_report(run_id="test", input_paths={})
        rules = " ".join(contract["eligibility_rules"])
        self.assertIn("reviewer-approved", rules)
        self.assertEqual(contract["empty_reviewed_mapping_records"], [])

    def test_high_confidence_suggestion_is_not_marked_final_approved(self):
        queue, _policy, _contract, _summary = self.build([record()])
        self.assertFalse(queue["queue_items"][0]["audit_trail"]["final_mapping_approved"])
        self.assertFalse(queue["run_metadata"]["final_mapping_approved"])

    def test_suggest_only_candidate_remains_requires_confirmation_true(self):
        item = record("suggest", gate_status="suggest_mapping_only", requires_confirmation=True)
        queue, _policy, _contract, _summary = self.build([item])
        self.assertTrue(queue["queue_items"][0]["requires_confirmation"])

    def test_queue_item_preserves_mapping_input_and_source_candidate_ids(self):
        queue, _policy, _contract, _summary = self.build([record("trace")])
        item = queue["queue_items"][0]
        self.assertEqual(item["mapping_input_id"], "trace")
        self.assertEqual(item["source_candidate_id"], "source-trace")

    def test_queue_item_preserves_top_suggestion_and_suggestions(self):
        queue, _policy, _contract, _summary = self.build([record()])
        self.assertEqual(queue["queue_items"][0]["top_suggestion"]["concept_qname"], "ssmt:CashAndBankBalances")
        self.assertEqual(len(queue["queue_items"][0]["suggestions"]), 1)

    def test_summary_counts_workflow_statuses_correctly(self):
        records = [
            record("ready"),
            record("amb", mapping_status="ambiguous_multiple_suggestions"),
            record("confirm", mapping_status="medium_confidence_suggestion", requires_confirmation=True),
        ]
        _queue, _policy, _contract, summary = self.build(records)
        self.assertEqual(summary["total_mapping_records"], 3)
        self.assertEqual(summary["ready_for_review_approval_count"], 1)
        self.assertEqual(summary["needs_human_concept_choice_count"], 1)
        self.assertEqual(summary["needs_confirmation_count"], 1)

    def test_markdown_reports_render_policy_queue_and_contract_sections(self):
        queue, policy, contract, summary = self.build([record()])
        self.assertIn("## Summary", render_queue_markdown(queue))
        self.assertIn("## Workflow Statuses", render_policy_markdown(policy))
        self.assertIn("## Eligibility Rules", render_contract_markdown(contract))
        self.assertIn("## Review Workload", render_summary_markdown(summary))

    def test_no_azure_di_call_is_required(self):
        with patch("services.azure_document_intelligence_provider.AzureDocumentIntelligenceProvider.analyze_pdf_path") as mocked:
            self.build([record()])
        mocked.assert_not_called()

    def test_no_hugging_face_or_openai_call_is_required(self):
        queue, policy, contract, summary = self.build([record()])
        for report in [queue, policy, contract, summary]:
            self.assertFalse(report["run_metadata"]["live_huggingface_calls_made"])
            self.assertFalse(report["run_metadata"]["live_openai_calls_made"])

    def test_no_db_is_required(self):
        queue, policy, contract, summary = self.build([record()])
        for report in [queue, policy, contract, summary]:
            self.assertFalse(report["run_metadata"]["database_mutated"])

    def test_no_xbrl_or_arelle_path_is_invoked(self):
        queue, policy, contract, summary = self.build([record()])
        for report in [queue, policy, contract, summary]:
            self.assertFalse(report["run_metadata"]["xbrl_generated"])
            self.assertFalse(report["run_metadata"]["arelle_validation_run"])

    def test_reference_xml_is_not_sent_to_any_model(self):
        queue, policy, contract, summary = self.build([record()])
        for report in [queue, policy, contract, summary]:
            self.assertFalse(report["run_metadata"]["reference_xml_sent_to_model"])

    def test_no_final_mapping_approval_is_produced(self):
        queue, policy, contract, summary = self.build([record()])
        self.assertFalse(queue["run_metadata"]["final_mapping_approved"])
        self.assertEqual(contract["contract_status"], "future_schema_only_no_approved_mappings")
        self.assertFalse(summary["run_metadata"]["final_mapping_approved"])

    def test_runner_writes_reports_without_live_or_db_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mapping_path = root / "mapping.json"
            confidence_path = root / "confidence.json"
            gap_path = root / "gap.json"
            mapping_path.write_text(json.dumps(mapping_report([record()])), encoding="utf-8")
            confidence_path.write_text(json.dumps(confidence_report()), encoding="utf-8")
            gap_path.write_text(json.dumps(gap_report()), encoding="utf-8")
            result = run_manual_mapping_review(
                mapping_report_path=mapping_path,
                confidence_report_path=confidence_path,
                gap_report_path=gap_path,
                output_prefix=root / "out",
            )
            self.assertTrue(result["paths"].queue_json.exists())
            self.assertFalse(result["queue_report"]["run_metadata"]["database_mutated"])


if __name__ == "__main__":
    unittest.main()

