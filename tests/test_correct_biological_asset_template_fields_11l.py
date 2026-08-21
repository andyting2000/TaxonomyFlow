import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from scripts import correct_biological_asset_template_fields_11l as correction


class FakeTemplateService:
    def get_concept_info(self, concept_id):
        labels = {
            "ssmt-mpers:CurrentBiologicalAssets": {"label": "Biological assets"},
            "ssmt-mpers:NoncurrentBiologicalAssets": {"label": "Biological assets"},
        }
        return labels.get(concept_id)


def _row(
    item_id="item-1",
    label="SHARE CAPITAL",
    template_field_id="ssmt-mpers:CurrentBiologicalAssets",
    job_id=9,
    confirmed_tag_id=123,
):
    return SimpleNamespace(
        item_id=item_id,
        job_id=job_id,
        page_id="page-1",
        page_number=2,
        extracted_label=label,
        extracted_value="5,032,604.00",
        template_field_id=template_field_id,
        statement_type="Statement of Financial Position",
        confirmed_tag_id=confirmed_tag_id,
    )


def _plan_report(candidate_count=2):
    candidates = []
    for index in range(candidate_count):
        candidates.append(
            {
                "item_id": f"item-{index}",
                "job_id": 9,
                "current_template_field_id": "ssmt-mpers:CurrentBiologicalAssets",
            }
        )
    return {
        "feature": "11K",
        "job_id": 9,
        "apply_supported": False,
        "candidate_count": candidate_count,
        "candidates": candidates,
    }


class CorrectBiologicalAssetTemplateFields11LTests(unittest.TestCase):
    def test_target_ids_are_loaded_from_11k_report(self):
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

    def test_non_biological_target_row_is_eligible_and_preserves_fields(self):
        evidence = correction.row_to_evidence(
            _row(),
            expected_job_id=9,
            template_service=FakeTemplateService(),
        )

        self.assertTrue(evidence.eligible)
        self.assertEqual(evidence.current_template_field_id, "ssmt-mpers:CurrentBiologicalAssets")
        self.assertEqual(evidence.current_statement_type, "Statement of Financial Position")
        self.assertEqual(evidence.confirmed_tag_id, 123)
        self.assertTrue(evidence.proposed_action["preserve_extracted_label"])
        self.assertTrue(evidence.proposed_action["preserve_extracted_value"])
        self.assertTrue(evidence.proposed_action["preserve_statement_type"])
        self.assertTrue(evidence.proposed_action["preserve_confirmed_tag_id"])
        self.assertIsNone(evidence.proposed_action["replacement_concept_id"])
        self.assertFalse(evidence.proposed_action["invent_replacement_concept"])

    def test_biological_label_is_not_eligible(self):
        evidence = correction.row_to_evidence(
            _row(label="Biological assets - livestock"),
            expected_job_id=9,
            template_service=FakeTemplateService(),
        )

        self.assertFalse(evidence.eligible)
        self.assertIn("supports biological-asset mapping", evidence.eligibility_reason)

    def test_non_biological_concept_is_not_eligible(self):
        evidence = correction.row_to_evidence(
            _row(template_field_id="ifrs-smes:TradeAndOtherCurrentReceivables"),
            expected_job_id=9,
            template_service=FakeTemplateService(),
        )

        self.assertFalse(evidence.eligible)
        self.assertIn("no longer a guarded biological-asset concept", evidence.eligibility_reason)

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

    def test_update_statement_requires_exact_id_job_biological_concept_and_failed_guardrail(self):
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
        self.assertIn("ssmt-mpers:CurrentBiologicalAssets", compiled)
        self.assertIn("ssmt-mpers:NoncurrentBiologicalAssets", compiled)
        self.assertIn("lower(coalesce(extracted_data_items.extracted_label", compiled)
        self.assertNotIn("statement_type=", compiled)
        self.assertNotIn("confirmed_tag_id=", compiled)
        self.assertNotIn("extracted_label=", compiled)
        self.assertNotIn("extracted_value=", compiled)

    def test_report_marks_no_replacement_concept(self):
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
        self.assertTrue(action["manual_review_required"])


if __name__ == "__main__":
    unittest.main()
