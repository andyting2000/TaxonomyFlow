import json
from pathlib import Path
import unittest

from schemas import RowMappingEligibility
from services.section_aware_mapping_context_builder import (
    MappingContextLimits,
    build_section_aware_mapping_context,
)
from services.section_aware_taxonomy_candidate_retriever import retrieve_section_aware_candidates
from services.section_aware_taxonomy_concept_cards import build_taxonomy_concept_inventory


class SectionAwareMappingContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cards, cls.metadata = build_taxonomy_concept_inventory()

    def candidate_set(self):
        return retrieve_section_aware_candidates(
            row_eligibility=RowMappingEligibility(source_row_id="r2", outcome="fact_candidate", eligible=True),
            row={"source_row_id": "r2", "label": "Cash and cash equivalents", "current_value": "10"},
            section_id="s1",
            subsection_id=None,
            template_group_ids=["210000"],
            statement_families=["financial_position"],
            inventory_cards=self.cards,
            concept_inventory_hash=self.metadata["concept_inventory_hash"],
            max_candidates=3,
        )

    def test_context_preserves_values_and_bounds_neighbors_and_candidates(self):
        rows = [
            {"source_row_id": "r1", "label": "Current assets", "row_type": "heading", "table_id": "t1"},
            {"source_row_id": "r2", "label": "Cash and cash equivalents", "normalized_label": "cash and cash equivalents", "current_value": "10", "prior_value": "8", "current_year": 2025, "prior_year": 2024, "page_number": 2, "table_id": "t1", "parent_row_id": "r1"},
            {"source_row_id": "r3", "label": "Receivables", "current_value": "5", "table_id": "t1", "parent_row_id": "r1"},
            {"source_row_id": "r4", "label": "Inventories", "current_value": "3", "table_id": "t1", "parent_row_id": "r1"},
        ]
        context = build_section_aware_mapping_context(
            row=rows[1],
            section={"section_id": "s1", "section_title": "Statement of Financial Position", "canonical_section_type": "statement_of_financial_position"},
            rows_in_section=rows,
            candidate_set=self.candidate_set(),
            limits=MappingContextLimits(max_characters=5000, max_siblings=1, max_ancestors=1, max_descendants=1, max_candidate_cards=2, max_nearby_paragraphs=1),
            nearby_paragraphs=["Paragraph one", "Paragraph two"],
        )
        self.assertEqual(context["current_year_value"], "10")
        self.assertEqual(context["prior_year_value"], "8")
        self.assertEqual(context["parent_row_label"], "Current assets")
        self.assertLessEqual(len(context["sibling_labels"]), 1)
        self.assertLessEqual(len(context["candidate_concepts"]), 2)
        self.assertTrue(context["truncated"])
        self.assertLessEqual(len(json.dumps(context, ensure_ascii=True, sort_keys=True, separators=(",", ":"))), 5000)

    def test_context_does_not_include_whole_document_or_forbidden_artifacts(self):
        context = build_section_aware_mapping_context(
            row={"source_row_id": "r2", "label": "Cash and cash equivalents", "current_value": "10"},
            section={"section_id": "s1"},
            rows_in_section=[{"source_row_id": "r2", "label": "Cash and cash equivalents", "current_value": "10"}],
            candidate_set=self.candidate_set(),
        )
        encoded = json.dumps(context).lower()
        for forbidden in ("auditor_xml", "reference_xml", "benchmark_gold", "correct_qname", "confirmed_tag_id"):
            self.assertNotIn(forbidden, encoded)

    def test_job68_first_failing_context_fits_without_dropping_ranked_candidates(self):
        fixture_path = (
            Path(__file__).parent
            / "fixtures"
            / "toc_aware"
            / "fixture_n_job68_candidate_context_overflow.json"
        )
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        row = fixture["row"]
        section = fixture["section"]
        eligibility = RowMappingEligibility(
            source_row_id=row["source_row_id"],
            outcome="fact_candidate",
            eligible=True,
        )
        candidate_set = retrieve_section_aware_candidates(
            row=row,
            row_eligibility=eligibility,
            section_id=section["section_id"],
            subsection_id=section["subsection_id"],
            template_group_ids=section["template_group_ids"],
            statement_families=section["statement_families"],
            inventory_cards=self.cards,
            concept_inventory_hash=self.metadata["concept_inventory_hash"],
            max_candidates=fixture["limits"]["max_candidate_cards"],
        )

        context = build_section_aware_mapping_context(
            row=row,
            section=section,
            rows_in_section=[row],
            candidate_set=candidate_set,
            limits=MappingContextLimits(**fixture["limits"]),
        )

        encoded = json.dumps(
            context,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.assertLessEqual(len(encoded), fixture["limits"]["max_characters"])
        self.assertEqual(len(context["candidate_concepts"]), 8)
        self.assertEqual(
            [item["concept_id"] for item in context["candidate_concepts"]],
            [item.concept_id for item in candidate_set.candidates],
        )


if __name__ == "__main__":
    unittest.main()
