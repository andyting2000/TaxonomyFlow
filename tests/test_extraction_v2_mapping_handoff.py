import json
import unittest
from copy import deepcopy

from services.extraction_v2_mapping_handoff import (
    build_mapping_handoff_reports,
    render_candidates_markdown,
    render_contract_markdown,
    render_validation_markdown,
    validate_mapping_handoff,
)


def gate_record(candidate_id="cand-1", **overrides):
    base = {
        "case_id": "case-a",
        "page_number": 1,
        "candidate_id": candidate_id,
        "original_candidate_id": candidate_id,
        "label": "Cash and bank balances",
        "value": "100",
        "previous_value": "",
        "text_preview": "Cash and bank balances",
        "statement_section": "Statement of Financial Position",
        "row_type": "numeric_fact",
        "source": "huggingface_vision_fallback",
        "source_snippet": "Cash and bank balances 100",
        "retained_in_cleaned_rows": True,
        "resolution_action": "keep",
        "duplicate_group_ids": [],
        "readiness": "high",
        "gate_status": "auto_mappable_candidate",
        "requires_confirmation": False,
        "review_reasons": [],
        "warning_flags": [],
        "source_provenance": {
            "extraction_method": "huggingface_vision_fallback",
            "source_pdf": "case-a.pdf",
            "page_number": 1,
            "confidence": 0.9,
            "provenance": {"page_number": 1},
        },
    }
    base.update(overrides)
    return base


def cleaned_report(records):
    candidates = []
    audit = []
    for index, record in enumerate(records):
        cand = {
            "case_id": record.get("case_id"),
            "source_pdf": "case-a.pdf",
            "page_number": record.get("page_number"),
            "extraction_method": record.get("source"),
            "row_type": record.get("row_type"),
            "statement_section": record.get("statement_section"),
            "label": record.get("label"),
            "value": record.get("value"),
            "previous_value": record.get("previous_value"),
            "text": record.get("text_preview") if record.get("row_type") == "text_block" else "",
            "source_snippet": record.get("source_snippet"),
            "warnings": record.get("warning_flags", []),
            "provenance": {"page_number": record.get("page_number")},
            "original_candidate_id": record.get("original_candidate_id"),
            "resolution_action": record.get("resolution_action", "keep"),
            "duplicate_group_ids": record.get("duplicate_group_ids", []),
        }
        if record.get("retained_in_cleaned_rows", True):
            candidates.append(cand)
        audit.append(
            {
                "original_candidate_id": record.get("original_candidate_id"),
                "original_global_index": index,
                "original_case_index": index,
                "case_id": record.get("case_id"),
                "page_number": record.get("page_number"),
                "duplicate_group_ids": record.get("duplicate_group_ids", []),
                "original_row_type": record.get("row_type"),
                "proposed_row_type": record.get("row_type"),
                "original_readiness": record.get("readiness", "high"),
                "proposed_readiness": record.get("readiness", "high"),
                "action": record.get("resolution_action", "keep"),
                "action_reasons": [],
                "retained_in_cleaned_rows": record.get("retained_in_cleaned_rows", True),
                "original_candidate": deepcopy(cand),
                "cleaned_candidate": deepcopy(cand),
            }
        )
    return {
        "run_metadata": {"database_mutated": False, "reference_xml_sent_to_model": False},
        "case_reports": [{"case_id": "case-a", "candidates": candidates}],
        "duplicate_resolution": {
            "original_candidate_count": len(records),
            "cleaned_candidate_count": len(candidates),
            "candidate_audit_trail": audit,
        },
    }


def gate_report(records):
    counts = {
        "auto_mappable_candidate": 0,
        "suggest_mapping_only": 0,
        "manual_review_required": 0,
        "blocked_from_mapping": 0,
        "reference_only_or_context": 0,
    }
    for record in records:
        counts[record["gate_status"]] = counts.get(record["gate_status"], 0) + 1
    return {
        "run_metadata": {"database_mutated": False},
        "total_original_candidates": len(records),
        "total_cleaned_candidates": sum(1 for item in records if item.get("retained_in_cleaned_rows", True)),
        "aggregate_gate_counts": counts,
        "mapping_candidate_input_summary": {
            "allowed_into_13u_count": counts["auto_mappable_candidate"] + counts["suggest_mapping_only"],
            "requires_confirmation_count": counts["suggest_mapping_only"],
            "blocked_from_13u_count": counts["manual_review_required"]
            + counts["blocked_from_mapping"]
            + counts["reference_only_or_context"],
        },
        "candidate_gate_records": records,
    }


def review_queue(items=None, conflicts=None):
    return {
        "run_metadata": {"database_mutated": False},
        "manual_review_queue": items or [],
        "conflict_groups": conflicts or [],
    }


def build(records, queue=None):
    return build_mapping_handoff_reports(
        cleaned_report=cleaned_report(records),
        mapping_gate_report=gate_report(records),
        manual_review_queue=queue or review_queue(),
        data_contract={},
        ui_api_plan={},
        input_paths={"cleaned_candidates": "memory"},
    )


class ExtractionV2MappingHandoffTests(unittest.TestCase):
    def test_auto_mappable_candidate_is_included_without_confirmation(self):
        candidates, validation, _contract = build([gate_record()])
        self.assertEqual(candidates["total_handoff_candidates"], 1)
        self.assertFalse(candidates["handoff_items"][0]["requires_confirmation"])
        self.assertTrue(validation["validation_passed"])

    def test_suggest_mapping_only_is_included_with_confirmation(self):
        record = gate_record("cand-2", gate_status="suggest_mapping_only", requires_confirmation=True, readiness="medium")
        candidates, _validation, _contract = build([record])
        self.assertEqual(candidates["total_handoff_candidates"], 1)
        self.assertTrue(candidates["handoff_items"][0]["requires_confirmation"])

    def test_manual_review_required_is_excluded(self):
        candidates, _validation, _contract = build([gate_record(gate_status="manual_review_required")])
        self.assertEqual(candidates["total_handoff_candidates"], 0)
        self.assertIn("excluded_gate_status:manual_review_required", candidates["exclusion_ledger"][0]["reason_codes"])

    def test_blocked_from_mapping_is_excluded(self):
        candidates, _validation, _contract = build([gate_record(gate_status="blocked_from_mapping")])
        self.assertEqual(candidates["total_handoff_candidates"], 0)

    def test_reference_only_or_context_is_excluded(self):
        candidates, _validation, _contract = build([gate_record(gate_status="reference_only_or_context", row_type="metadata")])
        self.assertEqual(candidates["total_handoff_candidates"], 0)

    def test_suppressed_candidate_is_excluded(self):
        record = gate_record(
            retained_in_cleaned_rows=False,
            resolution_action="suppress_exact_duplicate",
        )
        candidates, _validation, _contract = build([record])
        self.assertEqual(candidates["total_handoff_candidates"], 0)
        self.assertIn("suppressed_candidate", candidates["exclusion_ledger"][0]["reason_codes"])

    def test_unresolved_conflict_candidate_is_excluded(self):
        record = gate_record("cand-conflict", duplicate_group_ids=["conflict-0001"])
        conflict = {
            "conflict_group_id": "conflict-0001",
            "blocks_auto_mapping": True,
            "candidate_options": [{"candidate_id": "cand-conflict"}],
        }
        candidates, _validation, _contract = build([record], review_queue(conflicts=[conflict]))
        self.assertEqual(candidates["total_handoff_candidates"], 0)
        self.assertIn("unresolved_conflict", candidates["exclusion_ledger"][0]["reason_codes"])

    def test_numeric_candidate_with_non_numeric_value_is_excluded(self):
        candidates, _validation, _contract = build([gate_record(value="not available")])
        self.assertEqual(candidates["total_handoff_candidates"], 0)
        self.assertIn("non_numeric_numeric_value", candidates["exclusion_ledger"][0]["reason_codes"])

    def test_text_block_with_sufficient_text_is_included_if_gate_allows(self):
        text = "Revenue is recognised when control of goods transfers to customers."
        record = gate_record(
            "text-1",
            row_type="text_block",
            label="Revenue policy",
            value="",
            text_preview=text,
            source_snippet=text,
            gate_status="suggest_mapping_only",
            requires_confirmation=True,
        )
        candidates, _validation, _contract = build([record])
        self.assertEqual(candidates["total_handoff_candidates"], 1)

    def test_handoff_item_preserves_source_candidate_id_and_case_id(self):
        candidates, _validation, _contract = build([gate_record("cand-10", case_id="case-z")])
        item = candidates["handoff_items"][0]
        self.assertEqual(item["source_candidate_id"], "cand-10")
        self.assertEqual(item["case_id"], "case-z")

    def test_handoff_item_includes_provenance_and_warning_flags(self):
        candidates, _validation, _contract = build([gate_record(warning_flags=["section_warning"])])
        item = candidates["handoff_items"][0]
        self.assertIn("source_provenance", item)
        self.assertEqual(item["warning_flags"], ["section_warning"])

    def test_validation_fails_if_suggest_mapping_only_does_not_require_confirmation(self):
        candidates, _validation, _contract = build([gate_record("cand-2", gate_status="suggest_mapping_only", requires_confirmation=True)])
        candidates["handoff_items"][0]["requires_confirmation"] = False
        validation = validate_mapping_handoff(candidates, mapping_gate_report=gate_report([gate_record("cand-2", gate_status="suggest_mapping_only")]))
        self.assertFalse(validation["validation_passed"])
        self.assertEqual(validation["validation_errors"][0]["code"], "suggest_mapping_only_missing_confirmation")

    def test_validation_fails_if_blocked_candidate_appears_in_handoff(self):
        candidates, _validation, _contract = build([gate_record()])
        candidates["handoff_items"][0]["gate_status"] = "blocked_from_mapping"
        validation = validate_mapping_handoff(candidates, mapping_gate_report=gate_report([gate_record()]))
        self.assertFalse(validation["validation_passed"])
        self.assertEqual(validation["validation_errors"][0]["code"], "blocked_or_unknown_gate_included")

    def test_validation_warns_if_statement_section_is_missing(self):
        candidates, _validation, _contract = build([gate_record()])
        candidates["handoff_items"][0]["statement_section"] = None
        validation = validate_mapping_handoff(candidates, mapping_gate_report=gate_report([gate_record()]))
        codes = {item["code"] for item in validation["validation_warnings"]}
        self.assertIn("missing_statement_section", codes)

    def test_exclusion_ledger_counts_excluded_candidates_by_reason(self):
        candidates, _validation, _contract = build(
            [
                gate_record("ok"),
                gate_record("manual", gate_status="manual_review_required"),
                gate_record("blocked", gate_status="blocked_from_mapping"),
            ]
        )
        self.assertEqual(candidates["excluded_count"], 2)
        self.assertGreater(candidates["exclusion_summary"]["by_reason"]["excluded_gate_status:manual_review_required"], 0)

    def test_reconciliation_against_expected_13t_counts_works(self):
        records = [
            gate_record("auto"),
            gate_record("suggest", gate_status="suggest_mapping_only", requires_confirmation=True),
            gate_record("manual", gate_status="manual_review_required"),
        ]
        _candidates, validation, _contract = build(records)
        self.assertEqual(validation["reconciliation"]["expected_allowed_count"], 2)
        self.assertTrue(validation["reconciliation"]["included_matches_expected_allowed"])

    def test_contract_report_contains_allowed_and_excluded_gate_statuses(self):
        _candidates, _validation, contract = build([gate_record()])
        self.assertIn("auto_mappable_candidate", contract["allowed_gate_statuses"])
        self.assertIn("manual_review_required", contract["excluded_gate_statuses"])

    def test_markdown_reports_render_handoff_and_validation_summary(self):
        candidates, validation, contract = build([gate_record()])
        self.assertIn("## Summary", render_candidates_markdown(candidates))
        self.assertIn("## Validation Summary", render_validation_markdown(validation))
        self.assertIn("## Allowed Gate Statuses", render_contract_markdown(contract))

    def test_no_db_mutation_metadata_is_false(self):
        candidates, validation, contract = build([gate_record()])
        self.assertFalse(candidates["run_metadata"]["database_mutated"])
        self.assertFalse(validation["run_metadata"]["database_mutated"])
        self.assertFalse(contract["run_metadata"]["database_mutated"])

    def test_no_live_model_calls_are_required(self):
        candidates, validation, contract = build([gate_record()])
        self.assertFalse(candidates["run_metadata"]["live_huggingface_calls_made"])
        self.assertFalse(candidates["run_metadata"]["live_openai_calls_made"])
        self.assertFalse(validation["run_metadata"]["live_huggingface_calls_made"])
        self.assertFalse(contract["run_metadata"]["live_openai_calls_made"])

    def test_reference_xml_is_not_sent_to_any_model(self):
        candidates, validation, contract = build([gate_record()])
        self.assertFalse(candidates["run_metadata"]["reference_xml_sent_to_model"])
        self.assertFalse(validation["run_metadata"]["reference_xml_sent_to_model"])
        self.assertFalse(contract["run_metadata"]["reference_xml_sent_to_model"])

    def test_no_taxonomy_mapping_or_semantic_matcher_call_is_performed(self):
        candidates, validation, contract = build([gate_record()])
        self.assertFalse(candidates["run_metadata"]["taxonomy_mapping_performed"])
        self.assertFalse(candidates["run_metadata"]["semantic_matcher_called"])
        self.assertFalse(validation["run_metadata"]["semantic_matcher_called"])
        self.assertFalse(contract["run_metadata"]["taxonomy_mapping_performed"])

    def test_json_reports_validate(self):
        candidates, validation, contract = build([gate_record()])
        json.dumps(candidates)
        json.dumps(validation)
        json.dumps(contract)


if __name__ == "__main__":
    unittest.main()
