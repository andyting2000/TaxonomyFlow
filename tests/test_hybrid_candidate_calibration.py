import json
import unittest
from decimal import Decimal

from services.hybrid_candidate_calibration import (
    apply_ranking_profile_to_row,
    apply_ranking_profile_to_rows,
    build_profile_metrics,
    profile_config_to_dict,
    select_recommended_profile,
)
from services.hybrid_candidate_ranking_mapper import evaluate_candidate_rows
from services.pdf_xbrl_deterministic_alignment import PdfRowValue, canonical_label


def candidate(qname, *, score, risk="low", sources=("taxonomy_lexical",), evidence=None, blocking=None, ambiguity=None):
    return {
        "qname": qname,
        "concept_label": qname.split(":")[-1],
        "candidate_source": sources[0],
        "candidate_sources_combined": list(sources),
        "score": score,
        "risk_level": risk,
        "risk_reasons": [],
        "blocking_reasons": list(blocking or []),
        "ambiguity_reasons": list(ambiguity or []),
        "evidence": {
            "label_similarity": 0.9,
            "statement_family_match": True,
            "section_context_match": True,
            "row_role_match": True,
            **dict(evidence or {}),
        },
        "requires_human_review": True,
        "safe_for_auto_apply": False,
    }


def row(row_id, label, candidates):
    return {
        "sample_id": "case_test",
        "row_id": row_id,
        "pdf_label": label,
        "normalized_label": canonical_label(label),
        "value": "100",
        "statement_family": "financial_position",
        "section_block": "current_assets",
        "row_role": "component",
        "candidate_coverage_status": "ranked_candidates_available" if candidates else "no_candidate",
        "candidate_count": len(candidates),
        "blocked_candidate_count": 0,
        "filtered_candidate_count": 0,
        "blocked_candidates": [],
        "filtered_candidates": [],
        "candidates": list(candidates),
        "requires_human_review": True,
        "safe_for_auto_apply": False,
    }


class HybridCandidateCalibrationTests(unittest.TestCase):
    def profile_fixture_rows(self):
        return [
            row(
                "row-1:current",
                "Current assets",
                [
                    candidate("ifrs-smes:CurrentAssets", score=0.62, sources=("deterministic_current_mapper",)),
                    candidate("ifrs-smes:Assets", score=0.60, sources=("taxonomy_lexical",)),
                    candidate("ifrs-smes:TradeAndOtherCurrentReceivables", score=0.76, risk="high", sources=("taxonomy_lexical",)),
                    candidate(
                        "ifrs-smes:CurrentAssetsAlt",
                        score=0.57,
                        sources=("concept_playbook_lookup",),
                        evidence={"local_structured_match": True},
                    ),
                    candidate("ifrs-smes:Blocked", score=0.95, risk="critical", sources=("deterministic_current_mapper",), blocking=["blocked_by_note_boundary"]),
                ],
            ),
            row(
                "row-2:current",
                "Other asset",
                [
                    candidate(
                        "ifrs-smes:OtherCurrentAssets",
                        score=0.55,
                        sources=("section_concept_pack",),
                        evidence={"local_structured_match": True},
                    )
                ],
            ),
        ]

    def test_strict_profile_reduces_candidates_compared_with_recall(self):
        rows = self.profile_fixture_rows()
        strict = apply_ranking_profile_to_rows(rows, "strict", top_n=5)
        recall = apply_ranking_profile_to_rows(rows, "recall", top_n=5)

        self.assertLess(
            sum(row["candidate_count"] for row in strict),
            sum(row["candidate_count"] for row in recall),
        )

    def test_recall_profile_has_equal_or_higher_coverage_than_strict(self):
        rows = self.profile_fixture_rows()
        strict = apply_ranking_profile_to_rows(rows, "strict", top_n=5)
        recall = apply_ranking_profile_to_rows(rows, "recall", top_n=5)

        self.assertGreaterEqual(
            sum(1 for row in recall if row["candidate_count"] > 0),
            sum(1 for row in strict if row["candidate_count"] > 0),
        )

    def test_balanced_profile_sits_between_strict_and_recall(self):
        rows = self.profile_fixture_rows()
        strict = apply_ranking_profile_to_rows(rows, "strict", top_n=5)
        balanced = apply_ranking_profile_to_rows(rows, "balanced", top_n=5)
        recall = apply_ranking_profile_to_rows(rows, "recall", top_n=5)
        strict_count = sum(row["candidate_count"] for row in strict)
        balanced_count = sum(row["candidate_count"] for row in balanced)
        recall_count = sum(row["candidate_count"] for row in recall)

        self.assertLessEqual(strict_count, balanced_count)
        self.assertLessEqual(balanced_count, recall_count)

    def test_profile_thresholds_are_applied(self):
        fixture = row("row-1:current", "Low score", [candidate("ifrs-smes:LowScore", score=0.46, sources=("taxonomy_lexical",))])

        strict = apply_ranking_profile_to_row(fixture, "strict", top_n=5)
        recall = apply_ranking_profile_to_row(fixture, "recall", top_n=5)

        self.assertEqual(strict["candidate_count"], 0)
        self.assertEqual(recall["candidate_count"], 1)
        self.assertIn("profile_candidate_score_below_minimum", strict["filtered_candidates"][0]["filter_reasons"])

    def test_source_weights_affect_ranking_order(self):
        fixture = row(
            "row-1:current",
            "Current assets",
            [
                candidate("ifrs-smes:LexicalAssets", score=0.72, sources=("taxonomy_lexical",)),
                candidate("ifrs-smes:DeterministicAssets", score=0.68, sources=("deterministic_current_mapper",)),
            ],
        )

        balanced = apply_ranking_profile_to_row(fixture, "balanced", top_n=5)

        self.assertEqual(balanced["candidates"][0]["qname"], "ifrs-smes:DeterministicAssets")

    def test_taxonomy_lexical_does_not_dominate_corroborated_deterministic_local_candidate(self):
        fixture = row(
            "row-1:current",
            "Current assets",
            [
                candidate("ifrs-smes:LexicalAssets", score=0.80, sources=("taxonomy_lexical",)),
                candidate(
                    "ifrs-smes:CorroboratedAssets",
                    score=0.72,
                    sources=("deterministic_current_mapper", "concept_playbook_lookup"),
                    evidence={"local_structured_match": True},
                ),
            ],
        )

        balanced = apply_ranking_profile_to_row(fixture, "balanced", top_n=5)

        self.assertEqual(balanced["candidates"][0]["qname"], "ifrs-smes:CorroboratedAssets")

    def test_critical_risk_candidates_are_filtered(self):
        fixture = row(
            "row-1:current",
            "Critical",
            [candidate("ifrs-smes:Critical", score=0.95, risk="critical", sources=("deterministic_current_mapper",))],
        )

        for profile in ("strict", "balanced", "recall"):
            with self.subTest(profile=profile):
                profiled = apply_ranking_profile_to_row(fixture, profile, top_n=5)
                self.assertEqual(profiled["candidate_count"], 0)
                self.assertIn("profile_filters_critical_risk_candidate", profiled["filtered_candidates"][0]["filter_reasons"])

    def test_high_risk_candidates_require_corroboration_in_balanced_profile(self):
        fixture = row(
            "row-1:current",
            "Receivables",
            [
                candidate("ifrs-smes:HighStandalone", score=0.78, risk="high", sources=("taxonomy_lexical",)),
                candidate(
                    "ifrs-smes:HighCorroborated",
                    score=0.70,
                    risk="high",
                    sources=("taxonomy_lexical", "section_concept_pack"),
                    evidence={"local_structured_match": True},
                ),
            ],
        )

        balanced = apply_ranking_profile_to_row(fixture, "balanced", top_n=5)
        qnames = [item["qname"] for item in balanced["candidates"]]

        self.assertNotIn("ifrs-smes:HighStandalone", qnames)
        self.assertIn("ifrs-smes:HighCorroborated", qnames)

    def test_recall_profile_can_retain_more_high_risk_candidates_but_still_blocks_critical(self):
        fixture = row(
            "row-1:current",
            "Receivables",
            [
                candidate("ifrs-smes:HighStandalone", score=0.78, risk="high", sources=("taxonomy_lexical",)),
                candidate(
                    "ifrs-smes:HighCorroborated",
                    score=0.70,
                    risk="high",
                    sources=("taxonomy_lexical", "section_concept_pack"),
                    evidence={"local_structured_match": True},
                ),
                candidate("ifrs-smes:Critical", score=0.95, risk="critical", sources=("deterministic_current_mapper",)),
            ],
        )

        balanced = apply_ranking_profile_to_row(fixture, "balanced", top_n=5)
        recall = apply_ranking_profile_to_row(fixture, "recall", top_n=5)

        self.assertGreater(
            sum(1 for item in recall["candidates"] if item["risk_level"] == "high"),
            sum(1 for item in balanced["candidates"] if item["risk_level"] == "high"),
        )
        self.assertNotIn("ifrs-smes:Critical", [item["qname"] for item in recall["candidates"]])

    def test_safe_for_auto_apply_always_false_and_review_required_true(self):
        profiled = apply_ranking_profile_to_row(self.profile_fixture_rows()[0], "balanced", top_n=5)

        self.assertFalse(profiled["safe_for_auto_apply"])
        self.assertTrue(profiled["requires_human_review"])
        for item in profiled["candidates"]:
            self.assertFalse(item["safe_for_auto_apply"])
            self.assertTrue(item["requires_human_review"])

    def test_top_n_metrics_compute_correctly_per_profile(self):
        fixture = row(
            "row-1:current",
            "Current assets",
            [
                candidate("ifrs-smes:Assets", score=0.80, sources=("taxonomy_lexical",)),
                candidate("ifrs-smes:CurrentAssets", score=0.70, sources=("deterministic_current_mapper",)),
            ],
        )
        profiled = [apply_ranking_profile_to_row(fixture, "recall", top_n=5)]
        row_values = [
            PdfRowValue(
                sample_id="case_test",
                company_name="Example",
                pdf_row_id="row-1:current",
                source_pdf_row_id="row-1",
                pdf_label="Current assets",
                pdf_value="100",
                numeric_value=Decimal("100"),
                value_role="current",
                expected_year=2024,
                pdf_statement_type="Statement of financial position",
                pdf_statement_family="financial_position",
                pdf_page=1,
                pdf_row_order=1,
                row_type="numeric_fact",
            )
        ]
        facts = {
            "case_test": [
                {
                    "qname": "ifrs-smes:CurrentAssets",
                    "value": "100",
                    "normalized_value": "100",
                    "instant": "2024-12-31",
                }
            ]
        }

        report = evaluate_candidate_rows(profiled, row_values=row_values, facts_by_sample=facts)

        self.assertEqual(report["summary"]["top1_precision_if_evaluable"], 0.0)
        self.assertEqual(report["summary"]["top3_recall_if_evaluable"], 1.0)
        self.assertEqual(report["summary"]["top5_recall_if_evaluable"], 1.0)

    def test_recommended_profile_selection_works(self):
        metrics = {
            "strict": {"summary": {"candidate_coverage_rate": 0.55, "top1_precision_if_evaluable": 0.82, "high_or_critical_candidate_ratio": 0.1, "critical_candidate_count": 0, "risk_controlled": True, "candidate_quality_score": 70}},
            "balanced": {"summary": {"candidate_coverage_rate": 0.61, "top1_precision_if_evaluable": 0.76, "top3_recall_if_evaluable": 0.59, "top5_recall_if_evaluable": 0.60, "high_or_critical_candidate_ratio": 0.25, "critical_candidate_count": 0, "risk_controlled": True, "safe_for_auto_apply_count": 0, "candidate_quality_score": 78}},
            "recall": {"summary": {"candidate_coverage_rate": 0.65, "top1_precision_if_evaluable": 0.73, "high_or_critical_candidate_ratio": 0.35, "critical_candidate_count": 0, "risk_controlled": False, "candidate_quality_score": 74}},
        }

        recommended = select_recommended_profile(metrics)

        self.assertEqual(recommended["recommended_profile"], "balanced")
        self.assertTrue(recommended["backend_advisory_integration_justified"])

    def test_reports_serialize_valid_json(self):
        rows = self.profile_fixture_rows()
        profiled = apply_ranking_profile_to_rows(rows, "balanced", top_n=5)
        metrics = build_profile_metrics(profile="balanced", rows=profiled, evaluation={"summary": {}}, baseline_rows=rows)
        encoded = json.dumps({"metrics": metrics, "config": profile_config_to_dict("balanced")}, default=str)

        self.assertIn("candidate_quality_score", encoded)
        self.assertIn("safe_for_auto_apply", encoded)


if __name__ == "__main__":
    unittest.main()
