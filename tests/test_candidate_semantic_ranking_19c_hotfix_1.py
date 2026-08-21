import json
from pathlib import Path
import re
import unittest

from schemas import RowMappingEligibility
from services.section_aware_initial_mapping_llm import deterministic_initial_mapping_decision
from services.section_aware_taxonomy_candidate_retriever import (
    audit_section_aware_candidate_scope,
    retrieve_section_aware_candidates,
)
from services.section_aware_taxonomy_concept_cards import (
    build_taxonomy_concept_inventory,
    normalize_concept_label,
)


FIXTURES = Path(__file__).parent / "fixtures" / "section_aware_mapping" / "fixtures_19c_hotfix_1.json"


def _concept_families(candidate):
    card = candidate.concept_card
    text = normalize_concept_label(
        " ".join(
            [
                card.qname,
                card.standard_label,
                card.local_name,
                *card.aliases,
                *card.parent_concepts,
            ]
        )
    )
    compact = re.sub(r"[^a-z0-9]", "", text)
    noncurrent = "noncurrent" in compact
    families = set()
    checks = {
        "receivable": "receivab",
        "payable": "payab",
        "reserve": "reserve",
        "asset": "asset",
        "liability": "liabilit",
        "equity": "equity",
        "inventory": "inventor",
        "investment": "invest",
        "tax": "tax",
        "expense": "expense",
        "cash": "cash",
        "capital": "capital",
        "total": "total",
    }
    for family, marker in checks.items():
        if marker in text or marker in compact:
            families.add(family)
    if noncurrent:
        families.add("noncurrent")
    elif "current" in text or "current" in compact:
        families.add("current")
    if "other comprehensive income" in text or "othercomprehensiveincome" in compact:
        families.add("oci")
    if "comprehensive income" in text or "comprehensiveincome" in compact:
        families.add("comprehensive")
    if ("profit loss" in text or "profitloss" in compact) and "comprehensive" not in families:
        families.add("ordinary_profit")
    return families


class CandidateSemanticRanking19CHotfix1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cards, cls.metadata = build_taxonomy_concept_inventory()
        cls.fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))["fixtures"]

    def retrieve(self, fixture):
        eligibility = RowMappingEligibility(
            source_row_id=fixture["id"],
            outcome="fact_candidate",
            eligible=True,
        )
        return retrieve_section_aware_candidates(
            row={"source_row_id": fixture["id"], "label": fixture["label"], "current_value": "100"},
            row_eligibility=eligibility,
            section_id="section-1",
            subsection_id=None,
            template_group_ids=fixture["template_group_ids"],
            statement_families=[fixture["statement_family"]],
            inventory_cards=self.cards,
            concept_inventory_hash=self.metadata["concept_inventory_hash"],
            max_candidates=8,
            sibling_labels=fixture.get("sibling_labels", []),
        )

    def test_sanitized_semantic_family_regressions(self):
        self.assertGreaterEqual(len(self.fixtures), 20)
        for fixture in self.fixtures:
            with self.subTest(fixture=fixture["id"]):
                result = self.retrieve(fixture)
                self.assertEqual(
                    result.semantic_source_label,
                    fixture.get("expected_semantic_label", normalize_concept_label(fixture["label"])),
                )
                if "expected_scope_limitation" in fixture:
                    self.assertIn(fixture["expected_scope_limitation"], result.semantic_scope_limitations)
                    self.assertEqual(
                        deterministic_initial_mapping_decision(result)["decision"],
                        fixture["expected_decision"],
                    )
                    continue
                self.assertTrue(result.candidates)
                families = _concept_families(result.candidates[0])
                self.assertTrue(set(fixture["expected_top1_families"]).issubset(families), families)
                self.assertFalse(set(fixture.get("forbidden_top1_families", [])).intersection(families), families)

    def test_raw_label_is_not_mutated_and_semantic_cleanup_is_auditable(self):
        fixture = next(item for item in self.fixtures if item["id"] == "FP-08")
        result = self.retrieve(fixture)
        self.assertEqual(fixture["label"], "TOTAL EQUITY AND LIABILITIES DRAFT WIE")
        self.assertEqual(result.semantic_source_label, "total equity and liabilities")
        self.assertIn("removed_trailing_evidence_noise:DRAFT", result.semantic_normalization_reasons)
        self.assertIn("removed_trailing_evidence_noise:WIE", result.semantic_normalization_reasons)

    def test_complete_scope_audit_includes_survivors_and_exclusions(self):
        fixture = next(item for item in self.fixtures if item["id"] == "CI-01")
        eligibility = RowMappingEligibility(source_row_id=fixture["id"], outcome="fact_candidate", eligible=True)
        audit = audit_section_aware_candidate_scope(
            row={"source_row_id": fixture["id"], "label": fixture["label"], "current_value": "100"},
            row_eligibility=eligibility,
            section_id="section-1",
            subsection_id=None,
            template_group_ids=fixture["template_group_ids"],
            statement_families=[fixture["statement_family"]],
            inventory_cards=self.cards,
            concept_inventory_hash=self.metadata["concept_inventory_hash"],
        )
        self.assertEqual(audit["candidate_count_before_filter"], 21)
        self.assertEqual(audit["candidate_count_after_filter"], 17)
        self.assertEqual(len(audit["candidate_records"]), 21)
        self.assertEqual(sum(record["selectable"] for record in audit["candidate_records"]), 17)
        self.assertTrue(all("concept_card" in record for record in audit["candidate_records"]))
        self.assertTrue(all(record.get("score") or record.get("exclusion_reason") for record in audit["candidate_records"]))

    def test_current_noncurrent_and_ordinary_income_oci_contrasts_are_explicit(self):
        cases = [
            ("Total current assets", "ifrs-smes:NoncurrentAssets", "current!=noncurrent"),
            ("Other receivables", "ifrs-smes:OtherReserves", "receivable!=reserve"),
            ("Other payables and accruals", "ifrs-smes:OtherReserves", "payable!=reserve"),
        ]
        for label, qname, reason in cases:
            with self.subTest(label=label, qname=qname):
                fixture = {
                    "id": qname,
                    "label": label,
                    "template_group_ids": ["210000"],
                    "statement_family": "financial_position",
                }
                eligibility = RowMappingEligibility(source_row_id=qname, outcome="fact_candidate", eligible=True)
                audit = audit_section_aware_candidate_scope(
                    row={"source_row_id": qname, "label": label, "current_value": "100"},
                    row_eligibility=eligibility,
                    section_id="section-1",
                    subsection_id=None,
                    template_group_ids=["210000"],
                    statement_families=["financial_position"],
                    inventory_cards=self.cards,
                    concept_inventory_hash=self.metadata["concept_inventory_hash"],
                )
                candidate = next(item for item in audit["candidate_records"] if item["qname"] == qname)
                self.assertGreater(candidate["score"]["semantic_contrast_penalty"], 0.0)
                self.assertTrue(any(reason in item for item in candidate["score"]["reasons"]))

        fixture = next(item for item in self.fixtures if item["id"] == "CI-07")
        eligibility = RowMappingEligibility(source_row_id=fixture["id"], outcome="fact_candidate", eligible=True)
        audit = audit_section_aware_candidate_scope(
            row={"source_row_id": fixture["id"], "label": fixture["label"], "current_value": "100"},
            row_eligibility=eligibility,
            section_id="section-1",
            subsection_id=None,
            template_group_ids=["420000"],
            statement_families=["comprehensive_income"],
            inventory_cards=self.cards,
            concept_inventory_hash=self.metadata["concept_inventory_hash"],
        )
        oci = next(item for item in audit["candidate_records"] if item["qname"] == "ifrs-smes:OtherComprehensiveIncome")
        self.assertGreater(oci["score"]["semantic_contrast_penalty"], 0.0)
        self.assertTrue(any("ordinary_income_or_profit!=oci" in item for item in oci["score"]["reasons"]))


if __name__ == "__main__":
    unittest.main()
