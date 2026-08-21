import copy
import inspect
import json
import unittest
from argparse import Namespace
from pathlib import Path

from pydantic import ValidationError

from schemas import RankedCandidateItem
from scripts.design_ranked_candidate_backend_integration_18f_c import build_reports
from services.ranked_candidate_advisory_service import (
    RankedCandidateAdvisoryConfig,
    RankedCandidateAdvisoryError,
    advisory_capabilities,
    build_ranked_candidate_advisory_response,
    load_ranked_rows_from_report,
)
import services.ranked_candidate_advisory_service as advisory_service


def _candidate(qname="ssmt:CashAndBankBalances", score=0.72, risk_level="low"):
    return {
        "rank": 1,
        "qname": qname,
        "concept_label": "Cash and bank balances",
        "candidate_source": "deterministic_current_mapper",
        "candidate_sources_combined": ["deterministic_current_mapper", "taxonomy_lexical"],
        "score": score,
        "confidence_bucket": "candidate_medium",
        "risk_level": risk_level,
        "evidence": {
            "statement_family_match": True,
            "section_context_match": True,
            "label_similarity": 1.0,
        },
        "match_reasons": ["deterministic_method:dictionary"],
        "risk_reasons": [],
        "ambiguity_reasons": [],
        "blocking_reasons": [],
        "requires_human_review": False,
        "safe_for_auto_apply": True,
    }


def _row(row_id="row-1", candidates=None):
    candidates = list(candidates if candidates is not None else [_candidate()])
    return {
        "sample_id": "case_test",
        "row_id": row_id,
        "pdf_label": "Bank balances",
        "normalized_label": "bank balances",
        "value": "1000",
        "pdf_period": {"value_role": "current", "expected_year": 2025},
        "statement_family": "financial_position",
        "section_block": "cash",
        "candidate_coverage_status": "ranked_candidates_available" if candidates else "no_candidate",
        "candidate_count": len(candidates),
        "note_boundary": {},
        "candidates": candidates,
    }


class RankedCandidateBackendIntegrationDesignTests(unittest.TestCase):
    def test_feature_disabled_by_default_and_generation_fails_closed(self):
        config = RankedCandidateAdvisoryConfig()
        capabilities = advisory_capabilities(101, config=config)

        self.assertFalse(capabilities["enabled"])
        self.assertEqual(capabilities["default_mode"], "dry_run")
        self.assertFalse(capabilities["allow_persistence"])
        self.assertFalse(capabilities["safety"]["auto_apply_enabled"])

        with self.assertRaises(RankedCandidateAdvisoryError):
            build_ranked_candidate_advisory_response(
                job_id=101,
                ranked_rows=[_row()],
                config=config,
            )

    def test_dry_run_response_forces_no_persistence_or_mapping_mutation(self):
        config = RankedCandidateAdvisoryConfig(
            enabled=True,
            allow_persistence=True,
            default_mode="persisted_later",
        )
        before = [_row()]
        original = copy.deepcopy(before)

        response = build_ranked_candidate_advisory_response(
            job_id=101,
            filing_id=55,
            ranked_rows=before,
            config=config,
        )

        self.assertEqual(before, original)
        self.assertEqual(response["mode"], "dry_run")
        self.assertFalse(response["feature_flags"]["RANKED_CANDIDATES_ADVISORY_ALLOW_PERSISTENCE"])
        self.assertEqual(response["safety"]["confirmed_tag_id_mutations"], 0)
        self.assertEqual(response["safety"]["final_mapping_mutations"], 0)
        self.assertEqual(response["safety"]["ai_suggestion_table_writes"], 0)

    def test_candidates_are_always_human_review_and_never_safe_for_auto_apply(self):
        config = RankedCandidateAdvisoryConfig(enabled=True)

        response = build_ranked_candidate_advisory_response(
            job_id=101,
            ranked_rows=[_row()],
            config=config,
        )
        candidate = response["rows"][0]["candidates"][0]

        self.assertTrue(candidate["requires_human_review"])
        self.assertFalse(candidate["safe_for_auto_apply"])
        self.assertNotIn(candidate["recommended_action"], {"accept", "apply", "confirm"})
        encoded_rows = json.dumps(response["rows"], sort_keys=True)
        self.assertNotIn("confirmed_tag_id", encoded_rows)
        self.assertNotIn("final_mapping_update", encoded_rows)
        self.assertEqual(response["safety"]["confirmed_tag_id_mutations"], 0)

    def test_max_candidates_per_row_is_respected(self):
        config = RankedCandidateAdvisoryConfig(enabled=True, max_candidates_per_row=1)
        response = build_ranked_candidate_advisory_response(
            job_id=101,
            ranked_rows=[
                _row(
                    candidates=[
                        _candidate("ssmt:CashAndBankBalances", score=0.72),
                        _candidate("ifrs-smes:CashAndCashEquivalents", score=0.70),
                    ]
                )
            ],
            config=config,
        )

        self.assertEqual(len(response["rows"][0]["candidates"]), 1)
        self.assertEqual(response["profile"], "balanced")

    def test_balanced_profile_is_used_by_default(self):
        config = RankedCandidateAdvisoryConfig(enabled=True)
        response = build_ranked_candidate_advisory_response(
            job_id=101,
            ranked_rows=[_row()],
            config=config,
        )

        self.assertEqual(response["profile"], "balanced")
        self.assertEqual(response["rows"][0]["candidates"][0]["profile"], "balanced")
        self.assertEqual(
            response["rows"][0]["candidates"][0]["calibration_version"],
            "18F-B-balanced",
        )

    def test_invalid_profile_fails_closed(self):
        config = RankedCandidateAdvisoryConfig(enabled=True, default_profile="unsafe")

        with self.assertRaises(RankedCandidateAdvisoryError):
            build_ranked_candidate_advisory_response(
                job_id=101,
                ranked_rows=[_row()],
                config=config,
            )

    def test_missing_report_input_fails_safely(self):
        with self.assertRaises(RankedCandidateAdvisoryError):
            load_ranked_rows_from_report(Path("reports/does_not_exist_18f_c.json"))

    def test_schema_rejects_unsafe_candidate_values(self):
        safe_payload = {
            "rank": 1,
            "qname": "ssmt:CashAndBankBalances",
            "score": 0.9,
            "confidence_bucket": "candidate_high",
            "risk_level": "low",
        }
        RankedCandidateItem(**safe_payload)

        with self.assertRaises(ValidationError):
            RankedCandidateItem(**{**safe_payload, "safe_for_auto_apply": True})
        with self.assertRaises(ValidationError):
            RankedCandidateItem(**{**safe_payload, "requires_human_review": False})
        with self.assertRaises(ValidationError):
            RankedCandidateItem(**{**safe_payload, "recommended_action": "accept"})

    def test_config_flags_are_documented_with_safe_defaults(self):
        source = Path("config.py").read_text(encoding="utf-8")

        self.assertIn('"RANKED_CANDIDATES_ADVISORY_ENABLED"', source)
        self.assertIn('"RANKED_CANDIDATES_ADVISORY_DEFAULT_MODE"', source)
        self.assertIn('"RANKED_CANDIDATES_ADVISORY_ALLOW_PERSISTENCE"', source)
        self.assertIn('"RANKED_CANDIDATES_ADVISORY_DEFAULT_PROFILE"', source)
        self.assertIn('"RANKED_CANDIDATES_ADVISORY_MAX_ROWS"', source)
        self.assertIn('"RANKED_CANDIDATES_ADVISORY_MAX_CANDIDATES_PER_ROW"', source)
        self.assertIn('"RANKED_CANDIDATES_ADVISORY_ADMIN_ONLY"', source)
        self.assertIn('"false",', source)
        self.assertIn('"dry_run",', source)
        self.assertIn('"balanced",', source)

    def test_no_external_call_path_exists_in_service_scaffold(self):
        source = inspect.getsource(advisory_service)

        forbidden_snippets = [
            "import requests",
            "import httpx",
            "urllib.request",
            "OpenAI(",
            "AsyncOpenAI(",
            "subprocess.",
            "aiohttp",
        ]
        for snippet in forbidden_snippets:
            self.assertNotIn(snippet, source)

    def test_reports_are_json_serializable(self):
        args = Namespace(
            calibration_summary="reports/hybrid_candidate_calibration_summary_18f_b.json",
            recommended_profile="reports/hybrid_candidate_calibration_recommended_profile_18f_b.json",
        )
        calibration_summary = {
            "summary": {
                "recommended_profile": "balanced",
                "recommended_reason": "Balanced preserves coverage and controls risk.",
                "backend_advisory_integration_justified": True,
                "recommended_metrics": {
                    "candidate_coverage_rate": 0.6036,
                    "top1_precision_if_evaluable": 0.8,
                    "top3_recall_if_evaluable": 0.5825,
                    "top5_recall_if_evaluable": 0.5825,
                    "high_or_critical_candidate_ratio": 0.2574,
                    "critical_candidate_count": 0,
                    "safe_for_auto_apply_count": 0,
                    "requires_human_review_count": 983,
                },
            }
        }
        recommended_profile = {
            "recommended_profile": {
                "basis": {
                    "candidate_coverage_rate": 0.6036,
                    "safe_for_auto_apply_count": 0,
                }
            }
        }

        reports = build_reports(
            args=args,
            generated_at="2026-06-25T00:00:00Z",
            calibration_summary=calibration_summary,
            recommended_profile=recommended_profile,
        )

        self.assertEqual(set(reports), {"design", "contract", "guardrails", "phases"})
        json.dumps(reports, sort_keys=True)


if __name__ == "__main__":
    unittest.main()
