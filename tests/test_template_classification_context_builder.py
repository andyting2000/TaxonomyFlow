import json
import unittest
from unittest.mock import patch

from config import settings
from services.document_section_template_classifier import load_template_group_cards
from services.template_classification_context_builder import (
    build_template_classification_context,
)
from tests.template_classification_test_support import evidence


class TemplateClassificationContextBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cards, _metadata = load_template_group_cards()

    def test_context_is_bounded_and_records_omissions(self):
        rows = [
            evidence(
                f"paragraph-{index}",
                f"Paragraph {index} " + ("x" * 80),
                page=1,
                top=index,
                content_type="paragraph",
            )
            for index in range(12)
        ]
        rows.extend(
            [
                evidence(
                    f"row-{index}",
                    f"Row label {index}",
                    page=1,
                    top=20 + index,
                    content_type="extracted_row",
                )
                for index in range(10)
            ]
        )
        with (
            patch.object(settings, "toc_aware_template_classification_max_characters", 1800),
            patch.object(settings, "toc_aware_template_classification_max_paragraphs", 4),
            patch.object(settings, "toc_aware_template_classification_max_row_labels", 3),
            patch.object(settings, "toc_aware_template_classification_max_table_headers", 2),
            patch.object(settings, "toc_aware_template_classification_max_template_cards", 3),
        ):
            context = build_template_classification_context(
                source_section_id="note-1",
                source_title="Other information",
                normalized_title="other information",
                parent_title="Notes to Financial Statements",
                page_range={"pdf_page_start": 1, "pdf_page_end": 1},
                nearby_headings=["Issued Capital", "Related Party Transactions"],
                evidence=rows,
                template_cards=self.cards,
            )
        self.assertLessEqual(len(json.dumps(context, ensure_ascii=False)), 1800)
        self.assertTrue(context["truncated"])
        self.assertGreater(context["omitted_counts"]["paragraphs"], 0)
        self.assertGreater(context["omitted_counts"]["row_labels"], 0)
        self.assertGreater(context["omitted_counts"]["template_cards"], 0)

    def test_context_safety_excludes_prohibited_evaluation_and_mapping_data(self):
        context = build_template_classification_context(
            source_section_id="note-1",
            source_title="Issued Capital",
            normalized_title="issued capital",
            parent_title="Notes to Financial Statements",
            page_range={"pdf_page_start": 1, "pdf_page_end": 1},
            nearby_headings=[],
            evidence=[],
            template_cards=self.cards[:2],
        )
        safety = context["safety"]
        self.assertFalse(safety["auditor_xml_included"])
        self.assertFalse(safety["parsed_auditor_xbrl_facts_included"])
        self.assertFalse(safety["expected_template_ids_included"])
        self.assertFalse(safety["evaluation_labels_included"])
        self.assertFalse(safety["taxonomy_qname_answers_included"])
        self.assertFalse(safety["final_mapping_results_included"])
        serialized = json.dumps(context)
        self.assertNotIn("confirmed_tag_id", serialized)
        self.assertNotIn("\"qname\":", serialized.lower())


if __name__ == "__main__":
    unittest.main()
