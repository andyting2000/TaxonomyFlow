import json
import unittest
from datetime import datetime
from pathlib import Path

from database import (
    ExtractedDataItem,
    LLMMappingSuggestion,
    MappingSupervisorReview,
)
from schemas import (
    MappingSupervisorReviewCreateInternal,
    MappingSupervisorReviewRead,
    MappingSupervisorReviewUpdateInternal,
    mapping_supervisor_review_read_from_model,
)


FORBIDDEN_SCHEMA_FIELDS = {
    "auditor_xml",
    "parsed_xml_facts",
    "parsed_xml_fact",
    "gold_answer",
    "target_correct_qname",
    "target_gold_answer",
    "evaluation_label",
    "confirmed_tag_id",
    "raw_payload",
    "raw_prompt",
    "raw_response",
}


class SupervisorReviewPersistenceTests(unittest.TestCase):
    def test_model_table_metadata_exists_with_required_columns(self):
        table = MappingSupervisorReview.__table__
        columns = set(table.columns.keys())

        self.assertEqual(table.name, "mapping_supervisor_reviews")
        for column in [
            "id",
            "user_id",
            "job_id",
            "extracted_data_item_id",
            "llm_mapping_suggestion_id",
            "mapper_selected_template_field_id",
            "mapper_selected_qname",
            "mapper_confidence",
            "mapper_status",
            "review_status",
            "supervisor_decision",
            "supervisor_risk_level",
            "supervisor_recommended_action",
            "supervisor_safe_to_accept",
            "calibrated_safe_to_accept",
            "supervisor_confidence_adjustment",
            "supervisor_issues_json",
            "supervisor_reason",
            "supervisor_model_provider",
            "supervisor_model_id",
            "supervisor_prompt_version",
            "supervisor_schema_version",
            "supervisor_payload_hash",
            "supervisor_response_hash",
            "error_type",
            "error_message_sanitized",
            "created_at",
            "updated_at",
        ]:
            self.assertIn(column, columns)

        self.assertFalse(FORBIDDEN_SCHEMA_FIELDS & columns)

    def test_pending_review_nullable_outputs_and_required_status_defaults(self):
        table = MappingSupervisorReview.__table__

        self.assertFalse(table.c.job_id.nullable)
        self.assertFalse(table.c.review_status.nullable)
        self.assertFalse(table.c.supervisor_safe_to_accept.nullable)
        self.assertFalse(table.c.calibrated_safe_to_accept.nullable)
        self.assertTrue(table.c.supervisor_decision.nullable)
        self.assertTrue(table.c.supervisor_risk_level.nullable)
        self.assertTrue(table.c.supervisor_recommended_action.nullable)
        self.assertTrue(table.c.supervisor_reason.nullable)

    def test_model_has_practical_indexes_and_check_constraints(self):
        table = MappingSupervisorReview.__table__
        index_names = {index.name for index in table.indexes}
        constraint_names = {constraint.name for constraint in table.constraints if constraint.name}

        for index in [
            "idx_mapping_supervisor_reviews_job",
            "idx_mapping_supervisor_reviews_suggestion",
            "idx_mapping_supervisor_reviews_item",
            "idx_mapping_supervisor_reviews_status",
            "idx_mapping_supervisor_reviews_safe",
            "idx_mapping_supervisor_reviews_calibrated_safe",
            "idx_mapping_supervisor_reviews_risk",
            "idx_mapping_supervisor_reviews_created",
        ]:
            self.assertIn(index, index_names)

        for constraint in [
            "chk_mapping_supervisor_reviews_status",
            "chk_mapping_supervisor_reviews_decision",
            "chk_mapping_supervisor_reviews_risk",
            "chk_mapping_supervisor_reviews_action",
            "chk_mapping_supervisor_reviews_confidence_adjustment",
            "chk_mapping_supervisor_reviews_source",
            "chk_mapping_supervisor_reviews_mapper_confidence",
            "chk_mapping_supervisor_reviews_attempt",
        ]:
            self.assertIn(constraint, constraint_names)

    def test_completed_review_can_store_decision_risk_action_issues_reason(self):
        review = MappingSupervisorReview(
            id="review-1",
            user_id=1,
            job_id=101,
            extracted_data_item_id="item-1",
            llm_mapping_suggestion_id="suggestion-1",
            mapper_selected_template_field_id="ifrs-smes:CashAndCashEquivalents",
            mapper_selected_qname="ifrs-smes:CashAndCashEquivalents",
            mapper_confidence=0.97,
            mapper_status="suggested",
            review_status="completed",
            supervisor_decision="agree",
            supervisor_risk_level="low",
            supervisor_recommended_action="accept",
            supervisor_safe_to_accept=True,
            calibrated_safe_to_accept=True,
            supervisor_confidence_adjustment="keep",
            supervisor_issues_json=json.dumps([]),
            supervisor_reason="Mapper selection is supported by candidate and concept-card evidence.",
            supervisor_model_provider="hf",
            supervisor_model_id="supervisor-model",
            supervisor_prompt_version="17d_c_v1",
            supervisor_schema_version="supervisor_review_v1",
            supervisor_payload_hash="a" * 64,
            supervisor_response_hash="b" * 64,
            source="mock",
        )

        self.assertEqual(review.review_status, "completed")
        self.assertEqual(review.supervisor_decision, "agree")
        self.assertTrue(review.supervisor_safe_to_accept)
        self.assertEqual(json.loads(review.supervisor_issues_json), [])

    def test_failed_review_can_store_sanitized_error(self):
        review = MappingSupervisorReview(
            id="review-2",
            job_id=101,
            review_status="failed",
            supervisor_safe_to_accept=False,
            calibrated_safe_to_accept=False,
            error_type="provider_rate_limited",
            error_message_sanitized="Supervisor provider is temporarily rate limited.",
            source="mock",
        )

        self.assertEqual(review.review_status, "failed")
        self.assertEqual(review.error_type, "provider_rate_limited")
        self.assertNotIn("hf_", review.error_message_sanitized)

    def test_supervisor_review_creation_does_not_mutate_suggestion_or_extracted_row(self):
        item = ExtractedDataItem(
            id="item-1",
            page_id="page-1",
            extracted_label="Cash",
            extracted_value="100",
            financial_year=2026,
            template_field_id=None,
            is_reviewed=False,
            confirmed_tag_id=None,
        )
        suggestion = LLMMappingSuggestion(
            id="suggestion-1",
            job_id=101,
            extracted_data_item_id="item-1",
            suggested_template_field_id="ifrs-smes:CashAndCashEquivalents",
            confidence=0.97,
            reason="AI selected a candidate.",
            ranked_candidates_json="[]",
            status="suggested",
            model_id="unit-qwen",
        )

        MappingSupervisorReview(
            id="review-3",
            job_id=101,
            extracted_data_item_id=item.id,
            llm_mapping_suggestion_id=suggestion.id,
            review_status="completed",
            supervisor_decision="agree",
            supervisor_risk_level="low",
            supervisor_recommended_action="accept",
            supervisor_safe_to_accept=True,
            calibrated_safe_to_accept=True,
            source="mock",
        )

        self.assertIsNone(item.template_field_id)
        self.assertFalse(item.is_reviewed)
        self.assertIsNone(item.confirmed_tag_id)
        self.assertEqual(suggestion.status, "suggested")

    def test_read_serializer_excludes_sensitive_payload_and_hash_fields(self):
        review = MappingSupervisorReview(
            id="review-4",
            job_id=101,
            extracted_data_item_id="item-1",
            llm_mapping_suggestion_id="suggestion-1",
            review_status="completed",
            supervisor_decision="needs_human_review",
            supervisor_risk_level="medium",
            supervisor_recommended_action="keep_for_human_review",
            supervisor_safe_to_accept=False,
            calibrated_safe_to_accept=False,
            supervisor_confidence_adjustment="decrease",
            supervisor_issues_json=json.dumps(
                [{"type": "ambiguous_label", "description": "Label is too broad."}]
            ),
            supervisor_reason="Needs human review.",
            supervisor_model_provider="hf",
            supervisor_model_id="supervisor-model",
            supervisor_prompt_version="17d_c_v1",
            supervisor_schema_version="supervisor_review_v1",
            supervisor_payload_hash="a" * 64,
            supervisor_response_hash="b" * 64,
            created_at=datetime(2026, 6, 17),
            updated_at=datetime(2026, 6, 17),
        )

        serialized = mapping_supervisor_review_read_from_model(review).model_dump()

        self.assertEqual(serialized["supervisor_issues"][0]["type"], "ambiguous_label")
        self.assertNotIn("supervisor_payload_hash", serialized)
        self.assertNotIn("supervisor_response_hash", serialized)
        self.assertFalse(FORBIDDEN_SCHEMA_FIELDS & set(serialized.keys()))

    def test_schema_classes_have_no_forbidden_fields(self):
        for schema in [
            MappingSupervisorReviewCreateInternal,
            MappingSupervisorReviewUpdateInternal,
            MappingSupervisorReviewRead,
        ]:
            self.assertFalse(FORBIDDEN_SCHEMA_FIELDS & set(schema.model_fields.keys()))

    def test_migration_file_exists_and_defines_review_table_safely(self):
        migration = Path("migrations/012_add_mapping_supervisor_reviews.sql").read_text(
            encoding="utf-8"
        )

        self.assertIn("CREATE TABLE IF NOT EXISTS mapping_supervisor_reviews", migration)
        self.assertIn("REFERENCES filing_jobs(id) ON DELETE CASCADE", migration)
        self.assertIn("REFERENCES llm_mapping_suggestions(id) ON DELETE SET NULL", migration)
        self.assertIn("chk_mapping_supervisor_reviews_status", migration)
        self.assertIn("idx_mapping_supervisor_reviews_job", migration)
        self.assertIn("idx_mapping_supervisor_reviews_suggestion", migration)
        self.assertIn("idx_mapping_supervisor_reviews_item", migration)
        self.assertNotIn("confirmed_tag_id", migration)
        for forbidden in [
            "auditor_xml",
            "parsed_xml_facts",
            "gold_answer",
            "target_correct_qname",
            "evaluation_label",
            "raw_payload",
            "raw_prompt",
            "raw_response",
        ]:
            self.assertNotIn(forbidden, migration)

    def test_db_init_tracks_supervisor_review_table_and_columns(self):
        db_init_source = Path("db_init.py").read_text(encoding="utf-8")

        self.assertIn('"mapping_supervisor_reviews"', db_init_source)
        self.assertIn('"llm_mapping_suggestion_id"', db_init_source)
        self.assertIn('"supervisor_safe_to_accept"', db_init_source)
        self.assertIn('"calibrated_safe_to_accept"', db_init_source)


if __name__ == "__main__":
    unittest.main()
