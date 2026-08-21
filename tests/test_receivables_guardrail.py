import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from lxml import etree

from services.smart_ai_processor import smart_ai_processor
from services.xbrl_generator import XBRLGenerator
from services.xbrl_template_service import (
    XBRLTemplateService,
    automatic_mapping_guardrail_reason,
    label_supports_receivables_mapping,
    receivables_guardrail_allows,
)


TARGET_CONCEPT = "ifrs-smes:TradeAndOtherCurrentReceivables"


def _write_template_file(path: Path, concepts):
    path.write_text(
        json.dumps(
            {
                "_metadata": {"namespaces": {"ifrs-smes": "urn:ifrs-smes"}},
                "templates": {
                    "210000": {
                        "code": "210000",
                        "description": "Statement of Financial Position",
                        "total_concepts": len(concepts),
                        "concepts": concepts,
                    }
                },
            }
        ),
        encoding="utf-8",
    )


class ReceivablesGuardrailTests(unittest.TestCase):
    def test_summary_receivable_labels_remain_allowed(self):
        allowed_labels = [
            "OTHER DEBTOR - IH(I.T)",
            "TRADE RECEIVABLES",
            "Trade and other receivables",
            "Accounts receivable",
            "Amount due from related company",
            "Due from director",
            "Receivable from shareholder",
        ]

        for label in allowed_labels:
            with self.subTest(label=label):
                self.assertTrue(label_supports_receivables_mapping(label))
                self.assertTrue(receivables_guardrail_allows(TARGET_CONCEPT, label))

    def test_company_detail_labels_without_receivable_words_are_blocked(self):
        blocked_labels = [
            "CORPSEC SERVICES SDN BHD",
            "MALAYSIAN RESOURCES CORPORATION BHD",
            "PERMODALAN NASIONAL BERHAD",
            "BBS TRUST INT'L LIMITED",
            "Vendor Customer Name",
        ]

        for label in blocked_labels:
            with self.subTest(label=label):
                self.assertFalse(receivables_guardrail_allows(TARGET_CONCEPT, label))
                self.assertEqual(
                    automatic_mapping_guardrail_reason(TARGET_CONCEPT, label),
                    "receivables_detail_guardrail",
                )

    def test_company_detail_labels_with_explicit_due_from_or_receivable_are_allowed(self):
        self.assertTrue(
            receivables_guardrail_allows(
                TARGET_CONCEPT,
                "Amount due from ACME SDN BHD",
            )
        )
        self.assertTrue(
            receivables_guardrail_allows(
                TARGET_CONCEPT,
                "Receivable from CORPSEC SERVICES SDN BHD",
            )
        )

    def test_guardrail_does_not_change_unrelated_concepts(self):
        self.assertTrue(
            receivables_guardrail_allows(
                "ifrs-smes:CashAndCashEquivalents",
                "CORPSEC SERVICES SDN BHD",
            )
        )

    def test_hybrid_match_blocks_company_detail_without_replacement(self):
        concepts = [
            {
                "id": TARGET_CONCEPT,
                "label": "CORPSEC SERVICES SDN BHD",
                "namespace": "ifrs-smes",
                "required": False,
            },
            {
                "id": "ifrs-smes:CashAndCashEquivalents",
                "label": "Cash and cash equivalents",
                "namespace": "ifrs-smes",
                "required": False,
            },
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            template_path = Path(temp_dir) / "mpers_templates.json"
            _write_template_file(template_path, concepts)
            service = XBRLTemplateService(str(template_path))
            concept_id, score = asyncio.run(
                service.find_matching_concept_hybrid(
                    extracted_label="CORPSEC SERVICES SDN BHD",
                    template_code="210000",
                    db=None,
                )
            )

        self.assertIsNone(concept_id)
        self.assertEqual(score, 0.0)

    def test_llm_concept_match_blocks_receivables_detail_candidate(self):
        template = {
            "description": "Statement of Financial Position",
            "concepts": [
                {
                    "id": TARGET_CONCEPT,
                    "label": "Trade and other current receivables",
                    "required": False,
                }
            ],
        }

        result = smart_ai_processor._match_from_llm_concept(
            concept_id=TARGET_CONCEPT,
            extracted_label="CORPSEC SERVICES SDN BHD",
            statement_code="210000",
            template=template,
        )

        self.assertFalse(result["matched"])
        self.assertEqual(result["blocked_reason"], "receivables_detail_guardrail")
        self.assertEqual(result["blocked_concept_id"], TARGET_CONCEPT)

    def test_llm_concept_match_allows_receivable_summary_candidate(self):
        template = {
            "description": "Statement of Financial Position",
            "concepts": [
                {
                    "id": TARGET_CONCEPT,
                    "label": "Trade and other current receivables",
                    "required": False,
                }
            ],
        }

        result = smart_ai_processor._match_from_llm_concept(
            concept_id=TARGET_CONCEPT,
            extracted_label="OTHER DEBTOR - RH",
            statement_code="210000",
            template=template,
        )

        self.assertTrue(result["matched"])
        self.assertEqual(result["field_id"], TARGET_CONCEPT)

    def test_generator_skips_persisted_blocked_receivables_template_fact(self):
        generator = XBRLGenerator()
        root = etree.Element("root")
        item = SimpleNamespace(
            confirmed_tag=None,
            template_field_id=TARGET_CONCEPT,
            extracted_label="CORPSEC SERVICES SDN BHD",
            extracted_value="864.00",
            statement_type="Statement of Financial Position",
        )

        added = generator._add_financial_fact(
            root,
            item,
            2024,
            {
                "current_instant": "asof_20241231",
                "current_instant_separate": "asof_20241231_SeparateMember",
            },
            "MYR",
        )

        self.assertFalse(added)
        self.assertEqual(len(root), 0)

    def test_generator_allows_persisted_receivables_summary_fact(self):
        generator = XBRLGenerator()
        root = etree.Element("root")
        item = SimpleNamespace(
            confirmed_tag=None,
            template_field_id=TARGET_CONCEPT,
            extracted_label="OTHER DEBTOR - AS",
            extracted_value="133279.62",
            statement_type="Statement of Financial Position",
        )

        added = generator._add_financial_fact(
            root,
            item,
            2024,
            {
                "current_instant": "asof_20241231",
                "current_instant_separate": "asof_20241231_SeparateMember",
            },
            "MYR",
        )

        self.assertTrue(added)
        self.assertEqual(len(root), 1)


if __name__ == "__main__":
    unittest.main()
