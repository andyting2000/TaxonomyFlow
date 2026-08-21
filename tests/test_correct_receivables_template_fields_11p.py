import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from scripts import correct_receivables_template_fields_11p as correction


TARGET_CONCEPT = "ifrs-smes:TradeAndOtherCurrentReceivables"


class FakeTemplateService:
    def get_concept_info(self, concept_id):
        labels = {
            TARGET_CONCEPT: {"label": "Trade and other current receivables"},
            "TradeAndOtherCurrentReceivables": {"label": "Trade and other current receivables"},
        }
        return labels.get(concept_id)


def _row(
    item_id="item-1",
    label="CORPSEC SERVICES SDN BHD",
    template_field_id=TARGET_CONCEPT,
    job_id=9,
    confirmed_tag_id=123,
    is_reviewed=True,
):
    return SimpleNamespace(
        item_id=item_id,
        job_id=job_id,
        page_id="page-1",
        page_number=1,
        extracted_label=label,
        extracted_value="864.00",
        template_field_id=template_field_id,
        statement_type="Statement of Financial Position",
        confirmed_tag_id=confirmed_tag_id,
        is_reviewed=is_reviewed,
    )


def _plan_report(candidate_count=2):
    candidates = []
    for index in range(candidate_count):
        candidates.append(
            {
                "item_id": f"item-{index}",
                "job_id": 9,
                "extracted_label": f"COMPANY {index} SDN BHD",
                "current_template_field_id": TARGET_CONCEPT,
            }
        )
    return {
        "feature": "11O",
        "job_id": 9,
        "apply_supported": False,
        "candidate_count": candidate_count,
        "candidates": candidates,
    }


class CorrectReceivablesTemplateFields11PTests(unittest.TestCase):
    def test_target_ids_are_loaded_from_11o_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "plan.json"
            report_path.write_text(json.dumps(_plan_report()), encoding="utf-8")

            target_ids = correction.load_target_ids_from_plan(
                report_path,
                job_id=9,
                expected_count=2,
            )

        self.assertEqual(target_ids, ("item-0", "item-1"))

    def test_target_loader_rejects_incomplete_or_duplicate_targets(self):
        report = _plan_report(candidate_count=2)
        report["candidates"][1]["item_id"] = "item-0"

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "plan.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaises(ValueError):
                correction.load_target_ids_from_plan(
                    report_path,
                    job_id=9,
                    expected_count=2,
                )

    def test_target_loader_rejects_explicit_receivable_evidence(self):
        report = _plan_report(candidate_count=1)
        report["candidates"][0]["extracted_label"] = "Amount due from COMPANY 1 SDN BHD"

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "plan.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaises(ValueError):
                correction.load_target_ids_from_plan(
                    report_path,
                    job_id=9,
                    expected_count=1,
                )

    def test_company_customer_detail_target_row_is_eligible_and_preserves_fields(self):
        evidence = correction.row_to_evidence(
            _row(),
            expected_job_id=9,
            template_service=FakeTemplateService(),
        )

        self.assertTrue(evidence.eligible)
        self.assertEqual(evidence.current_template_field_id, TARGET_CONCEPT)
        self.assertEqual(evidence.current_statement_type, "Statement of Financial Position")
        self.assertEqual(evidence.confirmed_tag_id, 123)
        self.assertTrue(evidence.is_reviewed)
        self.assertTrue(evidence.proposed_action["preserve_extracted_label"])
        self.assertTrue(evidence.proposed_action["preserve_extracted_value"])
        self.assertTrue(evidence.proposed_action["preserve_statement_type"])
        self.assertTrue(evidence.proposed_action["preserve_confirmed_tag_id"])
        self.assertTrue(evidence.proposed_action["preserve_reviewed_status"])
        self.assertIsNone(evidence.proposed_action["replacement_concept_id"])
        self.assertFalse(evidence.proposed_action["invent_replacement_concept"])
        self.assertFalse(evidence.proposed_action["infer_aggregation"])
        self.assertFalse(evidence.proposed_action["infer_dimensions"])

    def test_explicit_receivable_label_is_not_eligible(self):
        evidence = correction.row_to_evidence(
            _row(label="Amount due from CORPSEC SERVICES SDN BHD"),
            expected_job_id=9,
            template_service=FakeTemplateService(),
        )

        self.assertFalse(evidence.eligible)
        self.assertIn("supports receivables", evidence.eligibility_reason)

    def test_non_receivables_concept_is_not_eligible(self):
        evidence = correction.row_to_evidence(
            _row(template_field_id="ifrs-smes:CashAndCashEquivalents"),
            expected_job_id=9,
            template_service=FakeTemplateService(),
        )

        self.assertFalse(evidence.eligible)
        self.assertIn("no longer TradeAndOtherCurrentReceivables", evidence.eligibility_reason)

    def test_wrong_job_is_not_eligible(self):
        evidence = correction.row_to_evidence(
            _row(job_id=10),
            expected_job_id=9,
            template_service=FakeTemplateService(),
        )

        self.assertFalse(evidence.eligible)
        self.assertIn("expected 9", evidence.eligibility_reason)

    def test_dry_run_report_does_not_mutate_rows(self):
        rows = [
            correction.row_to_evidence(
                _row("item-1"),
                expected_job_id=9,
                template_service=FakeTemplateService(),
            )
        ]

        report = correction.build_report(
            job_id=9,
            target_ids=("item-1",),
            rows=rows,
            apply_changes=False,
            rows_updated=0,
        )

        self.assertEqual(report["mode"], "dry_run")
        self.assertFalse(report["applied"])
        self.assertFalse(report["database_modified"])
        self.assertEqual(report["rows_eligible"], 1)
        self.assertEqual(report["rows_updated"], 0)
        self.assertTrue(report["update_policy"]["clear_template_field_id_only"])
        self.assertFalse(report["update_policy"]["assign_replacement_concept"])
        self.assertFalse(report["update_policy"]["infer_aggregation"])
        self.assertFalse(report["update_policy"]["infer_dimensions"])

    def test_update_statement_requires_exact_id_job_receivables_concept_and_failed_guardrail(self):
        statement = correction.build_correction_update_statement(
            job_id=9,
            target_ids=("item-1", "item-2"),
            eligible_ids=("item-1",),
        )
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))

        self.assertIn("UPDATE extracted_data_items SET template_field_id=NULL", compiled)
        self.assertIn("extracted_data_items.id IN ('item-1', 'item-2')", compiled)
        self.assertIn("extracted_data_items.id IN ('item-1')", compiled)
        self.assertIn("financial_statement_pages.job_id = 9", compiled)
        self.assertIn("extracted_data_items.template_field_id IN", compiled)
        self.assertIn("ifrs-smes:TradeAndOtherCurrentReceivables", compiled)
        self.assertIn("TradeAndOtherCurrentReceivables", compiled)
        self.assertIn("lower(coalesce(extracted_data_items.extracted_label", compiled)
        self.assertIn("sdn bhd", compiled)
        self.assertIn("amount due from", compiled)
        self.assertNotIn("statement_type=", compiled)
        self.assertNotIn("confirmed_tag_id=", compiled)
        self.assertNotIn("extracted_label=", compiled)
        self.assertNotIn("extracted_value=", compiled)
        self.assertNotIn("is_reviewed=", compiled)

    def test_report_marks_no_replacement_concept_and_preserves_fields(self):
        rows = [
            correction.row_to_evidence(
                _row("item-1"),
                expected_job_id=9,
                template_service=FakeTemplateService(),
            )
        ]

        report = correction.build_report(
            job_id=9,
            target_ids=("item-1",),
            rows=rows,
            apply_changes=False,
            rows_updated=0,
        )
        action = report["target_rows"][0]["proposed_action"]

        self.assertIsNone(action["replacement_concept_id"])
        self.assertFalse(action["invent_replacement_concept"])
        self.assertFalse(action["infer_aggregation"])
        self.assertFalse(action["infer_dimensions"])
        self.assertTrue(action["manual_review_required"])
        self.assertTrue(action["preserve_confirmed_tag_id"])
        self.assertTrue(action["preserve_reviewed_status"])


if __name__ == "__main__":
    unittest.main()
