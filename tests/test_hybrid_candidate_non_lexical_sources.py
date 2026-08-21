import json
import unittest

from services.hybrid_candidate_ranking_mapper import build_reports, rank_candidates_for_record
from services.pdf_xbrl_deterministic_alignment import canonical_label
from services.taxonomy_concept_metadata import enrich_concept_record


def record(label, *, family, section, role="component", main=True, notes=False, candidates=None):
    return {
        "sample_id": "case_test",
        "company_name": "Example",
        "row_id": f"case_test:{canonical_label(label)}:current",
        "pdf_label": label,
        "normalized_label": canonical_label(label),
        "value": "100",
        "pdf_value": "100",
        "pdf_period": {"value_role": "current", "expected_year": 2024},
        "statement_family": family,
        "section_block": section,
        "row_role": role,
        "is_main_statement": main,
        "is_notes_context": notes,
        "candidates": list(candidates or []),
    }


def concept(qname, label, *, template_codes=()):
    return enrich_concept_record({"qname": qname, "concept_label": label, "template_codes": list(template_codes)})


def existing_candidate(qname, *, score=0.7, source="taxonomy_lexical"):
    return {
        "qname": qname,
        "concept_label": qname.split(":")[-1],
        "candidate_source": source,
        "candidate_sources_combined": [source],
        "score": score,
        "confidence_bucket": "candidate_low",
        "risk_level": "low",
        "risk_reasons": [],
        "evidence": {"label_similarity": 0.9, "statement_family_match": True, "section_context_match": True},
        "match_reasons": ["existing_test_candidate"],
        "blocking_reasons": [],
        "ambiguity_reasons": [],
        "requires_human_review": True,
        "safe_for_auto_apply": False,
    }


class HybridCandidateNonLexicalSourcesTests(unittest.TestCase):
    def test_non_lexical_and_lexical_agreement_improves_score_and_source_evidence(self):
        base = rank_candidates_for_record(
            record("Revenue", family="income_statement", section="revenue"),
            concepts=[concept("ifrs-smes:Revenue", "Revenue", template_codes=["310000"])],
            filter_mode="tightened",
        )
        enhanced = rank_candidates_for_record(
            record("Revenue", family="income_statement", section="revenue"),
            concepts=[concept("ifrs-smes:Revenue", "Revenue", template_codes=["310000"])],
            filter_mode="tightened",
            enable_local_sources=True,
        )

        self.assertEqual(enhanced["candidates"][0]["qname"], "ifrs-smes:Revenue")
        self.assertIn("taxonomy_lexical", enhanced["candidates"][0]["candidate_sources_combined"])
        self.assertIn("statement_role_pack", enhanced["candidates"][0]["candidate_sources_combined"])
        self.assertGreater(enhanced["candidates"][0]["score"], base["candidates"][0]["score"])

    def test_non_lexical_conflict_marks_ambiguity(self):
        ranked = rank_candidates_for_record(
            record(
                "Purchases",
                family="income_statement",
                section="cost_of_sales",
                candidates=[existing_candidate("ifrs-smes:Revenue", score=0.7)],
            ),
            concepts=[],
            filter_mode="tightened",
            enable_local_sources=True,
            include_existing_candidates=True,
            include_standard_sources=False,
            top_n=2,
        )

        self.assertEqual(ranked["candidate_count"], 2)
        self.assertTrue(any(candidate["qname"] == "ifrs-smes:CostOfSales" for candidate in ranked["candidates"]))
        self.assertIn("multiple_competing_candidates_close_in_score", ranked["candidates"][0]["ambiguity_reasons"])

    def test_note_detail_row_blocks_main_statement_candidate(self):
        ranked = rank_candidates_for_record(
            record(
                "Loss for the year",
                family="notes",
                section="notes_detail",
                role="note_detail",
                main=False,
                notes=True,
                candidates=[existing_candidate("ifrs-smes:ProfitLoss", score=0.72)],
            ),
            concepts=[],
            filter_mode="tightened",
            include_existing_candidates=True,
            include_standard_sources=False,
        )

        self.assertFalse(ranked["candidates"])
        self.assertEqual(ranked["candidate_coverage_status"], "blocked_by_note_boundary")
        self.assertIn("note_detail_row_blocks_main_statement_concept", ranked["blocked_candidates"][0]["blocking_reasons"])

    def test_note_summary_total_generates_review_required_candidate_when_boundary_allows_support(self):
        ranked = rank_candidates_for_record(
            record("Total current liabilities", family="notes", section="notes_payables", role="total", main=False, notes=True),
            concepts=[],
            filter_mode="tightened",
            enable_local_sources=True,
            include_standard_sources=False,
        )

        self.assertEqual(ranked["candidates"][0]["qname"], "ifrs-smes:CurrentLiabilities")
        self.assertEqual(ranked["candidates"][0]["candidate_source"], "note_total_candidate")
        self.assertTrue(ranked["candidates"][0]["requires_human_review"])
        self.assertFalse(ranked["candidates"][0]["safe_for_auto_apply"])

    def test_safe_for_auto_apply_always_false_and_review_required_true(self):
        ranked = rank_candidates_for_record(
            record("Operating loss before working capital changes", family="cash_flow", section="cash_flow_operating"),
            concepts=[],
            filter_mode="tightened",
            enable_local_sources=True,
            include_standard_sources=False,
        )

        self.assertTrue(ranked["candidates"])
        for candidate in ranked["candidates"]:
            self.assertTrue(candidate["requires_human_review"])
            self.assertFalse(candidate["safe_for_auto_apply"])

    def test_reports_serialize_valid_json_with_local_sources(self):
        reports = build_reports(
            records=[record("Revenue", family="income_statement", section="revenue")],
            concepts=[],
            evaluation_report={"records": []},
            qwen_index={},
            local_concept_cards=[],
            row_values=[],
            facts_by_sample={},
            filter_mode="tightened",
            enable_local_sources=True,
            include_standard_sources=False,
        )

        encoded = json.dumps(reports, default=str)
        self.assertIn("statement_role_pack", encoded)
        self.assertIn("safe_for_auto_apply_count", encoded)


if __name__ == "__main__":
    unittest.main()
