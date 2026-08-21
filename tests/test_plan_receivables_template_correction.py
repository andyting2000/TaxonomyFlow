import unittest
from types import SimpleNamespace

import scripts.plan_receivables_template_correction as planner


TARGET_CONCEPT = "ifrs-smes:TradeAndOtherCurrentReceivables"


class FakeTemplateService:
    def get_concept_info(self, concept_id):
        labels = {
            TARGET_CONCEPT: {"label": "Trade and other current receivables"},
            "TradeAndOtherCurrentReceivables": {"label": "Trade and other current receivables"},
        }
        return labels.get(concept_id)


def _row(item_id, label, template_field_id=TARGET_CONCEPT):
    return SimpleNamespace(
        item_id=item_id,
        job_id=9,
        page_id="page-1",
        page_number=1,
        extracted_label=label,
        extracted_value="100.00",
        template_field_id=template_field_id,
        statement_type="Statement of Financial Position",
        is_reviewed=True,
        confirmed_tag_id=None,
    )


class ReceivablesTemplateCorrectionPlanTests(unittest.TestCase):
    def test_candidate_detection_finds_blocked_receivables_template_rows(self):
        candidates = planner.detect_correction_candidates(
            [_row("item-1", "CORPSEC SERVICES SDN BHD")],
            FakeTemplateService(),
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].item_id, "item-1")
        self.assertEqual(candidates[0].current_template_field_id, TARGET_CONCEPT)
        self.assertEqual(candidates[0].guardrail_reason.split(",")[0], "template_field_id is ifrs-smes:TradeAndOtherCurrentReceivables")

    def test_explicit_summary_receivable_labels_are_excluded(self):
        candidates = planner.detect_correction_candidates(
            [
                _row("item-1", "OTHER DEBTOR - IH(I.T)"),
                _row("item-2", "TRADE RECEIVABLES"),
                _row("item-3", "Accounts receivable"),
            ],
            FakeTemplateService(),
        )

        self.assertEqual(candidates, [])

    def test_company_customer_like_labels_without_receivable_wording_are_included(self):
        candidates = planner.detect_correction_candidates(
            [
                _row("item-1", "ASIAN SECRETS SDN BHD"),
                _row("item-2", "BBS TRUST INT'L LIMITED", "TradeAndOtherCurrentReceivables"),
                _row("item-3", "MALAYSIAN RESOURCES CORPORATION BHD"),
            ],
            FakeTemplateService(),
        )

        self.assertEqual([candidate.item_id for candidate in candidates], ["item-1", "item-2", "item-3"])
        self.assertTrue(all(candidate.label_pattern == "company_or_customer_like_detail" for candidate in candidates))

    def test_labels_with_explicit_receivable_debtor_or_due_from_wording_are_excluded(self):
        candidates = planner.detect_correction_candidates(
            [
                _row("item-1", "Amount due from ASIAN SECRETS SDN BHD"),
                _row("item-2", "Receivable from CORPSEC SERVICES SDN BHD"),
                _row("item-3", "Other debtors"),
            ],
            FakeTemplateService(),
        )

        self.assertEqual(candidates, [])

    def test_non_receivables_concepts_are_not_candidates(self):
        candidates = planner.detect_correction_candidates(
            [_row("item-1", "CORPSEC SERVICES SDN BHD", "ifrs-smes:CashAndCashEquivalents")],
            FakeTemplateService(),
        )

        self.assertEqual(candidates, [])

    def test_proposed_action_does_not_invent_replacement_or_policy(self):
        candidates = planner.detect_correction_candidates(
            [_row("item-1", "CORPSEC SERVICES SDN BHD")],
            FakeTemplateService(),
        )

        action = candidates[0].proposed_action
        self.assertIsNone(action["replacement_concept_id"])
        self.assertFalse(action["invent_replacement_concept"])
        self.assertFalse(action["infer_aggregation"])
        self.assertFalse(action["infer_dimensions"])
        self.assertTrue(action["manual_review_required"])
        self.assertTrue(action["preserve_extracted_label"])
        self.assertTrue(action["preserve_extracted_value"])
        self.assertTrue(action["preserve_statement_type"])
        self.assertTrue(action["preserve_confirmed_tag_id"])

    def test_report_is_dry_run_only(self):
        report = planner.build_report(
            9,
            planner.detect_correction_candidates(
                [_row("item-1", "CORPSEC SERVICES SDN BHD")],
                FakeTemplateService(),
            ),
        )

        self.assertEqual(report["mode"], "dry_run_only")
        self.assertTrue(report["read_only"])
        self.assertFalse(report["database_modified"])
        self.assertFalse(report["apply_supported"])
        self.assertFalse(report["generated_xbrl_modified"])
        self.assertFalse(report["mapping_behavior_changed"])
        self.assertFalse(report["proposed_future_correction"]["assign_replacement_concept"])
        self.assertFalse(report["proposed_future_correction"]["infer_aggregation"])
        self.assertFalse(report["proposed_future_correction"]["infer_dimensions"])
        self.assertFalse(report["proposed_future_correction"]["apply_in_this_feature"])

    def test_no_db_mutation_helper_or_apply_option_exists_in_this_feature(self):
        public_names = {
            name
            for name in dir(planner)
            if not name.startswith("_")
        }

        self.assertNotIn("build_correction_update_statement", public_names)
        self.assertNotIn("run_correction", public_names)
        self.assertNotIn("apply_correction", public_names)

        parser_source = planner.async_main.__code__.co_consts
        self.assertFalse(any(const == "--apply" for const in parser_source))


if __name__ == "__main__":
    unittest.main()
