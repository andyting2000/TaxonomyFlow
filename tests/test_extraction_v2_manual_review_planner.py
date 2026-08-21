import json
import unittest

from services.extraction_v2_manual_review_planner import (
    build_manual_review_queue_plan_reports,
    render_data_contract_markdown,
    render_implementation_sequence_markdown,
    render_ui_api_plan_markdown,
)


def sample_inputs():
    policy = {
        "summary": {"conflict_group_count": 2},
        "conflict_group_policy": {"conflict_group_count": 2},
    }
    gate = {
        "summary": {
            "total_original_candidates": 10,
            "total_cleaned_candidates": 9,
        },
        "gate_counts": {
            "auto_mappable_candidate": 3,
            "suggest_mapping_only": 2,
            "manual_review_required": 2,
            "blocked_from_mapping": 1,
            "reference_only_or_context": 1,
        },
        "mapping_candidate_input": {
            "allowed_candidate_count": 5,
            "requires_confirmation_count": 2,
        },
    }
    queue = {
        "queue_items": [
            {"queue_id": "q1", "priority": "critical"},
            {"queue_id": "q2", "priority": "high"},
            {"queue_id": "q3", "priority": "low"},
        ],
        "priority_distribution": {"critical": 1, "high": 1, "low": 1},
    }
    return policy, gate, queue


class ManualReviewPlannerTests(unittest.TestCase):
    def setUp(self):
        self.policy, self.gate, self.queue = sample_inputs()
        self.ui_api, self.contract, self.sequence = build_manual_review_queue_plan_reports(
            self.policy, self.gate, self.queue
        )

    def test_data_contract_includes_required_entities(self):
        names = {entity["name"] for entity in self.contract["entities"]}
        self.assertIn("manual_review_batch", names)
        self.assertIn("manual_review_item", names)
        self.assertIn("conflict_group", names)
        self.assertIn("reviewer_decision", names)
        self.assertIn("mapping_handoff_item", names)

    def test_api_plan_includes_required_endpoint_categories(self):
        endpoints = self.ui_api["api_design"]["endpoints"]
        paths = {endpoint["path"] for endpoint in endpoints}
        methods = {(endpoint["method"], endpoint["path"]) for endpoint in endpoints}
        self.assertIn("/api/v1/extraction-v2/review-batches", paths)
        self.assertIn("/api/v1/extraction-v2/review-batches/{batch_id}", paths)
        self.assertIn("/api/v1/extraction-v2/review-items/{item_id}/decision", paths)
        self.assertIn("/api/v1/extraction-v2/conflict-groups/{group_id}/decision", paths)
        self.assertIn("/api/v1/extraction-v2/review-batches/{batch_id}/mapping-handoff", paths)
        self.assertIn("/api/v1/extraction-v2/review-batches/{batch_id}/summary", paths)
        self.assertIn("/api/v1/extraction-v2/review-batches/{batch_id}/export", paths)
        self.assertIn(("POST", "/api/v1/extraction-v2/review-batches"), methods)

    def test_ui_plan_includes_required_views(self):
        ui = self.ui_api["react_ui_design"]
        self.assertIn("queue_list_view", ui)
        self.assertIn("review_detail_panel", ui)
        self.assertIn("conflict_group_view", ui)
        self.assertIn("reviewer_decision_ui", ui)
        self.assertIn("mapping_handoff_preview", ui)

    def test_candidate_state_transitions_include_required_statuses(self):
        statuses = set(self.ui_api["review_state_transitions"]["candidate_item_statuses"])
        self.assertIn("approved_for_mapping", statuses)
        self.assertIn("rejected", statuses)
        self.assertIn("context_only", statuses)
        self.assertIn("blocked", statuses)
        self.assertIn("needs_manual_taxonomy_mapping", statuses)

    def test_conflict_group_transitions_include_required_statuses(self):
        statuses = set(self.ui_api["review_state_transitions"]["conflict_group_statuses"])
        self.assertIn("resolved_choose_one", statuses)
        self.assertIn("resolved_keep_multiple", statuses)
        self.assertIn("resolved_context_only", statuses)
        self.assertIn("resolved_reject_all", statuses)
        self.assertIn("requires_aggregation_policy", statuses)
        self.assertIn("requires_dimension_policy", statuses)
        self.assertIn("requires_manual_taxonomy_mapping", statuses)

    def test_mapping_handoff_rules_allow_auto_and_confirmed_suggest_only(self):
        rules = self.ui_api["mapping_handoff_rules"]
        allowed = json.dumps(rules["allowed_without_review"] + rules["allowed_with_confirmation"])
        self.assertIn("auto_mappable_candidate", allowed)
        self.assertIn("suggest_mapping_only", allowed)
        self.assertIn("requires_confirmation=true", allowed)

    def test_mapping_handoff_rules_block_unsafe_candidates(self):
        blocked = set(self.ui_api["mapping_handoff_rules"]["blocked_from_handoff"])
        self.assertIn("manual_review_required and unresolved", blocked)
        self.assertIn("blocked_from_mapping", blocked)
        self.assertIn("reference_only_or_context", blocked)
        self.assertIn("suppressed exact duplicate", blocked)
        self.assertIn("downgraded metadata/date/year row", blocked)
        self.assertIn("unresolved conflict group", blocked)

    def test_risk_analysis_includes_mitigations(self):
        risks = self.sequence["risks_and_mitigations"]
        self.assertGreaterEqual(len(risks), 3)
        self.assertTrue(all(item.get("risk") and item.get("mitigation") for item in risks))

    def test_implementation_sequence_has_multiple_future_features(self):
        roadmap = self.sequence["staged_roadmap"]
        self.assertGreaterEqual(len(roadmap), 3)
        self.assertEqual(
            self.sequence["recommended_next_feature"],
            "Feature #13V - Report-based mapping handoff contract with no DB mutation.",
        )

    def test_markdown_reports_render_expected_sections(self):
        ui_md = render_ui_api_plan_markdown(self.ui_api)
        contract_md = render_data_contract_markdown(self.contract)
        sequence_md = render_implementation_sequence_markdown(self.sequence)
        self.assertIn("## Future API Design", ui_md)
        self.assertIn("## Future React UI Design", ui_md)
        self.assertIn("## Proposed Entities", contract_md)
        self.assertIn("## Staged Roadmap", sequence_md)

    def test_json_reports_validate(self):
        json.dumps(self.ui_api)
        json.dumps(self.contract)
        json.dumps(self.sequence)

    def test_metadata_confirms_no_db_mutation(self):
        self.assertFalse(self.ui_api["metadata"]["database_mutated"])
        self.assertFalse(self.contract["metadata"]["database_mutated"])
        self.assertFalse(self.sequence["metadata"]["database_mutated"])

    def test_metadata_confirms_no_live_model_calls(self):
        self.assertFalse(self.ui_api["metadata"]["live_huggingface_calls_made"])
        self.assertFalse(self.ui_api["metadata"]["live_openai_calls_made"])

    def test_metadata_confirms_no_frontend_code_modified(self):
        self.assertFalse(self.ui_api["metadata"]["frontend_code_modified"])
        self.assertFalse(self.ui_api["metadata"]["ui_implemented"])

    def test_metadata_confirms_no_api_routes_implemented(self):
        self.assertFalse(self.ui_api["metadata"]["api_routes_implemented"])

    def test_reference_xml_not_sent_to_model(self):
        self.assertFalse(self.ui_api["metadata"]["reference_xml_sent_to_model"])
        self.assertFalse(self.contract["metadata"]["reference_xml_sent_to_model"])
        self.assertFalse(self.sequence["metadata"]["reference_xml_sent_to_model"])


if __name__ == "__main__":
    unittest.main()
