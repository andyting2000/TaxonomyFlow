import json
import tempfile
import unittest
from pathlib import Path

from scripts.analyze_supervisor_evaluation_17d_b_hotfix_4 import (
    build_hotfix_reports,
    classify_broad_substitute,
    classify_mapper_outcome,
    relaxation_candidate,
    write_hotfix_reports,
)
from scripts.analyze_supervisor_calibration_17d_b_hotfix_5 import (
    build_calibration_reports,
    classify_broad_substitute_calibrated,
    classify_omission_calibrated,
    classify_safe_accept_relaxation,
    write_calibration_reports,
)
from scripts.analyze_supervisor_safe_accept_threshold_17d_b_hotfix_6 import (
    build_threshold_reports,
    classify_safe_accept_threshold,
    write_threshold_reports,
)
from services.supervisor_mapping_review import build_supervisor_prompt


def _review(decision="needs_human_review", *, issues=None, risk="medium", action="keep_for_human_review", safe=False):
    return {
        "review_decision": decision,
        "risk_level": risk,
        "reason": "fixture supervisor reason",
        "issues": [{"type": issue, "description": issue} for issue in (issues or [])],
        "recommended_action": action,
        "confidence_adjustment": "decrease" if not safe else "keep",
        "safe_to_accept": safe,
        "normalization_diagnostics": {
            "normalization_reasons": [
                "medium_or_high_risk_cannot_be_safe_accept" if risk in {"medium", "high"} else "",
                "recommended_action_not_accept_cannot_be_safe_accept" if action != "accept" else "",
            ]
        },
    }


def _record(
    row_id,
    label,
    *,
    status="suggested",
    selected="ifrs-smes:Revenue",
    correct="ifrs-smes:Revenue",
    statement="Statement of Comprehensive Income",
    row_type="numeric_fact",
    review=None,
    mapper_has_prediction=True,
    mapper_correct=True,
    mapper_wrong=False,
    reason="exact alias match fixture",
):
    return {
        "row": {
            "source_case_id": "case_001",
            "extracted_row_id": row_id,
            "label": label,
            "statement_type": statement,
            "row_type": row_type,
        },
        "mapper_selection": {
            "status": status,
            "selected_template_field_id": selected if mapper_has_prediction else None,
            "selected_concept_qname": selected if mapper_has_prediction else None,
            "confidence": 0.97 if mapper_has_prediction else 0.0,
            "reason": reason,
        },
        "supervisor_review": review or _review(),
        "local_scoring": {
            "correct_template_field_id": correct,
            "correct_concept_qname": correct,
            "mapper_selected_template_field_id": selected if mapper_has_prediction else None,
            "mapper_selected_concept_qname": selected if mapper_has_prediction else None,
            "mapper_has_prediction": mapper_has_prediction,
            "mapper_correct": mapper_correct,
            "mapper_wrong": mapper_wrong,
            "supervisor_agreed": (review or _review()).get("review_decision") == "agree",
            "supervisor_safe_to_accept": (review or _review()).get("safe_to_accept"),
            "correct_mapping_unnecessarily_blocked": bool(mapper_correct and not (review or _review()).get("safe_to_accept")),
            "false_agree": False,
            "false_safe_accept": False,
        },
    }


def _pred(row_id, label, *, concept="ifrs-smes:Revenue", statement="Statement of Comprehensive Income"):
    return {
        "source_case_id": "case_001",
        "extracted_row_id": row_id,
        "extracted_label": label,
        "correct_concept_qname": concept,
        "fewshot_qwen_prediction": {
            "status": "suggested",
            "predicted_concept_qname": concept,
            "predicted_template_field_id": concept,
            "candidate_concepts": [
                {
                    "template_field_id": concept,
                    "concept_qname": concept,
                    "label": label,
                    "statement_type": statement,
                    "deterministic_method": "exact_alias_match",
                }
            ],
        },
    }


def _playbook(*, concept="ifrs-smes:Revenue", label="Revenue", statement="Statement of Comprehensive Income", family="revenue"):
    return {
        "concept_cards": [
            {
                "concept_qname": concept,
                "template_field_id": concept,
                "canonical_label": label,
                "common_extracted_labels": [label],
                "normalized_label_patterns": [label.lower()],
                "statement_families_observed": [statement],
                "common_sections": [statement],
                "semantic_families": [family],
                "quality": "strong",
                "support_count": 3,
            }
        ]
    }


class SupervisorEvaluationHotfix4Tests(unittest.TestCase):
    def test_mapper_omission_counts_rejected_and_no_prediction_with_gold(self):
        records = [
            _record("r1", "Revenue", review=_review("agree", risk="low", action="accept", safe=True)),
            _record(
                "r2",
                "Other receivables",
                status="rejected",
                selected="",
                correct="ssmt-mpers:OtherCurrentMiscellaneousNontradeReceivables",
                review=_review("agree", issues=["ambiguous_label"]),
                mapper_has_prediction=False,
                mapper_correct=False,
            ),
            _record(
                "r3",
                "Depreciation",
                status="no_prediction",
                selected="",
                correct="ssmt-mpers:AdjustmentsForDepreciationExpense",
                review=_review("needs_human_review"),
                mapper_has_prediction=False,
                mapper_correct=False,
            ),
            _record(
                "r4",
                "DIRECTORS REPORT",
                status="rejected",
                selected="",
                correct="",
                row_type="section_header",
                review=_review("agree", risk="low", action="accept", safe=False),
                mapper_has_prediction=False,
                mapper_correct=False,
                reason="section header non fact",
            ),
        ]

        report = build_hotfix_reports(
            review_report={"review_records": records},
            predictions={"strict_scoring_rows": []},
            playbook={"concept_cards": []},
        )["omission"]
        metrics = report["metrics"]

        self.assertEqual(metrics["mapper_omission_count"], 2)
        self.assertEqual(metrics["mapper_rejected_but_gold_exists"], 1)
        self.assertEqual(metrics["mapper_no_prediction_but_gold_exists"], 1)
        self.assertEqual(metrics["supervisor_agreed_with_omission_count"], 1)
        self.assertEqual(metrics["supervisor_caught_omission_count"], 1)
        self.assertEqual(metrics["false_agree_on_rejection_count"], 1)
        self.assertEqual(metrics["mapper_correctly_rejected_non_fact"], 1)

    def test_blocked_correct_mapping_metrics_include_reason_family_statement_and_alias(self):
        record = _record("r1", "Revenue", review=_review(issues=["broad_substitute"]))
        reports = build_hotfix_reports(
            review_report={"review_records": [record]},
            predictions={"strict_scoring_rows": [_pred("r1", "Revenue")]},
            playbook=_playbook(label="Revenue"),
        )

        metrics = reports["overconservative"]["metrics"]

        self.assertEqual(metrics["blocked_correct_mapping_count"], 1)
        self.assertEqual(metrics["blocked_correct_by_reason"]["broad_substitute"], 1)
        self.assertEqual(metrics["blocked_correct_by_concept_family"]["revenue"], 1)
        self.assertEqual(metrics["blocked_correct_by_statement_type"]["Statement of Comprehensive Income"], 1)
        self.assertEqual(metrics["blocked_correct_with_exact_alias_match"], 1)
        self.assertEqual(metrics["blocked_correct_with_strong_concept_card"], 1)

    def test_broad_substitute_over_trigger_and_true_risk_classification(self):
        over_triggered = _record("r1", "Revenue", review=_review(issues=["broad_substitute"]))
        true_risk = _record(
            "r2",
            "Revenue",
            selected="ifrs-smes:OtherIncome",
            correct="ifrs-smes:Revenue",
            review=_review(issues=["broad_substitute"]),
            mapper_correct=False,
            mapper_wrong=True,
        )
        prediction_index = {"r1": _pred("r1", "Revenue"), "r2": _pred("r2", "Other income", concept="ifrs-smes:OtherIncome")}
        card_index = {
            "ifrs-smes:Revenue": _playbook(label="Revenue")["concept_cards"][0],
            "ifrs-smes:OtherIncome": _playbook(concept="ifrs-smes:OtherIncome", label="Other income")["concept_cards"][0],
        }

        self.assertEqual(
            classify_broad_substitute(over_triggered, prediction_index=prediction_index, card_index=card_index)[
                "classification"
            ],
            "over_triggered_broad_substitute",
        )
        self.assertEqual(
            classify_broad_substitute(true_risk, prediction_index=prediction_index, card_index=card_index)[
                "classification"
            ],
            "true_broad_substitute_risk",
        )

    def test_relaxation_candidate_requires_alias_card_statement_match_and_no_hard_blockers(self):
        base = _record("r1", "Revenue", review=_review(issues=["broad_substitute"]))
        prediction_index = {"r1": _pred("r1", "Revenue")}
        card_index = {"ifrs-smes:Revenue": _playbook(label="Revenue")["concept_cards"][0]}

        self.assertIsNotNone(relaxation_candidate(base, prediction_index=prediction_index, card_index=card_index))

        for issue in ["candidate_not_supported", "ambiguous_label", "statement_family_mismatch"]:
            blocked = _record("r1", "Revenue", review=_review(issues=["broad_substitute", issue]))
            self.assertIsNone(relaxation_candidate(blocked, prediction_index=prediction_index, card_index=card_index))

        wrong_statement_card = {
            "ifrs-smes:Revenue": _playbook(label="Revenue", statement="Statement of Financial Position")["concept_cards"][0]
        }
        wrong_statement_prediction = {
            "r1": _pred("r1", "Revenue", statement="Statement of Financial Position")
        }
        self.assertIsNone(
            relaxation_candidate(base, prediction_index=wrong_statement_prediction, card_index=wrong_statement_card)
        )

    def test_generated_reports_are_valid_json(self):
        review = {"run_metadata": {"feature": "17D-B", "mode": "live"}, "review_records": [_record("r1", "Revenue")]}
        predictions = {"strict_scoring_rows": [_pred("r1", "Revenue")]}
        playbook = _playbook(label="Revenue")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review_path = root / "review.json"
            predictions_path = root / "predictions.json"
            playbook_path = root / "playbook.json"
            review_path.write_text(json.dumps(review), encoding="utf-8")
            predictions_path.write_text(json.dumps(predictions), encoding="utf-8")
            playbook_path.write_text(json.dumps(playbook), encoding="utf-8")

            paths = write_hotfix_reports(
                reports_dir=root,
                review_report_path=review_path,
                predictions_report_path=predictions_path,
                playbook_report_path=playbook_path,
            )

            for key, path in paths.items():
                if key.endswith("_json"):
                    self.assertIsInstance(json.loads(path.read_text(encoding="utf-8")), dict)

    def test_mapper_outcome_names_wrong_correct_and_no_gold_cases(self):
        self.assertEqual(classify_mapper_outcome(_record("r1", "Revenue")), "mapper_selected_correct_concept")
        self.assertEqual(
            classify_mapper_outcome(
                _record("r2", "Revenue", selected="ifrs-smes:OtherIncome", mapper_correct=False, mapper_wrong=True)
            ),
            "mapper_selected_wrong_concept",
        )
        self.assertEqual(
            classify_mapper_outcome(
                _record(
                    "r3",
                    "DIRECTORS REPORT",
                    selected="",
                    correct="",
                    status="rejected",
                    row_type="section_header",
                    mapper_has_prediction=False,
                    mapper_correct=False,
                    reason="section header non fact",
                )
            ),
            "mapper_correctly_rejected_non_fact",
        )


class SupervisorEvaluationHotfix5Tests(unittest.TestCase):
    def test_total_non_current_assets_to_noncurrent_assets_is_not_true_broad_risk(self):
        record = _record(
            "r1",
            "Total non-current assets",
            selected="ifrs-smes:NoncurrentAssets",
            correct="ifrs-smes:NoncurrentAssets",
            statement="Statement of Financial Position",
            row_type="subtotal_or_total",
            review=_review(issues=["broad_substitute"]),
        )
        prediction_index = {
            "r1": _pred(
                "r1",
                "Non-current assets",
                concept="ifrs-smes:NoncurrentAssets",
                statement="Statement of Financial Position",
            )
        }
        card_index = {
            "ifrs-smes:NoncurrentAssets": _playbook(
                concept="ifrs-smes:NoncurrentAssets",
                label="Non-current assets",
                statement="Statement of Financial Position",
                family="asset",
            )["concept_cards"][0]
        }

        result = classify_broad_substitute_calibrated(record, prediction_index=prediction_index, card_index=card_index)

        self.assertIn(
            result["calibrated_classification"],
            {"acceptable_total_or_subtotal_line", "same_family_total_label", "exact_total_concept_match"},
        )

    def test_specific_label_to_broad_category_remains_true_broad_risk(self):
        record = _record(
            "r1",
            "Other receivables",
            selected="ifrs-smes:CurrentAssets",
            correct="ssmt-mpers:OtherCurrentMiscellaneousNontradeReceivables",
            statement="Statement of Financial Position",
            review=_review(issues=["broad_substitute"]),
            mapper_correct=False,
            mapper_wrong=True,
        )
        prediction_index = {
            "r1": _pred(
                "r1",
                "Current assets",
                concept="ifrs-smes:CurrentAssets",
                statement="Statement of Financial Position",
            )
        }
        card_index = {
            "ifrs-smes:CurrentAssets": _playbook(
                concept="ifrs-smes:CurrentAssets",
                label="Current assets",
                statement="Statement of Financial Position",
                family="asset",
            )["concept_cards"][0]
        }

        result = classify_broad_substitute_calibrated(record, prediction_index=prediction_index, card_index=card_index)

        self.assertEqual(result["calibrated_classification"], "true_broad_substitute_risk")

    def test_omission_calibration_counts_agreed_and_caught_omissions(self):
        agreed = _record(
            "r1",
            "Other receivables",
            status="rejected",
            selected="",
            correct="ssmt-mpers:OtherCurrentMiscellaneousNontradeReceivables",
            review=_review("agree", issues=["ambiguous_label"]),
            mapper_has_prediction=False,
            mapper_correct=False,
        )
        caught = _record(
            "r2",
            "Depreciation",
            status="rejected",
            selected="",
            correct="ssmt-mpers:AdjustmentsForDepreciationExpense",
            review=_review("needs_human_review"),
            mapper_has_prediction=False,
            mapper_correct=False,
        )
        prediction_index = {
            "r1": _pred("r1", "Other receivables", concept="ssmt-mpers:OtherCurrentMiscellaneousNontradeReceivables"),
            "r2": _pred("r2", "Depreciation", concept="ssmt-mpers:AdjustmentsForDepreciationExpense"),
        }

        agreed_result = classify_omission_calibrated(agreed, prediction_index=prediction_index)
        caught_result = classify_omission_calibrated(caught, prediction_index=prediction_index)

        self.assertTrue(agreed_result["is_mapper_omission"])
        self.assertTrue(agreed_result["supervisor_agreed_with_omission"])
        self.assertTrue(caught_result["is_mapper_omission"])
        self.assertTrue(caught_result["supervisor_caught_omission"])

    def test_correct_non_fact_rejection_is_not_omission_in_calibration(self):
        record = _record(
            "r1",
            "DIRECTORS REPORT",
            status="rejected",
            selected="",
            correct="",
            row_type="section_header",
            review=_review("agree", risk="low", action="accept", safe=False),
            mapper_has_prediction=False,
            mapper_correct=False,
            reason="section header non fact",
        )

        result = classify_omission_calibrated(record, prediction_index={})

        self.assertEqual(result["mapper_outcome"], "mapper_rejected_non_fact_correctly")
        self.assertFalse(result["is_mapper_omission"])

    def test_safe_accept_calibration_requires_correct_prediction_and_no_hard_issue(self):
        base = _record("r1", "Revenue", review=_review(issues=["broad_substitute"]))
        prediction_index = {"r1": _pred("r1", "Revenue")}
        card_index = {"ifrs-smes:Revenue": _playbook(label="Revenue")["concept_cards"][0]}

        result = classify_safe_accept_relaxation(base, prediction_index=prediction_index, card_index=card_index)
        self.assertIn("relaxation_candidate_exact_alias", result["relaxation_labels"])
        self.assertNotIn("not_relaxable_due_to_hard_issue", result["relaxation_labels"])

        for issue in ["ambiguous_label", "candidate_not_supported", "statement_family_mismatch"]:
            blocked = _record("r1", "Revenue", review=_review(issues=["broad_substitute", issue]))
            blocked_result = classify_safe_accept_relaxation(blocked, prediction_index=prediction_index, card_index=card_index)
            self.assertIn("not_relaxable_due_to_hard_issue", blocked_result["relaxation_labels"])

    def test_calibration_reports_are_valid_json(self):
        review = {
            "run_metadata": {"feature": "17D-B", "mode": "live"},
            "review_records": [_record("r1", "Revenue", review=_review(issues=["broad_substitute"]))],
        }
        predictions = {"strict_scoring_rows": [_pred("r1", "Revenue")]}
        playbook = _playbook(label="Revenue")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review_path = root / "review.json"
            predictions_path = root / "predictions.json"
            playbook_path = root / "playbook.json"
            review_path.write_text(json.dumps(review), encoding="utf-8")
            predictions_path.write_text(json.dumps(predictions), encoding="utf-8")
            playbook_path.write_text(json.dumps(playbook), encoding="utf-8")

            paths = write_calibration_reports(
                reports_dir=root,
                review_report_path=review_path,
                predictions_report_path=predictions_path,
                playbook_report_path=playbook_path,
            )

            for key, path in paths.items():
                if key.endswith("_json"):
                    self.assertIsInstance(json.loads(path.read_text(encoding="utf-8")), dict)

    def test_calibration_report_metrics_include_required_categories(self):
        records = [
            _record("r1", "Revenue", review=_review(issues=["broad_substitute"])),
            _record(
                "r2",
                "Other receivables",
                status="rejected",
                selected="",
                correct="ssmt-mpers:OtherCurrentMiscellaneousNontradeReceivables",
                review=_review("agree", issues=["ambiguous_label"]),
                mapper_has_prediction=False,
                mapper_correct=False,
            ),
        ]

        reports = build_calibration_reports(
            review_report={"run_metadata": {"feature": "17D-B", "mode": "live"}, "review_records": records},
            predictions={"strict_scoring_rows": [_pred("r1", "Revenue"), _pred("r2", "Other receivables", concept="ssmt-mpers:OtherCurrentMiscellaneousNontradeReceivables")]},
            playbook=_playbook(label="Revenue"),
        )

        self.assertIn("calibrated_classification_counts", reports["broad"]["metrics"])
        self.assertEqual(reports["omission"]["metrics"]["mapper_omission_count"], 1)
        self.assertIn("relaxation_label_counts", reports["safe_accept"]["metrics"])

    def test_supervisor_prompt_includes_hotfix_5_calibration_guidance(self):
        payload = {
            "row": {"label": "Total assets", "statement_type": "Statement of Financial Position", "row_type": "subtotal_or_total"},
            "mapper_suggestion": {"selected_template_field_id": "ifrs-smes:Assets", "selected_concept_qname": "ifrs-smes:Assets"},
            "candidate_concepts": [{"template_field_id": "ifrs-smes:Assets", "concept_qname": "ifrs-smes:Assets", "label": "Assets"}],
            "retrieved_concept_cards": [],
            "retrieved_fewshot_examples": [],
            "do_not_confuse_notes": [],
        }

        prompt = build_supervisor_prompt(payload)

        self.assertIn("Do not flag broad_substitute for ordinary total/subtotal labels", prompt)
        self.assertIn("Mapper omission is a risk", prompt)
        self.assertIn("safe_to_accept must remain false when hard risk issues exist", prompt)


class SupervisorEvaluationHotfix6Tests(unittest.TestCase):
    def _low_confidence_review(self, *, issues=None):
        review = _review(issues=issues or [])
        review["normalization_diagnostics"]["normalization_reasons"].append("mapper_confidence_below_safe_threshold")
        return review

    def test_low_mapper_confidence_alone_is_relaxable_with_exact_alias_strong_card_and_statement_match(self):
        record = _record("r1", "Revenue", review=self._low_confidence_review())
        prediction_index = {"r1": _pred("r1", "Revenue")}
        card_index = {"ifrs-smes:Revenue": _playbook(label="Revenue")["concept_cards"][0]}

        result = classify_safe_accept_threshold(record, prediction_index=prediction_index, card_index=card_index)

        self.assertTrue(result["calibrated_safe_to_accept"])
        self.assertIn("blocked_by_low_mapper_confidence_only", result["relaxation_labels"])
        self.assertIn("relaxable_exact_alias_strong_evidence", result["relaxation_labels"])

    def test_hard_issues_block_threshold_relaxation(self):
        prediction_index = {"r1": _pred("r1", "Revenue")}
        card_index = {"ifrs-smes:Revenue": _playbook(label="Revenue")["concept_cards"][0]}

        for issue in ["ambiguous_label", "candidate_not_supported", "statement_family_mismatch"]:
            record = _record("r1", "Revenue", review=self._low_confidence_review(issues=[issue]))
            result = classify_safe_accept_threshold(record, prediction_index=prediction_index, card_index=card_index)
            self.assertFalse(result["calibrated_safe_to_accept"])
            self.assertEqual(result["classification"], "blocked_by_hard_issue")

    def test_missing_concept_card_blocks_threshold_relaxation(self):
        record = _record("r1", "Revenue", review=self._low_confidence_review())
        prediction_index = {"r1": _pred("r1", "Revenue")}

        result = classify_safe_accept_threshold(record, prediction_index=prediction_index, card_index={})

        self.assertFalse(result["calibrated_safe_to_accept"])
        self.assertEqual(result["classification"], "blocked_by_missing_evidence")

    def test_mapper_omission_and_non_fact_rows_are_not_relaxable(self):
        omitted = _record(
            "r1",
            "Revenue",
            selected="",
            status="rejected",
            mapper_has_prediction=False,
            mapper_correct=False,
            review=self._low_confidence_review(),
        )
        non_fact = _record(
            "r2",
            "DIRECTORS REPORT",
            selected="",
            correct="",
            status="rejected",
            row_type="section_header",
            mapper_has_prediction=False,
            mapper_correct=False,
            reason="section header non fact",
            review=self._low_confidence_review(),
        )
        prediction_index = {
            "r1": _pred("r1", "Revenue"),
            "r2": _pred("r2", "Directors report"),
        }

        omitted_result = classify_safe_accept_threshold(omitted, prediction_index=prediction_index, card_index={})
        non_fact_result = classify_safe_accept_threshold(non_fact, prediction_index=prediction_index, card_index={})

        self.assertFalse(omitted_result["calibrated_safe_to_accept"])
        self.assertIn("mapper_omission_not_relaxable", omitted_result["calibration_guardrails_failed"])
        self.assertFalse(non_fact_result["calibrated_safe_to_accept"])
        self.assertIn("non_fact_or_discussion_header_row", non_fact_result["calibration_guardrails_failed"])

    def test_cash_flow_same_family_exact_alias_mapping_is_relaxable(self):
        concept = "ifrs-smes:CashFlowsFromUsedInOperatingActivities"
        record = _record(
            "r1",
            "Cash from operating activities",
            selected=concept,
            correct=concept,
            statement="Statement of Cash Flows",
            review=self._low_confidence_review(),
        )
        prediction_index = {
            "r1": _pred("r1", "Cash from operating activities", concept=concept, statement="Statement of Cash Flows")
        }
        card_index = {
            concept: _playbook(
                concept=concept,
                label="Cash from operating activities",
                statement="Statement of Cash Flows",
                family="cash",
            )["concept_cards"][0]
        }

        result = classify_safe_accept_threshold(record, prediction_index=prediction_index, card_index=card_index)

        self.assertTrue(result["calibrated_safe_to_accept"])
        self.assertIn("relaxable_cash_flow_same_family", result["relaxation_labels"])

    def test_calibrated_safe_accept_never_becomes_true_for_wrong_mapper_prediction(self):
        record = _record(
            "r1",
            "Revenue",
            selected="ifrs-smes:OtherIncome",
            correct="ifrs-smes:Revenue",
            review=self._low_confidence_review(),
            mapper_correct=False,
            mapper_wrong=True,
        )
        prediction_index = {"r1": _pred("r1", "Other income", concept="ifrs-smes:OtherIncome")}
        card_index = {
            "ifrs-smes:OtherIncome": _playbook(
                concept="ifrs-smes:OtherIncome",
                label="Other income",
            )["concept_cards"][0]
        }

        result = classify_safe_accept_threshold(record, prediction_index=prediction_index, card_index=card_index)

        self.assertFalse(result["calibrated_safe_to_accept"])

    def test_calibrated_false_safe_accept_count_computes_from_simulation(self):
        wrong_safe = _record(
            "r1",
            "Revenue",
            selected="ifrs-smes:OtherIncome",
            correct="ifrs-smes:Revenue",
            review=_review("agree", risk="low", action="accept", safe=True),
            mapper_correct=False,
            mapper_wrong=True,
        )

        reports = build_threshold_reports(
            review_report={"run_metadata": {"feature": "17D-B", "mode": "live"}, "review_records": [wrong_safe]},
            predictions={"strict_scoring_rows": [_pred("r1", "Other income", concept="ifrs-smes:OtherIncome")]},
            playbook=_playbook(concept="ifrs-smes:OtherIncome", label="Other income"),
        )

        self.assertEqual(reports["threshold"]["metrics"]["calibrated_false_safe_accept_count"], 1)

    def test_hotfix_6_reports_are_valid_json(self):
        review = {"run_metadata": {"feature": "17D-B", "mode": "live"}, "review_records": [_record("r1", "Revenue", review=self._low_confidence_review())]}
        predictions = {"strict_scoring_rows": [_pred("r1", "Revenue")]}
        playbook = _playbook(label="Revenue")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review_path = root / "review.json"
            predictions_path = root / "predictions.json"
            playbook_path = root / "playbook.json"
            review_path.write_text(json.dumps(review), encoding="utf-8")
            predictions_path.write_text(json.dumps(predictions), encoding="utf-8")
            playbook_path.write_text(json.dumps(playbook), encoding="utf-8")

            paths = write_threshold_reports(
                reports_dir=root,
                review_report_path=review_path,
                predictions_report_path=predictions_path,
                playbook_report_path=playbook_path,
            )

            for key, path in paths.items():
                if key.endswith("_json"):
                    self.assertIsInstance(json.loads(path.read_text(encoding="utf-8")), dict)


if __name__ == "__main__":
    unittest.main()
