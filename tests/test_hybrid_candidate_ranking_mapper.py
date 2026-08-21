import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from services.hybrid_candidate_ranking_mapper import (
    SAFETY,
    build_concept_catalog,
    build_reports,
    evaluate_candidate_rows,
    load_cached_qwen_candidates,
    load_taxonomy_concept_metadata,
    rank_candidate_rows,
    rank_candidates_for_record,
)
from services.pdf_xbrl_deterministic_alignment import PdfRowValue, canonical_label


def record(label, *, family="financial_position", section="current_assets", role="component", qname=None):
    return {
        "sample_id": "case_test",
        "company_name": "Example",
        "pdf_row_id": f"case_test:{canonical_label(label)}:current",
        "pdf_label": label,
        "normalized_label": canonical_label(label),
        "pdf_value": "100",
        "pdf_period": {"value_role": "current", "expected_year": 2024},
        "statement_family": family,
        "section_block": section,
        "row_role": role,
        "predicted_qname": qname,
        "predicted_concept_label": qname.split(":")[-1] if qname else None,
        "candidate_generation_method": "statement_template" if qname else None,
        "confidence_bucket": "review_required" if qname else "no_match",
        "safe_for_auto_apply": False,
        "requires_human_review": True,
    }


def concepts():
    return [
        {
            "qname": "ifrs-smes:Revenue",
            "concept_label": "Revenue",
            "normalized_label": "revenue",
            "statement_families": ["income_statement"],
            "template_codes": ["310000"],
            "concept_family": "profit_loss",
        },
        {
            "qname": "ifrs-smes:CurrentAssets",
            "concept_label": "Current assets",
            "normalized_label": "current assets",
            "statement_families": ["financial_position"],
            "template_codes": ["210000"],
            "concept_family": "financial_position",
        },
        {
            "qname": "ifrs-smes:Assets",
            "concept_label": "Assets",
            "normalized_label": "assets",
            "statement_families": ["financial_position"],
            "template_codes": ["210000"],
            "concept_family": "financial_position",
        },
        {
            "qname": "ifrs-smes:PropertyPlantAndEquipment",
            "concept_label": "Property Plant And Equipment",
            "normalized_label": "property plant and equipment",
            "statement_families": ["financial_position"],
            "template_codes": ["210000"],
            "concept_family": "financial_position",
        },
    ]


class HybridCandidateRankingMapperTests(unittest.TestCase):
    def test_generates_top_n_candidates_for_row(self):
        ranked = rank_candidates_for_record(
            record("Current assets", family="financial_position", section="current_assets", role="total"),
            concepts=concepts(),
            top_n=3,
        )

        self.assertGreaterEqual(ranked["candidate_count"], 1)
        self.assertLessEqual(len(ranked["candidates"]), 3)
        self.assertEqual(ranked["candidate_coverage_status"], "ranked_candidates_available")

    def test_preserves_existing_deterministic_candidate_as_source(self):
        ranked = rank_candidates_for_record(
            record("Current assets", qname="ifrs-smes:CurrentAssets"),
            concepts=concepts(),
        )

        top = ranked["candidates"][0]
        self.assertEqual(top["qname"], "ifrs-smes:CurrentAssets")
        self.assertIn("deterministic_current_mapper", top["candidate_sources_combined"])

    def test_lexical_taxonomy_candidate_generation_works_with_local_fixture(self):
        ranked = rank_candidates_for_record(
            record("Revenue", family="income_statement", section="revenue"),
            concepts=concepts(),
        )

        self.assertIn("ifrs-smes:Revenue", [item["qname"] for item in ranked["candidates"]])

    def test_statement_family_filter_removes_incompatible_candidates(self):
        ranked = rank_candidates_for_record(
            record("Revenue", family="financial_position", section="current_assets"),
            concepts=concepts(),
        )

        self.assertNotIn("ifrs-smes:Revenue", [item["qname"] for item in ranked["candidates"]])

    def test_note_detail_boundary_blocks_unsafe_candidates(self):
        ranked = rank_candidates_for_record(
            record(
                "Depreciation of property plant and equipment",
                family="notes",
                section="notes_ppe",
                role="note_detail",
            ),
            concepts=concepts(),
        )

        self.assertEqual(ranked["candidate_coverage_status"], "blocked_by_note_boundary")
        self.assertTrue(ranked["blocked_candidates"])
        self.assertFalse(ranked["candidates"])

    def test_generic_label_produces_higher_risk(self):
        ranked = rank_candidates_for_record(
            record("Total", qname="ifrs-smes:Assets"),
            concepts=concepts(),
        )

        self.assertEqual(ranked["candidates"][0]["risk_level"], "high")
        self.assertIn("generic_or_subtotal_label", ranked["candidates"][0]["risk_reasons"])

    def test_competing_candidates_close_in_score_are_marked_ambiguous(self):
        fixture_concepts = [
            {**concepts()[1], "qname": "ifrs-smes:CurrentAssets", "concept_label": "Current assets"},
            {**concepts()[1], "qname": "ifrs-smes:CurrentAssetTotal", "concept_label": "Current assets"},
        ]
        ranked = rank_candidates_for_record(
            record("Current assets", family="financial_position", section="current_assets"),
            concepts=fixture_concepts,
            top_n=2,
        )

        self.assertIn("multiple_competing_candidates_close_in_score", ranked["candidates"][0]["ambiguity_reasons"])

    def test_safe_for_auto_apply_is_always_false_and_review_required_true(self):
        ranked = rank_candidates_for_record(
            record("Current assets", qname="ifrs-smes:CurrentAssets"),
            concepts=concepts(),
        )

        for candidate in ranked["candidates"]:
            self.assertFalse(candidate["safe_for_auto_apply"])
            self.assertTrue(candidate["requires_human_review"])

    def test_top_n_evaluation_metrics_compute_correctly(self):
        ranked_rows = [
            {
                "sample_id": "case_test",
                "row_id": "row-1:current",
                "pdf_label": "Current assets",
                "normalized_label": "current assets",
                "candidates": [
                    {"qname": "ifrs-smes:Assets", "risk_level": "medium"},
                    {"qname": "ifrs-smes:CurrentAssets", "risk_level": "low"},
                ],
            }
        ]
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
                    "context_ref": "c1",
                    "fact_id": "f1",
                }
            ]
        }

        report = evaluate_candidate_rows(ranked_rows, row_values=row_values, facts_by_sample=facts)

        self.assertEqual(report["summary"]["top1_precision_if_evaluable"], 0.0)
        self.assertEqual(report["summary"]["top3_recall_if_evaluable"], 1.0)
        self.assertEqual(report["summary"]["top5_recall_if_evaluable"], 1.0)

    def test_missing_taxonomy_metadata_is_handled_gracefully(self):
        concepts_loaded, diagnostics = load_taxonomy_concept_metadata(
            "missing-taxonomy-fixture.json",
            allow_missing=True,
        )

        self.assertEqual(concepts_loaded, [])
        self.assertEqual(diagnostics["status"], "missing_allowed")

    def test_missing_qwen_report_is_handled_gracefully(self):
        index, diagnostics = load_cached_qwen_candidates("missing-qwen-dir", allow_missing=True)

        self.assertEqual(index, {})
        self.assertEqual(diagnostics["status"], "missing_allowed")

    def test_no_external_calls_are_made(self):
        self.assertFalse(SAFETY["external_llm_called"])
        self.assertFalse(SAFETY["qwen_called"])
        self.assertFalse(SAFETY["supervisor_called"])
        self.assertFalse(SAFETY["database_mutated"])

    def test_reports_serialize_valid_json(self):
        rows = [record("Current assets", qname="ifrs-smes:CurrentAssets")]
        catalog, metadata = build_concept_catalog(rows, allow_missing_taxonomy=True, taxonomy_metadata_path="missing-taxonomy-fixture.json")
        reports = build_reports(
            records=rows,
            concepts=catalog or concepts(),
            evaluation_report={"records": []},
            qwen_index={},
            row_values=[],
            facts_by_sample={},
            metadata_diagnostics=metadata,
            qwen_diagnostics={"status": "not_requested"},
        )

        encoded = json.dumps(reports, default=str)
        self.assertIn("ranking", reports)
        self.assertIn("safe_for_auto_apply_count", encoded)

    def test_taxonomy_template_metadata_loads_fixture(self):
        payload = {
            "templates": {
                "310000": {
                    "concepts": [
                        {
                            "id": "ifrs-smes:Revenue",
                            "label": "Revenue",
                            "required": False,
                        }
                    ]
                }
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "taxonomy.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded, diagnostics = load_taxonomy_concept_metadata(path)

        self.assertEqual(diagnostics["concept_count"], 1)
        self.assertEqual(loaded[0]["statement_families"], ["income_statement"])

    def test_rank_candidate_rows_respects_debug_label(self):
        rows = rank_candidate_rows(
            [record("Current assets"), record("Revenue", family="income_statement")],
            concepts=concepts(),
            debug_label="revenue",
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["normalized_label"], "revenue")


if __name__ == "__main__":
    unittest.main()
