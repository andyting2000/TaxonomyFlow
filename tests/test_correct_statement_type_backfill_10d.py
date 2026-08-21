import unittest

from scripts.correct_statement_type_backfill_10d import (
    PROPOSED_STATEMENT_TYPE,
    TARGET_ITEM_IDS,
    TARGET_STATEMENT_TYPE,
    CorrectionReport,
    CorrectionRow,
    build_correction_update_statement,
    render_report,
)


class CorrectStatementTypeBackfill10DTests(unittest.TestCase):
    def test_target_list_contains_exact_13_unique_ids(self):
        self.assertEqual(len(TARGET_ITEM_IDS), 13)
        self.assertEqual(len(set(TARGET_ITEM_IDS)), 13)
        self.assertIn("c7a39463-11cd-4e98-81e7-6062888991c0", TARGET_ITEM_IDS)
        self.assertIn("dc7d72a9-8ef9-4a6e-aea6-406665224ca5", TARGET_ITEM_IDS)

    def test_update_statement_is_limited_to_target_ids_and_current_statement_type(self):
        statement = build_correction_update_statement()
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))

        self.assertIn("UPDATE extracted_data_items SET statement_type=''", compiled)
        self.assertIn("extracted_data_items.id IN", compiled)
        self.assertIn(
            f"extracted_data_items.statement_type = '{TARGET_STATEMENT_TYPE}'",
            compiled,
        )
        for item_id in TARGET_ITEM_IDS:
            self.assertIn(item_id, compiled)

    def test_render_report_shows_dry_run_row_evidence(self):
        report = CorrectionReport(
            applied=False,
            expected_target_count=13,
            rows_found=1,
            rows_eligible=1,
            rows_updated=0,
            rows_missing=[],
            rows=[
                CorrectionRow(
                    item_id="c7a39463-11cd-4e98-81e7-6062888991c0",
                    job_id=3,
                    page_id="page-1",
                    page_number=1,
                    extracted_label="ASSETS",
                    extracted_value="46,410.85",
                    template_field_id="ifrs-smes:Assets",
                    current_statement_type=TARGET_STATEMENT_TYPE,
                    proposed_statement_type=PROPOSED_STATEMENT_TYPE,
                )
            ],
        )

        text = render_report(report)

        self.assertIn("Mode: dry-run", text)
        self.assertIn("expected_target_count: 13", text)
        self.assertIn("rows_eligible: 1", text)
        self.assertIn("rows_updated: 0", text)
        self.assertIn("item_id=c7a39463-11cd-4e98-81e7-6062888991c0", text)
        self.assertIn("job_id=3", text)
        self.assertIn("page_id=page-1", text)
        self.assertIn("page_number=1", text)
        self.assertIn("extracted_label=ASSETS", text)
        self.assertIn("extracted_value=46,410.85", text)
        self.assertIn("template_field_id=ifrs-smes:Assets", text)
        self.assertIn("current_statement_type=Director Business Review", text)
        self.assertIn("proposed_statement_type=''", text)


if __name__ == "__main__":
    unittest.main()
