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
    biological_asset_guardrail_allows,
    label_supports_biological_asset_mapping,
)


def _write_template_file(path: Path, concepts):
    path.write_text(
        json.dumps(
            {
                "_metadata": {"namespaces": {"ssmt-mpers": "urn:ssmt-mpers"}},
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


class BiologicalAssetGuardrailTests(unittest.TestCase):
    def test_guardrail_allows_only_direct_biological_evidence(self):
        guarded_concept = "ssmt-mpers:CurrentBiologicalAssets"

        allowed_labels = [
            "Biological assets",
            "Livestock and cattle",
            "Agricultural produce",
            "Bearer plant assets",
            "Plantation assets",
            "Aquaculture stock",
        ]
        for label in allowed_labels:
            with self.subTest(label=label):
                self.assertTrue(label_supports_biological_asset_mapping(label))
                self.assertTrue(
                    biological_asset_guardrail_allows(guarded_concept, label)
                )

        blocked_labels = [
            "Profit and loss",
            "SHARE CAPITAL",
            "INFOHOUSE (I.T) SDN BHD",
            "Cash and bank",
            "Trade receivables",
            "Trade payables",
            "Accruals",
            "Creditors",
            "Revenue",
            "Expenses",
            "Balance sheet",
        ]
        for label in blocked_labels:
            with self.subTest(label=label):
                self.assertFalse(
                    biological_asset_guardrail_allows(guarded_concept, label)
                )

    def test_guardrail_does_not_change_non_biological_concepts(self):
        self.assertTrue(
            biological_asset_guardrail_allows(
                "ifrs-smes:TradeAndOtherCurrentReceivables",
                "INFOHOUSE (I.T) SDN BHD",
            )
        )

    def test_hybrid_match_blocks_biological_candidate_without_replacement(self):
        concepts = [
            {
                "id": "ssmt-mpers:CurrentBiologicalAssets",
                "label": "Share capital",
                "namespace": "ssmt-mpers",
                "required": False,
            },
            {
                "id": "ifrs-smes:Equity",
                "label": "Equity",
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
                    extracted_label="Share capital",
                    template_code="210000",
                    db=None,
                )
            )

        self.assertIsNone(concept_id)
        self.assertEqual(score, 0.0)

    def test_hybrid_match_allows_biological_candidate_with_evidence(self):
        concepts = [
            {
                "id": "ssmt-mpers:NoncurrentBiologicalAssets",
                "label": "Livestock",
                "namespace": "ssmt-mpers",
                "required": False,
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            template_path = Path(temp_dir) / "mpers_templates.json"
            _write_template_file(template_path, concepts)
            service = XBRLTemplateService(str(template_path))

            concept_id, score = asyncio.run(
                service.find_matching_concept_hybrid(
                    extracted_label="Livestock",
                    template_code="210000",
                    db=None,
                )
            )

        self.assertEqual(concept_id, "ssmt-mpers:NoncurrentBiologicalAssets")
        self.assertGreater(score, 0.5)

    def test_llm_concept_match_blocks_biological_candidate(self):
        template = {
            "description": "Statement of Financial Position",
            "concepts": [
                {
                    "id": "ssmt-mpers:CurrentBiologicalAssets",
                    "label": "Current biological assets",
                    "required": False,
                }
            ],
        }

        result = smart_ai_processor._match_from_llm_concept(
            concept_id="ssmt-mpers:CurrentBiologicalAssets",
            extracted_label="INFOHOUSE (I.T) SDN BHD",
            statement_code="210000",
            template=template,
        )

        self.assertFalse(result["matched"])
        self.assertEqual(result["blocked_reason"], "biological_asset_guardrail")

    def test_generator_skips_persisted_blocked_template_fact(self):
        generator = XBRLGenerator()
        root = etree.Element("root")
        item = SimpleNamespace(
            confirmed_tag=None,
            template_field_id="ssmt-mpers:CurrentBiologicalAssets",
            extracted_label="SHARE CAPITAL",
            extracted_value="5032604.00",
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

    def test_generator_allows_supported_biological_template_fact(self):
        generator = XBRLGenerator()
        root = etree.Element("root")
        item = SimpleNamespace(
            confirmed_tag=None,
            template_field_id="ssmt-mpers:CurrentBiologicalAssets",
            extracted_label="Biological assets",
            extracted_value="1000.00",
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
