import unittest
from types import SimpleNamespace

import scripts.plan_biological_asset_template_correction as planner


class FakeTemplateService:
    def get_concept_info(self, concept_id):
        labels = {
            "ssmt-mpers:CurrentBiologicalAssets": {"label": "Biological assets"},
            "ssmt-mpers:NoncurrentBiologicalAssets": {"label": "Biological assets"},
        }
        return labels.get(concept_id)


def _row(item_id, label, template_field_id="ssmt-mpers:CurrentBiologicalAssets"):
    return SimpleNamespace(
        item_id=item_id,
        job_id=9,
        page_id="page-1",
        page_number=2,
        extracted_label=label,
        extracted_value="100.00",
        template_field_id=template_field_id,
        statement_type="Statement of Financial Position",
        is_reviewed=True,
        confirmed_tag_id=None,
    )


class BiologicalAssetTemplateCorrectionPlanTests(unittest.TestCase):
    def test_candidate_detection_finds_non_biological_biological_asset_rows(self):
        candidates = planner.detect_correction_candidates(
            [_row("item-1", "SHARE CAPITAL")],
            FakeTemplateService(),
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].item_id, "item-1")
        self.assertEqual(
            candidates[0].current_template_field_id,
            "ssmt-mpers:CurrentBiologicalAssets",
        )

    def test_biological_labels_are_excluded_from_candidates(self):
        candidates = planner.detect_correction_candidates(
            [
                _row("item-1", "Biological assets"),
                _row("item-2", "Livestock and cattle"),
                _row("item-3", "Agricultural produce"),
            ],
            FakeTemplateService(),
        )

        self.assertEqual(candidates, [])

    def test_non_biological_labels_are_included_for_both_guarded_concepts(self):
        candidates = planner.detect_correction_candidates(
            [
                _row("item-1", "GOOD WILL", "ssmt-mpers:NoncurrentBiologicalAssets"),
                _row("item-2", "INFOHOUSE (I.T) SDN BHD", "CurrentBiologicalAssets"),
            ],
            FakeTemplateService(),
        )

        self.assertEqual([candidate.item_id for candidate in candidates], ["item-1", "item-2"])

    def test_non_biological_concepts_are_not_candidates(self):
        candidates = planner.detect_correction_candidates(
            [_row("item-1", "SHARE CAPITAL", "ifrs-smes:Equity")],
            FakeTemplateService(),
        )

        self.assertEqual(candidates, [])

    def test_proposed_action_does_not_invent_replacement_concept(self):
        candidates = planner.detect_correction_candidates(
            [_row("item-1", "P&L 2007")],
            FakeTemplateService(),
        )

        action = candidates[0].proposed_action
        self.assertIsNone(action["replacement_concept_id"])
        self.assertFalse(action["invent_replacement_concept"])
        self.assertTrue(action["manual_review_required"])
        self.assertTrue(action["preserve_extracted_label"])
        self.assertTrue(action["preserve_extracted_value"])

    def test_report_is_dry_run_only(self):
        report = planner.build_report(
            9,
            planner.detect_correction_candidates(
                [_row("item-1", "SHARE PREMIUM")],
                FakeTemplateService(),
            ),
        )

        self.assertEqual(report["mode"], "dry_run_only")
        self.assertTrue(report["read_only"])
        self.assertFalse(report["database_modified"])
        self.assertFalse(report["apply_supported"])
        self.assertFalse(report["proposed_future_correction"]["assign_replacement_concept"])
        self.assertFalse(report["proposed_future_correction"]["apply_in_this_feature"])

    def test_no_db_mutation_helper_exists_in_this_feature(self):
        public_names = {
            name
            for name in dir(planner)
            if not name.startswith("_")
        }

        self.assertNotIn("build_correction_update_statement", public_names)
        self.assertNotIn("run_correction", public_names)
        self.assertNotIn("apply_correction", public_names)


if __name__ == "__main__":
    unittest.main()
