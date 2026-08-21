import json
from pathlib import Path
import unittest

from schemas import RowMappingEligibility
from services.section_aware_initial_mapping_llm import deterministic_initial_mapping_decision
from services.section_aware_taxonomy_candidate_retriever import (
    RETRIEVAL_VERSION,
    retrieve_section_aware_candidates,
)
from services.section_aware_taxonomy_concept_cards import build_taxonomy_concept_inventory


FIXTURES = Path(__file__).parent / "fixtures" / "section_aware_mapping" / "fixtures_19c.json"
FAMILIES = {
    "210000": "financial_position",
    "220000": "financial_position",
    "310000": "profit_or_loss",
    "320100": "profit_or_loss",
    "510000": "cash_flows",
}


class SectionAwareCandidateRetrieverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cards, cls.metadata = build_taxonomy_concept_inventory()
        cls.fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))["fixtures"]

    def retrieve(self, label, group_ids, family=None, row_id="row-1"):
        eligibility = RowMappingEligibility(source_row_id=row_id, outcome="fact_candidate", eligible=True)
        return retrieve_section_aware_candidates(
            row={"source_row_id": row_id, "label": label, "current_value": "100"},
            row_eligibility=eligibility,
            section_id="section-1",
            subsection_id=None,
            template_group_ids=group_ids,
            statement_families=[family or FAMILIES.get(group_ids[0], "notes")],
            inventory_cards=self.cards,
            concept_inventory_hash=self.metadata["concept_inventory_hash"],
            max_candidates=8,
        )

    def test_fixture_recall_at_one_is_one_for_core_statement_rows(self):
        ranks = []
        for fixture in self.fixtures[:6]:
            result = self.retrieve(fixture["label"], fixture["template_group_ids"])
            qnames = [candidate.qname for candidate in result.candidates]
            ranks.append(qnames.index(fixture["expected_qname"]) + 1 if fixture["expected_qname"] in qnames else None)
            self.assertLessEqual(len(result.candidates), 8)
            self.assertTrue(all(set(candidate.concept_card.template_group_ids) & set(fixture["template_group_ids"]) for candidate in result.candidates))
        self.assertEqual(ranks, [1, 1, 1, 1, 1, 1])

    def test_scores_are_auditable_stable_and_tied_by_qname(self):
        first = self.retrieve("Revenue", ["310000"])
        second = self.retrieve("Revenue", ["310000"])
        self.assertEqual(first.model_dump(), second.model_dump())
        self.assertTrue(first.candidates[0].score.reasons)
        self.assertIn("not_a_correctness_probability", "_".join(first.candidates[0].score.reasons))
        self.assertEqual(first.candidates, sorted(first.candidates, key=lambda item: (-item.score.total_score, item.qname)))
        self.assertEqual(RETRIEVAL_VERSION, "19C-section-aware-retrieval-v2")

    def test_template_and_period_constraints_cannot_be_overridden_by_label(self):
        income = self.retrieve("Cash and cash equivalents", ["310000"])
        self.assertNotIn("ssmt:CashAndBankBalances", {item.qname for item in income.candidates})
        position = self.retrieve("Revenue", ["210000"])
        self.assertNotIn("ifrs-smes:Revenue", {item.qname for item in position.candidates})
        self.assertTrue(all(item.concept_card.period_type in {None, "instant"} for item in position.candidates))

    def test_top_k_hard_cap_no_safe_and_deterministic_advisory(self):
        capped = self.retrieve("Revenue", ["310000"])
        self.assertLessEqual(capped.top_k, 20)
        self.assertEqual(deterministic_initial_mapping_decision(capped)["selected_qname"], "ifrs-smes:Revenue")
        empty = retrieve_section_aware_candidates(
            row={"source_row_id": "r", "label": "Revenue", "current_value": "1"},
            row_eligibility=RowMappingEligibility(source_row_id="r", outcome="ambiguous_eligibility", eligible=False),
            section_id=None,
            subsection_id=None,
            template_group_ids=[],
            statement_families=[],
            inventory_cards=self.cards,
            concept_inventory_hash=self.metadata["concept_inventory_hash"],
            max_candidates=999,
        )
        self.assertEqual(empty.candidate_outcome, "row_not_eligible")
        self.assertEqual(empty.top_k, 20)
        self.assertFalse(empty.candidates)


if __name__ == "__main__":
    unittest.main()
