import unittest

from services.extraction_v2_manual_review_policy import (
    build_manual_review_policy_reports,
    render_gate_markdown,
    render_policy_markdown,
    render_queue_markdown,
)


def candidate(**overrides):
    base = {
        "case_id": "case-a",
        "source_pdf": "case-a.pdf",
        "page_number": 1,
        "extraction_method": "huggingface_vision_fallback",
        "row_type": "numeric_fact",
        "statement_section": "Statement of Financial Position",
        "label": "Cash and bank balances",
        "value": "100",
        "previous_value": "",
        "current_year": 2024,
        "prior_year": 2023,
        "text": "",
        "source_snippet": "Cash and bank balances 100",
        "confidence": 0.8,
        "warnings": [],
        "provenance": {"page_number": 1},
    }
    base.update(overrides)
    return base


def audit_entry(index, cand, **overrides):
    original_id = overrides.pop("original_candidate_id", f"case-a:candidate:{index}:{index}")
    retained = overrides.pop("retained_in_cleaned_rows", True)
    action = overrides.pop("action", cand.get("resolution_action") or "keep")
    cleaned = dict(cand)
    cleaned.setdefault("original_candidate_id", original_id)
    cleaned.setdefault("resolution_action", action)
    entry = {
        "original_candidate_id": original_id,
        "original_global_index": index,
        "original_case_index": index,
        "case_id": cand.get("case_id", "case-a"),
        "page_number": cand.get("page_number", 1),
        "duplicate_group_ids": cleaned.get("duplicate_group_ids", []),
        "original_row_type": cand.get("row_type"),
        "proposed_row_type": cleaned.get("row_type"),
        "original_readiness": overrides.pop("original_readiness", "high"),
        "proposed_readiness": overrides.pop("proposed_readiness", "high"),
        "action": action,
        "action_reasons": [],
        "retained_in_cleaned_rows": retained,
        "original_candidate": dict(cand),
        "cleaned_candidate": cleaned,
    }
    entry.update(overrides)
    return entry


def cleaned_report(entries):
    kept = [entry["cleaned_candidate"] for entry in entries if entry["retained_in_cleaned_rows"]]
    return {
        "run_metadata": {
            "database_mutated": False,
            "reference_xml_sent_to_model": False,
        },
        "case_reports": [
            {
                "case_id": "case-a",
                "candidate_count": len(kept),
                "candidates": kept,
            }
        ],
        "duplicate_resolution": {
            "original_candidate_count": len(entries),
            "cleaned_candidate_count": len(kept),
            "candidate_audit_trail": entries,
        },
    }


def duplicate_report(groups=None):
    return {
        "run_metadata": {
            "database_mutated": False,
            "reference_xml_sent_to_model": False,
        },
        "duplicate_groups": groups or [],
        "aggregate": {},
    }


def conflict_group(*candidate_ids):
    return {
        "group_id": "conflict-0001",
        "group_type": "same_label_conflicting_values",
        "classification": "conflict_review_required",
        "case_id": "case-a",
        "normalized_label": "revenue",
        "label": "Revenue",
        "candidate_count": len(candidate_ids),
        "values": [{"value": "100", "previous_value": ""}, {"value": "200", "previous_value": ""}],
        "page_numbers": [1, 2],
        "statement_sections": ["Statement of Profit or Loss"],
        "candidate_ids": list(candidate_ids),
    }


def readiness_report():
    return {
        "run_metadata": {"database_mutated": False},
        "readiness_comparison": {"after": {"high": 1}},
    }


def build(entries, groups=None):
    return build_manual_review_policy_reports(
        cleaned_report=cleaned_report(entries),
        duplicate_report=duplicate_report(groups),
        readiness_report=readiness_report(),
        input_paths={"cleaned_candidates": "memory"},
        output_paths={"policy": "policy.json", "gate": "gate.json", "queue": "queue.json"},
    )


def gate_record(gate_report, candidate_id):
    for record in gate_report["candidate_gate_records"]:
        if record["original_candidate_id"] == candidate_id:
            return record
    raise AssertionError(candidate_id)


class ExtractionV2ManualReviewPolicyTests(unittest.TestCase):
    def test_high_readiness_clean_numeric_candidate_becomes_auto_mappable(self):
        _policy, gate, _queue = build([audit_entry(0, candidate())])
        record = gate["candidate_gate_records"][0]
        self.assertEqual(record["gate_status"], "auto_mappable_candidate")

    def test_medium_readiness_usable_candidate_becomes_suggest_mapping_only(self):
        cand = candidate(label="trade receivables", row_type="comparative_numeric_fact", previous_value="80", current_year=None, prior_year=None)
        _policy, gate, _queue = build([audit_entry(0, cand, proposed_readiness="medium")])
        record = gate["candidate_gate_records"][0]
        self.assertEqual(record["gate_status"], "suggest_mapping_only")

    def test_conflicting_duplicate_candidate_becomes_manual_review_required(self):
        first = audit_entry(0, candidate(label="Revenue", value="100"), action="mark_conflict_review_required", proposed_readiness="low")
        second = audit_entry(1, candidate(label="Revenue", value="200"), action="mark_conflict_review_required", proposed_readiness="low")
        group = conflict_group(first["original_candidate_id"], second["original_candidate_id"])
        _policy, gate, _queue = build([first, second], [group])
        self.assertEqual(gate_record(gate, first["original_candidate_id"])["gate_status"], "manual_review_required")

    def test_suppressed_exact_duplicate_becomes_blocked_from_mapping(self):
        entry = audit_entry(0, candidate(), action="suppress_exact_duplicate", retained_in_cleaned_rows=False, proposed_readiness="not_ready")
        _policy, gate, _queue = build([entry])
        self.assertEqual(gate["candidate_gate_records"][0]["gate_status"], "blocked_from_mapping")

    def test_downgraded_date_year_candidate_becomes_reference_or_blocked(self):
        cand = candidate(label="As at 31/12/2023", row_type="metadata", value="100")
        entry = audit_entry(0, cand, action="downgrade_to_metadata", proposed_readiness="not_ready")
        _policy, gate, _queue = build([entry])
        self.assertIn(gate["candidate_gate_records"][0]["gate_status"], {"reference_only_or_context", "blocked_from_mapping"})

    def test_heading_like_numeric_fact_becomes_manual_review_required(self):
        entry = audit_entry(0, candidate(label="Assets"), action="manual_review_required", proposed_readiness="low")
        _policy, gate, _queue = build([entry])
        self.assertEqual(gate["candidate_gate_records"][0]["gate_status"], "manual_review_required")

    def test_non_numeric_numeric_candidate_becomes_blocked_from_mapping(self):
        entry = audit_entry(0, candidate(value="not available"), proposed_readiness="low")
        _policy, gate, _queue = build([entry])
        self.assertEqual(gate["candidate_gate_records"][0]["gate_status"], "blocked_from_mapping")

    def test_weak_text_block_label_becomes_review_or_suggest(self):
        text = "Revenue is recognised when control of goods is transferred to the customer and the amount can be measured reliably."
        entry = audit_entry(0, candidate(row_type="text_block", label="", value="", text=text, source_snippet=text), proposed_readiness="medium")
        _policy, gate, _queue = build([entry])
        self.assertIn(gate["candidate_gate_records"][0]["gate_status"], {"manual_review_required", "suggest_mapping_only"})

    def test_missing_statement_section_lowers_gate_status(self):
        entry = audit_entry(0, candidate(statement_section=None), proposed_readiness="medium")
        _policy, gate, _queue = build([entry])
        self.assertEqual(gate["candidate_gate_records"][0]["gate_status"], "manual_review_required")

    def test_conflict_group_preserves_all_candidate_options(self):
        first = audit_entry(0, candidate(label="Revenue", value="100"), action="mark_conflict_review_required", proposed_readiness="low")
        second = audit_entry(1, candidate(label="Revenue", value="200"), action="mark_conflict_review_required", proposed_readiness="low")
        group = conflict_group(first["original_candidate_id"], second["original_candidate_id"])
        _policy, _gate, queue = build([first, second], [group])
        self.assertEqual(len(queue["conflict_groups"][0]["candidate_options"]), 2)

    def test_conflict_group_blocks_auto_mapping(self):
        first = audit_entry(0, candidate(label="Revenue", value="100"), action="mark_conflict_review_required", proposed_readiness="low")
        second = audit_entry(1, candidate(label="Revenue", value="200"), action="mark_conflict_review_required", proposed_readiness="low")
        group = conflict_group(first["original_candidate_id"], second["original_candidate_id"])
        _policy, _gate, queue = build([first, second], [group])
        self.assertTrue(queue["conflict_groups"][0]["blocks_auto_mapping"])

    def test_manual_review_queue_priority_is_critical_for_conflicting_numeric_values(self):
        first = audit_entry(0, candidate(label="Revenue", value="100"), action="mark_conflict_review_required", proposed_readiness="low")
        second = audit_entry(1, candidate(label="Revenue", value="200"), action="mark_conflict_review_required", proposed_readiness="low")
        group = conflict_group(first["original_candidate_id"], second["original_candidate_id"])
        _policy, _gate, queue = build([first, second], [group])
        self.assertEqual(queue["manual_review_queue"][0]["priority"], "critical")

    def test_manual_review_queue_priority_is_high_for_heading_like_numeric_facts(self):
        entry = audit_entry(0, candidate(label="Assets"), action="manual_review_required", proposed_readiness="low")
        _policy, _gate, queue = build([entry])
        self.assertEqual(queue["manual_review_queue"][0]["priority"], "high")

    def test_mapping_candidate_input_contract_excludes_blocked_manual_reference_only(self):
        auto = audit_entry(0, candidate())
        manual = audit_entry(1, candidate(label="Assets"), action="manual_review_required", proposed_readiness="low")
        blocked = audit_entry(2, candidate(value="not available"), proposed_readiness="low")
        context = audit_entry(3, candidate(row_type="metadata", label="2024"), action="downgrade_to_metadata", proposed_readiness="not_ready")
        _policy, gate, _queue = build([auto, manual, blocked, context])
        allowed = gate["mapping_candidate_input_summary"]["allowed_into_13u_count"]
        self.assertEqual(allowed, 1)

    def test_suggest_mapping_only_candidates_require_confirmation_true(self):
        cand = candidate(label="trade receivables", row_type="comparative_numeric_fact", previous_value="80", current_year=None, prior_year=None)
        _policy, gate, _queue = build([audit_entry(0, cand, proposed_readiness="medium")])
        self.assertTrue(gate["candidate_gate_records"][0]["requires_confirmation"])

    def test_auto_mappable_candidate_requires_confirmation_false(self):
        _policy, gate, _queue = build([audit_entry(0, candidate())])
        self.assertFalse(gate["candidate_gate_records"][0]["requires_confirmation"])

    def test_gate_report_counts_are_stable(self):
        entries = [
            audit_entry(0, candidate()),
            audit_entry(1, candidate(value="not available"), proposed_readiness="low"),
        ]
        _policy, gate, _queue = build(entries)
        self.assertEqual(sum(gate["aggregate_gate_counts"].values()), 2)

    def test_markdown_reports_render_policy_and_queue_sections(self):
        policy, gate, queue = build([audit_entry(0, candidate())])
        self.assertIn("Mapping Candidate Input Contract", render_policy_markdown(policy))
        self.assertIn("Mapping Candidate Gate Report", render_gate_markdown(gate))
        self.assertIn("Manual Review Queue", render_queue_markdown(queue))

    def test_no_db_mutation_metadata_is_false(self):
        policy, gate, queue = build([audit_entry(0, candidate())])
        self.assertFalse(policy["run_metadata"]["database_mutated"])
        self.assertFalse(gate["run_metadata"]["database_mutated"])
        self.assertFalse(queue["run_metadata"]["database_mutated"])

    def test_no_live_huggingface_or_openai_call_is_required(self):
        policy, gate, queue = build([audit_entry(0, candidate())])
        self.assertFalse(policy["run_metadata"]["live_huggingface_calls_made"])
        self.assertFalse(gate["run_metadata"]["live_openai_calls_made"])
        self.assertFalse(queue["run_metadata"]["live_huggingface_calls_made"])

    def test_reference_xml_is_not_sent_to_any_model(self):
        policy, gate, queue = build([audit_entry(0, candidate())])
        self.assertFalse(policy["run_metadata"]["reference_xml_sent_to_model"])
        self.assertFalse(gate["run_metadata"]["reference_xml_sent_to_model"])
        self.assertFalse(queue["run_metadata"]["reference_xml_sent_to_model"])

    def test_suppressed_candidates_remain_traceable_in_queue_data(self):
        entry = audit_entry(0, candidate(), action="suppress_exact_duplicate", retained_in_cleaned_rows=False, proposed_readiness="not_ready")
        _policy, _gate, queue = build([entry])
        item = queue["manual_review_queue"][0]
        self.assertEqual(item["original_candidate_id"], entry["original_candidate_id"])
        self.assertFalse(item["retained_in_cleaned_rows"])


if __name__ == "__main__":
    unittest.main()
