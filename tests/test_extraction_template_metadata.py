import unittest
from types import SimpleNamespace

import services.smart_ai_processor as smart_ai_processor_module
from services.prompts.stage2_prompt_builder import stage2_prompt_builder
from services.smart_ai_processor import smart_ai_processor


class ExtractionTemplateMetadataTests(unittest.TestCase):
    def test_prompt_builder_uses_description_and_concepts_from_current_templates(self):
        template = {
            "code": "210000",
            "description": "Statement of Financial Position",
            "concepts": [
                {
                    "id": "ifrs-smes:CashAndCashEquivalents",
                    "label": "Cash and bank balances",
                    "namespace": "ifrs-smes",
                    "level": 1,
                    "required": True,
                }
            ],
        }

        prompt = stage2_prompt_builder.build_multi_template_extraction_prompt(
            templates=[template],
            statement_codes=["210000"],
            section_locations=["full"],
            page_context="Cash and bank balances 1,000",
        )

        self.assertIn("Statement of Financial Position", prompt)
        self.assertIn("210000", prompt)
        self.assertIn("ifrs-smes:CashAndCashEquivalents", prompt)
        self.assertIn("Cash and bank balances", prompt)
        self.assertNotIn("Unknown Statement", prompt)

    def test_extracted_data_item_gets_statement_type_from_template_description(self):
        template = {
            "code": "210000",
            "description": "Statement of Financial Position",
            "concepts": [],
        }
        cleaned_item = {
            "label": "Cash and bank balances",
            "value": "1,000",
            "year": 2024,
        }

        item = smart_ai_processor._create_extracted_data_item(
            page_id="page-1",
            cleaned_item=cleaned_item,
            template=template,
            statement_code="210000",
        )

        self.assertEqual(item.statement_type,
                         "Statement of Financial Position")
        self.assertEqual(item.extracted_label, "Cash and bank balances")
        self.assertEqual(item.extracted_value, "1,000")
        self.assertEqual(item.financial_year, 2024)

    def test_statement_type_falls_back_to_template_code_when_description_missing(self):
        statement_type = smart_ai_processor._get_template_statement_type(
            template={"code": "730000", "concepts": []},
            statement_code="730000",
        )

        self.assertEqual(statement_type, "730000")

    def test_extraction_quality_summary_counts_duplicate_candidates(self):
        items = [
            SimpleNamespace(
                extracted_label="Cash and bank balances",
                extracted_value="1,000",
                value_previous_year=None,
                statement_type="Statement of Financial Position",
                template_field_id="ifrs-smes:Cash",
                is_reviewed=True,
                confirmed_tag_id=None,
            ),
            SimpleNamespace(
                extracted_label=" Cash and bank balances ",
                extracted_value="1,000",
                value_previous_year=None,
                statement_type="",
                template_field_id=None,
                is_reviewed=False,
                confirmed_tag_id=42,
            ),
            SimpleNamespace(
                extracted_label="Inventory",
                extracted_value="(50)",
                value_previous_year="(25)",
                statement_type="Statement of Financial Position",
                template_field_id="",
                is_reviewed=False,
                confirmed_tag_id=None,
            ),
        ]

        summary = smart_ai_processor._build_extraction_quality_summary(items)

        self.assertEqual(summary["total_extracted_rows"], 3)
        self.assertEqual(summary["rows_with_template_field_id"], 1)
        self.assertEqual(summary["rows_without_template_field_id"], 2)
        self.assertEqual(summary["rows_with_blank_statement_type"], 1)
        self.assertEqual(summary["duplicate_label_count"], 1)
        self.assertEqual(summary["duplicate_label_value_count"], 1)
        self.assertEqual(summary["suspicious_signed_value_count"], 1)
        self.assertEqual(summary["reviewed_count"], 1)
        self.assertEqual(summary["tagged_count"], 1)
        self.assertEqual(summary["reviewed_or_tagged_count"], 2)
        self.assertEqual(summary["duplicate_label_candidates"]
                         [0]["label"], "Cash and bank balances")
        self.assertEqual(summary["duplicate_label_candidates"][0]["count"], 2)
        self.assertEqual(summary["duplicate_label_value_candidates"]
                         [0]["label"], "Cash and bank balances")
        self.assertEqual(
            summary["duplicate_label_value_candidates"][0]["value"], "1,000")
        self.assertEqual(
            summary["duplicate_label_value_candidates"][0]["count"], 2)

    def test_extraction_quality_summary_logging_uses_metrics_terms(self):
        items = [
            SimpleNamespace(
                extracted_label="Cash and bank balances",
                extracted_value="1,000",
                value_previous_year=None,
                statement_type="Statement of Financial Position",
                template_field_id="ifrs-smes:Cash",
                is_reviewed=True,
                confirmed_tag_id=None,
            ),
            SimpleNamespace(
                extracted_label="Cash and bank balances",
                extracted_value="1,000",
                value_previous_year=None,
                statement_type="",
                template_field_id=None,
                is_reviewed=False,
                confirmed_tag_id=42,
            ),
        ]

        with self.assertLogs(smart_ai_processor_module.logger.name, level="INFO") as captured:
            summary = smart_ai_processor._log_extraction_quality_summary(
                job_id=7,
                page_num=0,
                items=items,
                matched_count=2,
                validation_warnings_count=1,
                templates_used_count=1,
            )

        joined = "\n".join(captured.output)
        self.assertEqual(summary["duplicate_label_count"], 1)
        self.assertIn("total_extracted_rows=2", joined)
        self.assertIn("rows_with_template_field_id=1", joined)
        self.assertIn("rows_with_blank_statement_type=1", joined)
        self.assertIn("duplicate_label_count=1", joined)
        self.assertIn("duplicate_label_value_count=1", joined)
        self.assertIn("validation_warnings=1", joined)
        self.assertIn("templates_used=1", joined)
        self.assertIn("Duplicate extraction candidates", joined)


if __name__ == "__main__":
    unittest.main()
