import unittest
from types import SimpleNamespace

from scripts.backfill_statement_types import (
    BackfillCandidate,
    BackfillReport,
    build_backfill_plan,
    build_candidate_update_statement,
    render_report,
)


class BackfillStatementTypeTests(unittest.TestCase):
    def test_build_backfill_plan_only_targets_blank_rows_with_template_field(self):
        rows = [
            SimpleNamespace(
                id="row-1",
                page_id="page-a",
                statement_type="",
                template_field_id="ifrs-smes:Cash",
            ),
            SimpleNamespace(
                id="row-2",
                page_id="page-a",
                statement_type=None,
                template_field_id="ifrs-smes:Inventory",
            ),
            SimpleNamespace(
                id="row-3",
                page_id="page-a",
                statement_type="Statement of Financial Position",
                template_field_id="ifrs-smes:Equity",
            ),
            SimpleNamespace(
                id="row-4",
                page_id="page-b",
                statement_type="",
                template_field_id=None,
            ),
            SimpleNamespace(
                id="row-5",
                page_id="page-b",
                statement_type="",
                template_field_id="ifrs-smes:UnknownField",
            ),
        ]

        plan = build_backfill_plan(
            rows_scanned=5,
            rows=rows,
            statement_type_by_page_id={
                "page-a": "Statement of Financial Position",
                "page-b": "",
            },
        )

        self.assertEqual(plan.rows_scanned, 5)
        self.assertEqual(plan.rows_eligible, 3)
        self.assertEqual(plan.rows_resolvable, 2)
        self.assertEqual(plan.rows_unresolved, 1)
        self.assertEqual([candidate.item_id for candidate in plan.candidates], [
                         "row-1", "row-2"])
        self.assertEqual(
            [candidate.template_field_id for candidate in plan.candidates],
            ["ifrs-smes:Cash", "ifrs-smes:Inventory"],
        )
        self.assertEqual(
            [candidate.resolved_statement_type for candidate in plan.candidates],
            ["Statement of Financial Position", "Statement of Financial Position"],
        )
        self.assertEqual(plan.candidates[0].extracted_label, None)

    def test_render_report_shows_blank_counts_and_apply_mode(self):
        report = BackfillReport(
            rows_scanned=5,
            rows_eligible=4,
            rows_resolvable=2,
            rows_updated=2,
            rows_unresolved=1,
            blank_count_before=3,
            blank_count_after=1,
            applied=True,
            displayed_candidate_limit=25,
            displayed_candidates=[],
        )

        text = render_report(report)

        self.assertIn("Mode: apply", text)
        self.assertIn("rows_scanned: 5", text)
        self.assertIn("rows_eligible: 4", text)
        self.assertIn("rows_resolvable: 2", text)
        self.assertIn("rows_updated: 2", text)
        self.assertIn("statement_type_blank_before: 3", text)
        self.assertIn("statement_type_blank_after: 1", text)
        self.assertIn("blank_count_delta: 2", text)
        self.assertIn("displayed_candidate_limit: 25", text)
        self.assertIn("Candidate evidence:", text)
        self.assertIn("  - none", text)
        self.assertIn("dry-run is the default", text)

    def test_render_report_shows_candidate_evidence_with_optional_label(self):
        report = BackfillReport(
            rows_scanned=8,
            rows_eligible=3,
            rows_resolvable=2,
            rows_updated=0,
            rows_unresolved=1,
            blank_count_before=4,
            blank_count_after=4,
            applied=False,
            displayed_candidate_limit=1,
            displayed_candidates=[
                BackfillCandidate(
                    item_id="row-1",
                    page_id="page-a",
                    template_field_id="ifrs-smes:Cash",
                    resolved_statement_type="Statement of Financial Position",
                    extracted_label="Cash and bank balances",
                )
            ],
        )

        text = render_report(report)

        self.assertIn("Mode: dry-run", text)
        self.assertIn("displayed_candidate_limit: 1", text)
        self.assertIn("displayed_candidate_count: 1", text)
        self.assertIn("item_id=row-1", text)
        self.assertIn("page_id=page-a", text)
        self.assertIn("template_field_id=ifrs-smes:Cash", text)
        self.assertIn(
            "resolved_statement_type=Statement of Financial Position", text
        )
        self.assertIn("extracted_label=Cash and bank balances", text)

    def test_build_candidate_update_statement_rechecks_safety_conditions(self):
        candidate = BackfillCandidate(
            item_id="row-1",
            page_id="page-a",
            template_field_id="ifrs-smes:Cash",
            resolved_statement_type="Statement of Financial Position",
        )

        statement = build_candidate_update_statement(candidate)
        compiled = str(
            statement.compile(compile_kwargs={"literal_binds": True})
        )

        self.assertIn("UPDATE extracted_data_items SET statement_type='Statement of Financial Position'", compiled)
        self.assertIn("extracted_data_items.id = 'row-1'", compiled)
        self.assertIn("coalesce(trim(extracted_data_items.statement_type), '') = ''", compiled)
        self.assertIn("coalesce(trim(extracted_data_items.template_field_id), '') != ''", compiled)


if __name__ == "__main__":
    unittest.main()
