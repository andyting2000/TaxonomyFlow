import copy
import unittest

from services.extraction_v2_duplicate_resolver import (
    render_duplicate_conflict_markdown,
    resolve_extraction_v2_duplicates,
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
        "warnings": [],
        "provenance": {"page_number": 1},
    }
    base.update(overrides)
    return base


def v2_report(candidates):
    return {
        "run_metadata": {
            "database_mutated": False,
            "reference_xml_sent_to_model": False,
        },
        "pipeline_name": "Industrial Extraction Pipeline v2",
        "pipeline_stages": [],
        "case_reports": [
            {
                "case_id": "case-a",
                "source_pdf": "case-a.pdf",
                "status": "ok",
                "pages_analyzed": 2,
                "candidate_count": len(candidates),
                "candidates": candidates,
            }
        ],
    }


def quality_report():
    return {
        "run_metadata": {"database_mutated": False},
        "quality_issue_counts": {
            "duplicate_label_conflicting_values": 1,
            "duplicate_label_value_same_case": 1,
            "heading_like_numeric_fact": 1,
            "date_only_label": 1,
            "year_header_row_extracted_as_fact": 1,
            "comparative_value_under_numeric_type": 1,
        },
    }


def readiness_report():
    return {
        "run_metadata": {"database_mutated": False},
        "aggregate_readiness_counts": {"high": 1, "medium": 1, "low": 1, "not_ready": 1},
        "per_case_readiness": [
            {
                "case_id": "case-a",
                "total_candidates": 4,
                "high_readiness_count": 1,
                "medium_readiness_count": 1,
                "low_readiness_count": 1,
                "not_ready_count": 1,
                "reference_text_blocks": 1,
            }
        ],
    }


def comparison_report():
    return {
        "aggregate_metrics": {"missing_text_block_cases": []},
        "per_case": [{"case_id": "case-a", "reference_text_blocks": 1}],
    }


def reference_report():
    return {
        "run_metadata": {"database_mutated": False},
        "case_reports": [
            {
                "case_id": "case-a",
                "total_facts": 2,
                "numeric_fact_count": 1,
                "text_block_count": 1,
                "facts": [],
            }
        ],
    }


def resolve(candidates):
    return resolve_extraction_v2_duplicates(
        v2_report=v2_report(candidates),
        quality_report=quality_report(),
        readiness_report=readiness_report(),
        comparison_report=comparison_report(),
        reference_report=reference_report(),
        input_paths={"v2_report": "memory"},
        output_paths={"duplicate": "duplicate.json", "cleaned": "cleaned.json", "readiness_after": "readiness.json"},
    )


def audit_by_label(cleaned_report, label):
    return [
        entry
        for entry in cleaned_report["duplicate_resolution"]["candidate_audit_trail"]
        if entry["original_candidate"].get("label") == label
    ]


class ExtractionV2DuplicateResolverTests(unittest.TestCase):
    def test_exact_duplicate_same_case_page_section_label_value_is_suppressed(self):
        dup, cleaned, _ready = resolve([candidate(), candidate()])
        self.assertEqual(dup["aggregate"]["safe_suppression_count"], 1)
        self.assertEqual(cleaned["duplicate_resolution"]["cleaned_candidate_count"], 1)
        self.assertEqual(audit_by_label(cleaned, "Cash and bank balances")[1]["action"], "suppress_exact_duplicate")

    def test_same_label_with_conflicting_values_is_not_suppressed_and_marked_conflict(self):
        _dup, cleaned, _ready = resolve([candidate(label="Revenue", value="100"), candidate(label="Revenue", value="200")])
        actions = {entry["action"] for entry in audit_by_label(cleaned, "Revenue")}
        self.assertEqual(actions, {"mark_conflict_review_required"})
        self.assertEqual(cleaned["duplicate_resolution"]["cleaned_candidate_count"], 2)

    def test_same_label_value_across_different_sections_is_not_blindly_suppressed(self):
        _dup, cleaned, _ready = resolve(
            [
                candidate(label="Revenue", value="100", statement_section="Statement of Profit or Loss"),
                candidate(label="Revenue", value="100", statement_section="Notes to the Financial Statements", source_snippet="Revenue note 100"),
            ]
        )
        self.assertEqual(cleaned["duplicate_resolution"]["suppressed_count"], 0)
        self.assertEqual(cleaned["duplicate_resolution"]["cleaned_candidate_count"], 2)

    def test_pure_date_label_numeric_fact_is_downgraded_to_metadata(self):
        _dup, cleaned, _ready = resolve([candidate(label="As at 31/12/2023", value="100")])
        entry = audit_by_label(cleaned, "As at 31/12/2023")[0]
        self.assertEqual(entry["action"], "downgrade_to_metadata")
        self.assertEqual(entry["proposed_row_type"], "metadata")

    def test_pure_year_label_numeric_fact_is_downgraded(self):
        _dup, cleaned, _ready = resolve([candidate(label="2024", value="100")])
        entry = audit_by_label(cleaned, "2024")[0]
        self.assertEqual(entry["action"], "downgrade_to_metadata")

    def test_year_header_row_extracted_as_fact_is_marked_not_ready(self):
        _dup, cleaned, _ready = resolve([candidate(label="Current year", value="100")])
        entry = audit_by_label(cleaned, "Current year")[0]
        self.assertEqual(entry["proposed_readiness"], "not_ready")

    def test_numeric_fact_with_value_and_previous_value_is_converted_to_comparative(self):
        _dup, cleaned, _ready = resolve([candidate(label="Revenue", value="100", previous_value="90")])
        entry = audit_by_label(cleaned, "Revenue")[0]
        self.assertEqual(entry["action"], "convert_numeric_to_comparative")
        self.assertEqual(entry["proposed_row_type"], "comparative_numeric_fact")

    def test_heading_like_numeric_fact_is_flagged_and_not_high_readiness(self):
        _dup, cleaned, _ready = resolve([candidate(label="Assets", value="100")])
        entry = audit_by_label(cleaned, "Assets")[0]
        self.assertEqual(entry["action"], "manual_review_required")
        self.assertEqual(entry["proposed_readiness"], "low")

    def test_exact_duplicate_text_block_in_same_section_is_suppressible(self):
        text = "Revenue is recognised when control of goods is transferred to the customer."
        block = candidate(row_type="text_block", label="Revenue policy", value="", text=text, source_snippet=text)
        _dup, cleaned, _ready = resolve([block, copy.deepcopy(block)])
        self.assertEqual(cleaned["duplicate_resolution"]["suppressed_count"], 1)

    def test_similar_text_blocks_across_different_sections_are_not_merged(self):
        text = "Revenue is recognised when control of goods is transferred to the customer."
        _dup, cleaned, _ready = resolve(
            [
                candidate(row_type="text_block", label="Revenue policy", value="", text=text, source_snippet=text, statement_section="Note 1"),
                candidate(row_type="text_block", label="Revenue policy", value="", text=text, source_snippet=text, statement_section="Note 2"),
            ]
        )
        self.assertEqual(cleaned["duplicate_resolution"]["suppressed_count"], 0)

    def test_manual_review_required_groups_are_counted(self):
        dup, _cleaned, _ready = resolve([candidate(label="Assets", value="100"), candidate(label="Assets", value="200")])
        self.assertGreaterEqual(dup["aggregate"]["manual_review_required_count"], 1)

    def test_cleaned_candidate_report_retains_audit_trail_for_suppressed_candidates(self):
        _dup, cleaned, _ready = resolve([candidate(), candidate()])
        suppressed = [entry for entry in cleaned["duplicate_resolution"]["candidate_audit_trail"] if not entry["retained_in_cleaned_rows"]]
        self.assertEqual(len(suppressed), 1)
        self.assertIn("original_candidate", suppressed[0])

    def test_original_input_report_is_not_modified(self):
        candidates = [candidate(), candidate()]
        original = v2_report(candidates)
        snapshot = copy.deepcopy(original)
        resolve_extraction_v2_duplicates(
            v2_report=original,
            quality_report=quality_report(),
            readiness_report=readiness_report(),
            comparison_report=comparison_report(),
            reference_report=reference_report(),
        )
        self.assertEqual(original, snapshot)

    def test_no_db_mutation_metadata_remains_false(self):
        dup, cleaned, ready = resolve([candidate()])
        self.assertFalse(dup["run_metadata"]["database_mutated"])
        self.assertFalse(cleaned["run_metadata"]["database_mutated"])
        self.assertFalse(ready["run_metadata"]["database_mutated"])

    def test_no_live_huggingface_or_openai_call_is_required(self):
        dup, cleaned, ready = resolve([candidate()])
        self.assertFalse(dup["run_metadata"]["live_huggingface_calls_made"])
        self.assertFalse(cleaned["run_metadata"]["live_openai_calls_made"])
        self.assertFalse(ready["run_metadata"]["live_huggingface_calls_made"])

    def test_per_case_before_after_readiness_summary_is_stable(self):
        _dup, _cleaned, ready = resolve([candidate(), candidate()])
        row = ready["per_case"][0]
        self.assertEqual(row["case_id"], "case-a")
        self.assertIn("before_readiness_counts", row)
        self.assertIn("after_readiness_counts", row)

    def test_markdown_report_renders_duplicate_conflict_summary(self):
        dup, _cleaned, _ready = resolve([candidate(), candidate()])
        markdown = render_duplicate_conflict_markdown(dup)
        self.assertIn("Duplicate and Conflict Report", markdown)
        self.assertIn("Safe suppression count: 1", markdown)

    def test_conflicting_values_remain_visible_in_cleaned_audit_trail(self):
        _dup, cleaned, _ready = resolve([candidate(label="Revenue", value="100"), candidate(label="Revenue", value="200")])
        values = {entry["original_candidate"]["value"] for entry in audit_by_label(cleaned, "Revenue")}
        self.assertEqual(values, {"100", "200"})

    def test_candidate_ids_and_stable_indexes_remain_traceable(self):
        _dup, cleaned, _ready = resolve([candidate()])
        entry = cleaned["duplicate_resolution"]["candidate_audit_trail"][0]
        self.assertIn("original_candidate_id", entry)
        self.assertEqual(entry["original_global_index"], 0)
        self.assertEqual(entry["cleaned_candidate"]["original_candidate_id"], entry["original_candidate_id"])

    def test_reference_xml_is_not_sent_to_any_model(self):
        dup, cleaned, ready = resolve([candidate()])
        self.assertFalse(dup["run_metadata"]["reference_xml_sent_to_model"])
        self.assertFalse(cleaned["run_metadata"]["reference_xml_sent_to_model"])
        self.assertFalse(ready["run_metadata"]["reference_xml_sent_to_model"])


if __name__ == "__main__":
    unittest.main()
