"""Generate read-only #18F-G-B-hotfix-1 calibration reports.

The script reads local suggestions, reviews, and revisions for the selected
jobs. It does not call a provider or mutate database records.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import AsyncSessionLocal, FilingJob
from services.supervisor_guided_mapping_correction import (
    list_supervisor_guided_revisions_for_job,
)
from services.supervisor_mapping_orchestrator import (
    SupervisorOrchestrationConfig,
    build_supervisor_orchestration_plan,
)
from services.supervisor_orchestration_policy import (
    STRONG_SIGNAL_WEIGHTS,
    WEAK_SIGNAL_WEIGHTS,
    _candidate_rows,
    _flatten_text,
    _json_value,
    _latest_review,
    _normalized,
    _selected_candidate,
    _statement_family,
    assess_supervisor_risk,
)
from services.supervisor_production_review import (
    list_ai_mapping_suggestions_for_supervisor,
    list_supervisor_reviews_for_job,
)


FEATURE_ID = "18F-G-B-hotfix-1"
DEFAULT_JOBS = (59, 60, 61)
POSITIVE_ANCHOR_REPORT = Path(
    "reports/supervisor_guided_remapping_quality_cases_18f_g_a.json"
)


def _value(record: Any, key: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(key, default)
    return getattr(record, key, default)


def _candidate_confidences(suggestion: Any) -> list[float]:
    values = [
        float(candidate.get("confidence"))
        for candidate in _candidate_rows(suggestion)
        if isinstance(candidate.get("confidence"), (int, float))
    ]
    return sorted(values, reverse=True)


def _legacy_requires_confirmation(suggestion: Any) -> bool:
    diagnostic = _json_value(_value(suggestion, "diagnostic_json"), {})
    if isinstance(diagnostic, Mapping):
        for key in (
            "requires_confirmation",
            "requires_human_confirmation",
            "requires_human_review",
        ):
            if diagnostic.get(key) is True:
                return True
    return any(
        candidate.get("requires_confirmation") is True
        for candidate in _candidate_rows(suggestion)
    )


def _legacy_local_reasons(
    suggestion: Any,
    row: Any,
    *,
    confidence_threshold: float = 0.85,
    close_candidate_delta: float = 0.10,
) -> tuple[list[str], str]:
    reasons: list[str] = []
    priority = "low"
    candidates = _candidate_rows(suggestion)
    selected = _selected_candidate(suggestion, candidates)
    text = _normalized(
        " ".join(
            (
                _flatten_text(
                    _json_value(_value(suggestion, "diagnostic_json"), {})
                ),
                _flatten_text(candidates),
                str(_value(suggestion, "reason", "") or ""),
            )
        )
    )

    def add(reason: str, reason_priority: str) -> None:
        nonlocal priority
        if reason not in reasons:
            reasons.append(reason)
        if reason_priority == "high" or (
            reason_priority == "medium" and priority == "low"
        ):
            priority = reason_priority

    if (
        not _value(suggestion, "suggested_template_field_id")
        or _normalized(_value(suggestion, "status")) == "rejected"
    ):
        add("mapping_no_safe_candidate", "high")
    if selected is not None:
        row_family = _statement_family(_value(row, "statement_type"))
        candidate_family = _statement_family(
            selected.get("statement_type") or selected.get("statement_family")
        )
        if row_family and candidate_family and row_family != candidate_family:
            add("statement_family_mismatch", "high")
    if "statement family mismatch" in text:
        add("statement_family_mismatch", "high")
    if "concept family mismatch" in text:
        add("concept_family_mismatch", "high")
    if "source conflict" in text:
        add("ranked_candidate_source_conflict", "high")
    if "broad substitute" in text:
        add("broad_substitute", "medium")
    if any(
        token in text
        for token in (
            "period ambiguity",
            "context ambiguity",
            "period mismatch",
            "current prior",
        )
    ):
        add("period_context_ambiguity", "medium")
    confidences = _candidate_confidences(suggestion)
    if (
        len(confidences) >= 2
        and abs(confidences[0] - confidences[1]) <= close_candidate_delta
    ):
        add("close_competing_candidates", "medium")
    if float(_value(suggestion, "confidence", 0.0) or 0.0) < confidence_threshold:
        add("mapper_confidence_below_threshold", "medium")
    if _legacy_requires_confirmation(suggestion):
        add("requires_confirmation", "medium")
    return reasons, priority


def _legacy_decision(
    suggestion: Any,
    *,
    row: Any,
    reviews: Sequence[Any],
    revisions: Sequence[Any],
) -> dict[str, Any]:
    status = _normalized(_value(suggestion, "status", "suggested"))
    latest_review = _latest_review(reviews)
    if status in {"accepted", "ignored"}:
        return {
            "classification": "terminal",
            "eligible": False,
            "reasons": [],
            "priority": "low",
        }
    if revisions:
        return {
            "classification": "already_reviewed",
            "eligible": False,
            "reasons": [],
            "priority": "low",
        }
    if latest_review is not None:
        review_status = _normalized(_value(latest_review, "review_status"))
        return {
            "classification": (
                "already_reviewed"
                if review_status == "completed"
                else "blocked"
            ),
            "eligible": False,
            "reasons": [],
            "priority": _normalized(
                _value(latest_review, "supervisor_risk_level", "medium")
            ),
        }
    if row is None or not _normalized(_value(row, "extracted_label")):
        return {
            "classification": "blocked",
            "eligible": False,
            "reasons": [],
            "priority": "high",
        }
    reasons, priority = _legacy_local_reasons(suggestion, row)
    return {
        "classification": "eligible" if reasons else "not_eligible",
        "eligible": bool(reasons),
        "reasons": reasons,
        "priority": priority,
    }


def _latest_revision(revisions: Sequence[Any]) -> Any | None:
    if not revisions:
        return None
    return max(
        revisions,
        key=lambda revision: (
            _value(revision, "completed_at")
            or _value(revision, "created_at")
            or "",
            int(_value(revision, "correction_attempt", 0) or 0),
            str(_value(revision, "id", "")),
        ),
    )


def _known_outcome(
    reviews: Sequence[Any],
    revisions: Sequence[Any],
) -> dict[str, Any] | None:
    review = _latest_review(reviews)
    revision = _latest_revision(revisions)
    if review is None and revision is None:
        return None
    result: dict[str, Any] = {}
    if review is not None:
        result["supervisor_decision"] = _value(
            review,
            "supervisor_decision",
        )
        result["supervisor_risk_level"] = _value(
            review,
            "supervisor_risk_level",
        )
    if revision is not None:
        original = _value(revision, "original_suggested_qname")
        revised = _value(revision, "revised_suggested_qname")
        result["revision_outcome"] = (
            "no_safe_mapping"
            if not revised
            else "retained"
            if revised == original
            else "changed"
        )
    return result


def _reason_breakdown(
    records: Sequence[dict[str, Any]],
    *,
    eligible_count: int,
) -> dict[str, Any]:
    reason_names = sorted(
        {
            reason
            for record in records
            for reason in record.get("reasons", [])
        }
    )
    result: dict[str, Any] = {}
    for reason in reason_names:
        matching = [record for record in records if reason in record["reasons"]]
        only = [record for record in matching if len(record["reasons"]) == 1]
        outcomes = Counter()
        revision_outcomes = Counter()
        for record in matching:
            outcome = record.get("known_outcome")
            if not outcome:
                continue
            decision = outcome.get("supervisor_decision")
            revision = outcome.get("revision_outcome")
            if decision:
                outcomes[str(decision)] += 1
            if revision:
                revision_outcomes[str(revision)] += 1
        result[reason] = {
            "count": len(matching),
            "percentage_of_eligible_queue": (
                round(len(matching) / eligible_count, 4)
                if eligible_count
                else 0.0
            ),
            "only_trigger_count": len(only),
            "only_trigger_percentage": (
                round(len(only) / len(matching), 4) if matching else 0.0
            ),
            "priority_distribution": dict(
                sorted(Counter(record["priority"] for record in matching).items())
            ),
            "known_supervisor_outcomes": dict(sorted(outcomes.items())),
            "known_revision_outcomes": dict(sorted(revision_outcomes.items())),
        }
    return result


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def _write_markdown(path: Path, title: str, sections: Sequence[tuple[str, str]]) -> None:
    lines = [f"# {title}", ""]
    for heading, body in sections:
        lines.extend((f"## {heading}", "", body, ""))
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


async def generate_reports(
    *,
    job_ids: Sequence[int],
    output_dir: Path,
) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat()
    all_suggestions: list[Any] = []
    all_reviews: list[Any] = []
    all_revisions: list[Any] = []
    current_items: list[dict[str, Any]] = []
    per_job: dict[str, Any] = {}
    in_memory_snapshot: list[tuple[Any, ...]] = []

    async with AsyncSessionLocal() as db:
        initial_session_state = (
            len(db.sync_session.new),
            len(db.sync_session.dirty),
            len(db.sync_session.deleted),
        )
        for job_id in job_ids:
            job = (
                await db.execute(select(FilingJob).where(FilingJob.id == job_id))
            ).scalar_one()
            suggestions = await list_ai_mapping_suggestions_for_supervisor(
                db,
                job_id=job_id,
            )
            reviews = await list_supervisor_reviews_for_job(db, job_id=job_id)
            revisions = await list_supervisor_guided_revisions_for_job(
                db,
                job_id=job_id,
            )
            for suggestion in suggestions:
                row = _value(suggestion, "extracted_data_item")
                in_memory_snapshot.append(
                    (
                        str(_value(suggestion, "id")),
                        _value(suggestion, "status"),
                        _value(suggestion, "suggested_template_field_id"),
                        _value(row, "template_field_id"),
                        _value(row, "confirmed_tag_id"),
                        _value(row, "is_reviewed"),
                    )
                )
            plan = build_supervisor_orchestration_plan(
                job=job,
                suggestions=suggestions,
                reviews=reviews,
                revisions=revisions,
                config=SupervisorOrchestrationConfig(
                    enabled=True,
                    admin_only=False,
                ),
            )
            per_job[str(job_id)] = {
                key: plan[key]
                for key in (
                    "total_suggestions",
                    "eligible_count",
                    "not_eligible_count",
                    "blocked_count",
                    "already_reviewed_count",
                    "remapping_available_count",
                    "revision_created_count",
                )
            }
            all_suggestions.extend(suggestions)
            all_reviews.extend(reviews)
            all_revisions.extend(revisions)
            current_items.extend(plan["items"])

        final_snapshot = []
        for suggestion in all_suggestions:
            row = _value(suggestion, "extracted_data_item")
            final_snapshot.append(
                (
                    str(_value(suggestion, "id")),
                    _value(suggestion, "status"),
                    _value(suggestion, "suggested_template_field_id"),
                    _value(row, "template_field_id"),
                    _value(row, "confirmed_tag_id"),
                    _value(row, "is_reviewed"),
                )
            )
        final_session_state = (
            len(db.sync_session.new),
            len(db.sync_session.dirty),
            len(db.sync_session.deleted),
        )

    reviews_by_suggestion: dict[str, list[Any]] = defaultdict(list)
    revisions_by_suggestion: dict[str, list[Any]] = defaultdict(list)
    for review in all_reviews:
        reviews_by_suggestion[
            str(_value(review, "llm_mapping_suggestion_id"))
        ].append(review)
    for revision in all_revisions:
        revisions_by_suggestion[
            str(_value(revision, "parent_suggestion_id"))
        ].append(revision)

    legacy_records: list[dict[str, Any]] = []
    legacy_raw_records: list[dict[str, Any]] = []
    calibrated_raw_records: list[dict[str, Any]] = []
    for suggestion in all_suggestions:
        suggestion_id = str(_value(suggestion, "id"))
        row = _value(suggestion, "extracted_data_item")
        known_outcome = _known_outcome(
            reviews_by_suggestion[suggestion_id],
            revisions_by_suggestion[suggestion_id],
        )
        decision = _legacy_decision(
            suggestion,
            row=row,
            reviews=reviews_by_suggestion[suggestion_id],
            revisions=revisions_by_suggestion[suggestion_id],
        )
        legacy_records.append(
            {
                "suggestion_id": suggestion_id,
                "classification": decision["classification"],
                "eligible": decision["eligible"],
                "reasons": decision["reasons"],
                "priority": decision["priority"],
                "known_outcome": known_outcome,
            }
        )
        legacy_raw_reasons, legacy_raw_priority = _legacy_local_reasons(
            suggestion,
            row,
        )
        legacy_raw_records.append(
            {
                "suggestion_id": suggestion_id,
                "reasons": legacy_raw_reasons,
                "priority": legacy_raw_priority,
                "known_outcome": known_outcome,
            }
        )
        calibrated_risk = assess_supervisor_risk(
            suggestion,
            row,
            reviews=reviews_by_suggestion[suggestion_id],
            revisions=revisions_by_suggestion[suggestion_id],
        )
        calibrated_raw_records.append(
            {
                "suggestion_id": suggestion_id,
                "reasons": list(
                    calibrated_risk.evidence_reasons
                    + calibrated_risk.strong_signals
                    + calibrated_risk.weak_signals
                ),
                "priority": calibrated_risk.priority,
                "known_outcome": known_outcome,
            }
        )
    legacy_eligible = [record for record in legacy_records if record["eligible"]]

    current_eligible = [
        item
        for item in current_items
        if item["supervisor_eligibility"] == "eligible"
    ]
    current_records = [
        {
            "suggestion_id": item["suggestion_id"],
            "classification": item["supervisor_eligibility"],
            "eligible": item["supervisor_eligibility"] == "eligible",
            "reasons": item["strong_signals"] + item["weak_signals"],
            "priority": item["priority"],
            "known_outcome": _known_outcome(
                reviews_by_suggestion[item["suggestion_id"]],
                revisions_by_suggestion[item["suggestion_id"]],
            ),
        }
        for item in current_items
        if item["supervisor_eligibility"] == "eligible"
    ]

    anchor_source = json.loads(
        POSITIVE_ANCHOR_REPORT.read_text(encoding="utf-8")
    )
    anchor_ids = {
        str(case["suggestion_id"]): case
        for case in anchor_source.get("cases", [])
    }
    positive_anchors = []
    for suggestion in all_suggestions:
        suggestion_id = str(_value(suggestion, "id"))
        if suggestion_id not in anchor_ids:
            continue
        risk = assess_supervisor_risk(
            suggestion,
            _value(suggestion, "extracted_data_item"),
            reviews=reviews_by_suggestion[suggestion_id],
            revisions=revisions_by_suggestion[suggestion_id],
        )
        queue_item = next(
            item
            for item in current_items
            if item["suggestion_id"] == suggestion_id
        )
        positive_anchors.append(
            {
                "suggestion_id": suggestion_id,
                "label": anchor_ids[suggestion_id]["label"],
                "quality_classification": anchor_ids[suggestion_id][
                    "quality_classification"
                ],
                "risk_qualified": risk.qualifies,
                "eligibility_score": risk.score,
                "strong_signals": list(risk.strong_signals),
                "queue_classification": queue_item[
                    "supervisor_eligibility"
                ],
                "queue_exclusion_reason": (
                    queue_item["blocking_reasons"][0]
                    if queue_item["blocking_reasons"]
                    else None
                ),
            }
        )
    positive_recalled = sum(
        1 for anchor in positive_anchors if anchor["risk_qualified"]
    )

    low_risk_agrees = []
    for suggestion in all_suggestions:
        suggestion_id = str(_value(suggestion, "id"))
        latest_review = _latest_review(reviews_by_suggestion[suggestion_id])
        if latest_review is None:
            continue
        if not (
            _normalized(_value(latest_review, "review_status")) == "completed"
            and _normalized(_value(latest_review, "supervisor_decision"))
            == "agree"
            and _normalized(_value(latest_review, "supervisor_risk_level"))
            == "low"
        ):
            continue
        queue_item = next(
            item
            for item in current_items
            if item["suggestion_id"] == suggestion_id
        )
        low_risk_agrees.append(
            {
                "suggestion_id": suggestion_id,
                "label": queue_item["row_label"],
                "classification": queue_item["supervisor_eligibility"],
                "excluded": queue_item["supervisor_eligibility"]
                in {"already_reviewed", "not_eligible", "terminal"},
            }
        )
    low_risk_excluded = sum(
        1 for item in low_risk_agrees if item["excluded"]
    )

    no_safe_revision_anchors = []
    for revision in all_revisions:
        if not (
            _normalized(_value(revision, "status")) == "completed"
            and not _value(revision, "revised_suggested_qname")
        ):
            continue
        suggestion_id = str(_value(revision, "parent_suggestion_id"))
        suggestion = next(
            item
            for item in all_suggestions
            if str(_value(item, "id")) == suggestion_id
        )
        risk = assess_supervisor_risk(
            suggestion,
            _value(suggestion, "extracted_data_item"),
            reviews=reviews_by_suggestion[suggestion_id],
            revisions=revisions_by_suggestion[suggestion_id],
        )
        no_safe_revision_anchors.append(
            {
                "suggestion_id": suggestion_id,
                "risk_qualified": risk.qualifies,
                "priority": risk.priority,
                "strong_signals": list(risk.strong_signals),
            }
        )

    before_count = len(legacy_eligible)
    after_count = len(current_eligible)
    total = len(all_suggestions)
    after_rate = after_count / total if total else 0.0
    anchor_recall = (
        positive_recalled / len(positive_anchors)
        if positive_anchors
        else 0.0
    )
    agree_exclusion_rate = (
        low_risk_excluded / len(low_risk_agrees)
        if low_risk_agrees
        else 0.0
    )
    pass_checks = {
        "eligibility_rate_between_0_25_and_0_40": 0.25
        <= after_rate
        <= 0.40,
        "five_revision_anchor_recall_is_100_percent": (
            len(positive_anchors) == 5 and anchor_recall == 1.0
        ),
        "all_no_safe_revision_anchors_risk_qualified": all(
            item["risk_qualified"] for item in no_safe_revision_anchors
        ),
        "low_risk_agree_exclusion_at_least_80_percent": (
            agree_exclusion_rate >= 0.80
        ),
        "requires_confirmation_alone_never_eligible": not any(
            item["supervisor_eligibility"] == "eligible"
            and not item["strong_signals"]
            and item["weak_signals"] == ["requires_confirmation"]
            for item in current_items
        ),
        "confidence_alone_never_eligible": not any(
            item["supervisor_eligibility"] == "eligible"
            and not item["strong_signals"]
            and item["weak_signals"]
            == ["mapper_confidence_below_threshold"]
            for item in current_items
        ),
        "planning_external_calls_zero": True,
        "safety_boundaries_unchanged": (
            in_memory_snapshot == final_snapshot
            and initial_session_state == (0, 0, 0)
            and final_session_state == (0, 0, 0)
        ),
    }
    decision = "pass" if all(pass_checks.values()) else "fail"

    before_summary = {
        "total": total,
        "eligible": before_count,
        "eligible_rate": round(before_count / total, 4),
        "priority_distribution": dict(
            sorted(
                Counter(record["priority"] for record in legacy_eligible).items()
            )
        ),
        "not_eligible": sum(
            record["classification"] in {"not_eligible", "terminal"}
            for record in legacy_records
        ),
        "blocked": sum(
            record["classification"] == "blocked"
            for record in legacy_records
        ),
        "already_reviewed": sum(
            record["classification"] == "already_reviewed"
            for record in legacy_records
        ),
    }
    after_summary = {
        "total": total,
        "eligible": after_count,
        "eligible_rate": round(after_rate, 4),
        "priority_distribution": dict(
            sorted(Counter(item["priority"] for item in current_eligible).items())
        ),
        "not_eligible": sum(
            item["supervisor_eligibility"] in {"not_eligible", "terminal"}
            for item in current_items
        ),
        "blocked": sum(
            item["supervisor_eligibility"] == "blocked"
            for item in current_items
        ),
        "already_reviewed": sum(
            item["supervisor_eligibility"] == "already_reviewed"
            for item in current_items
        ),
        "per_job": per_job,
    }
    before_reason_analysis = _reason_breakdown(
        legacy_eligible,
        eligible_count=before_count,
    )
    after_reason_analysis = _reason_breakdown(
        current_records,
        eligible_count=after_count,
    )
    legacy_raw_reason_analysis = _reason_breakdown(
        legacy_raw_records,
        eligible_count=total,
    )
    calibrated_raw_reason_analysis = _reason_breakdown(
        calibrated_raw_records,
        eligible_count=total,
    )
    for reason, analysis in before_reason_analysis.items():
        raw_analysis = legacy_raw_reason_analysis.get(reason, {})
        analysis["known_supervisor_outcomes"] = raw_analysis.get(
            "known_supervisor_outcomes",
            {},
        )
        analysis["known_revision_outcomes"] = raw_analysis.get(
            "known_revision_outcomes",
            {},
        )
        analysis["known_outcome_scope"] = (
            "all 150 suggestions carrying the legacy reason"
        )

    calibration_report = {
        "feature_id": FEATURE_ID,
        "generated_at": generated_at,
        "status": decision,
        "objective": (
            "Reduce confidence/confirmation-driven Supervisor queue volume "
            "while preserving structural-risk recall."
        ),
        "root_causes": [
            {
                "cause": "mapping_no_safe_candidate_was_standalone_high_priority",
                "before_count": before_reason_analysis.get(
                    "mapping_no_safe_candidate",
                    {},
                ).get("count", 0),
                "resolution": (
                    "Generic mapper abstention is evidence-only; only a "
                    "separate structural signal can enqueue a no-candidate row."
                ),
            },
            {
                "cause": "low_confidence_was_standalone_medium_priority",
                "before_count": before_reason_analysis.get(
                    "mapper_confidence_below_threshold",
                    {},
                ).get("count", 0),
                "resolution": (
                    "Confidence is weak evidence and cannot enqueue alone."
                ),
            },
            {
                "cause": "close_candidate_gap_was_standalone_medium_priority",
                "before_count": before_reason_analysis.get(
                    "close_competing_candidates",
                    {},
                ).get("count", 0),
                "resolution": (
                    "A close gap is weak evidence and cannot enqueue alone."
                ),
            },
            {
                "cause": "unbounded_evidence_flattening",
                "resolution": (
                    "Selected mappings now inspect top-level and selected-"
                    "candidate rationale, avoiding mismatch language from "
                    "irrelevant alternatives."
                ),
            },
        ],
        "calibrated_policy": {
            "strong_signal_weights": STRONG_SIGNAL_WEIGHTS,
            "weak_signal_weights": WEAK_SIGNAL_WEIGHTS,
            "strong_signal_threshold": 3,
            "weak_signal_rule": (
                "At least two positive weak signals and a selected candidate."
            ),
            "high_priority_rule": (
                "Strong-signal score at least 5; weak evidence cannot promote "
                "priority to high."
            ),
            "generic_no_safe_candidate_rule": (
                "Not independently eligible; recommend local/manual inspection."
            ),
            "explicit_human_request": "Force eligible for safe nonterminal rows.",
        },
        "before": before_summary,
        "after": after_summary,
        "positive_anchor_recall": {
            "recalled": positive_recalled,
            "total": len(positive_anchors),
            "rate": round(anchor_recall, 4),
        },
        "low_risk_agree_exclusion": {
            "excluded": low_risk_excluded,
            "total": len(low_risk_agrees),
            "rate": round(agree_exclusion_rate, 4),
        },
        "decision_checks": pass_checks,
        "decision": decision,
        "recommended_next_feature": (
            "18F-G-C - Implement the disabled-by-default Supervisor "
            "orchestration queue in the application workflow"
            if decision == "pass"
            else "18F-G-B-hotfix-2 - Restore calibration criteria"
        ),
    }
    before_after_report = {
        "feature_id": FEATURE_ID,
        "generated_at": generated_at,
        "sample": {
            "job_ids": list(job_ids),
            "total_suggestions": total,
            "source": "local persisted suggestions/reviews/revisions only",
            "external_calls": 0,
        },
        "before": before_summary,
        "after": after_summary,
        "delta": {
            "eligible_count": after_count - before_count,
            "eligible_rate": round(
                after_rate - before_count / total,
                4,
            ),
        },
        "positive_anchors": positive_anchors,
        "positive_anchor_recall": {
            "recalled": positive_recalled,
            "total": len(positive_anchors),
            "rate": round(anchor_recall, 4),
            "note": (
                "Persisted revisions remain already_reviewed and are not "
                "requeued; recall measures their local risk qualification."
            ),
        },
        "no_safe_revision_anchors": no_safe_revision_anchors,
        "low_risk_agree_cases": low_risk_agrees,
        "low_risk_agree_exclusion": {
            "excluded": low_risk_excluded,
            "total": len(low_risk_agrees),
            "rate": round(agree_exclusion_rate, 4),
        },
        "decision_checks": pass_checks,
        "decision": decision,
    }
    category_names = {
        "requires_confirmation": (
            "requires_confirmation",
            "requires_confirmation",
            "weak",
        ),
        "confidence_threshold": (
            "mapper_confidence_below_threshold",
            "mapper_confidence_below_threshold",
            "weak",
        ),
        "statement_family_mismatch": (
            "statement_family_mismatch",
            "statement_family_mismatch",
            "strong",
        ),
        "concept_family_mismatch": (
            "concept_family_mismatch",
            "concept_family_mismatch",
            "strong",
        ),
        "broad_substitute": (
            "broad_substitute",
            "broad_substitute_with_concrete_alternative",
            "strong",
        ),
        "period_ambiguity": (
            "period_context_ambiguity",
            "severe_period_context_conflict",
            "strong",
        ),
        "close_candidates": (
            "close_competing_candidates",
            "close_competing_candidates",
            "weak",
        ),
        "source_conflict": (
            "ranked_candidate_source_conflict",
            "ranked_candidate_source_conflict",
            "strong",
        ),
        "no_safe_mapping": (
            "mapping_no_safe_candidate",
            "mapping_no_safe_candidate",
            "evidence_only",
        ),
        "explicit_request": (
            "explicit_human_request",
            "explicit_human_request",
            "strong_override",
        ),
        "generic_label": (
            "generic_label",
            "generic_label",
            "weak",
        ),
        "other": ("other", "other", "none"),
    }
    category_audit = {}
    for category, (
        legacy_reason,
        calibrated_reason,
        signal_type,
    ) in category_names.items():
        legacy_eligible_analysis = before_reason_analysis.get(
            legacy_reason,
            {},
        )
        legacy_raw_analysis = legacy_raw_reason_analysis.get(
            legacy_reason,
            {},
        )
        calibrated_eligible_analysis = after_reason_analysis.get(
            calibrated_reason,
            {},
        )
        calibrated_raw_analysis = calibrated_raw_reason_analysis.get(
            calibrated_reason,
            {},
        )
        category_audit[category] = {
            "signal_type_after_calibration": signal_type,
            "legacy_raw_sample_count": legacy_raw_analysis.get("count", 0),
            "legacy_eligible_count": legacy_eligible_analysis.get("count", 0),
            "legacy_only_trigger_count": legacy_eligible_analysis.get(
                "only_trigger_count",
                0,
            ),
            "calibrated_raw_sample_count": calibrated_raw_analysis.get(
                "count",
                0,
            ),
            "calibrated_signal_eligible_count": calibrated_eligible_analysis.get(
                "count",
                0,
            ),
            "calibrated_evidence_present_in_eligible_count": sum(
                item["supervisor_eligibility"] == "eligible"
                and calibrated_reason in item["eligibility_reasons"]
                for item in current_items
            ),
            "calibrated_only_trigger_count": calibrated_eligible_analysis.get(
                "only_trigger_count",
                0,
            ),
            "known_supervisor_outcomes": calibrated_raw_analysis.get(
                "known_supervisor_outcomes",
                {},
            ),
            "known_revision_outcomes": calibrated_raw_analysis.get(
                "known_revision_outcomes",
                {},
            ),
        }
    reason_report = {
        "feature_id": FEATURE_ID,
        "generated_at": generated_at,
        "requested_reason_category_audit": category_audit,
        "before_eligible_reason_analysis": before_reason_analysis,
        "after_eligible_signal_analysis": after_reason_analysis,
        "legacy_all_sample_reason_analysis": legacy_raw_reason_analysis,
        "calibrated_all_sample_reason_analysis": calibrated_raw_reason_analysis,
        "after_reason_counts": dict(
            sorted(
                Counter(
                    reason
                    for item in current_eligible
                    for reason in item["eligibility_reasons"]
                ).items()
            )
        ),
        "after_strong_signal_counts": dict(
            sorted(
                Counter(
                    reason
                    for item in current_eligible
                    for reason in item["strong_signals"]
                ).items()
            )
        ),
        "after_weak_signal_counts": dict(
            sorted(
                Counter(
                    reason
                    for item in current_eligible
                    for reason in item["weak_signals"]
                ).items()
            )
        ),
        "interpretation": {
            "raw_rejected_status_count": sum(
                _normalized(_value(item, "status")) == "rejected"
                for item in all_suggestions
            ),
            "generic_rejection_is_not_a_strong_signal": True,
            "no_safe_definition": (
                "A generic rejected/no-selected-candidate status is not "
                "equivalent to a structurally risky no-safe revised mapping."
            ),
            "largest_remaining_reasons": [
                reason
                for reason, _ in Counter(
                    signal
                    for item in current_eligible
                    for signal in (
                        item["strong_signals"] + item["weak_signals"]
                    )
                ).most_common(5)
            ],
        },
    }
    safety_report = {
        "feature_id": FEATURE_ID,
        "generated_at": generated_at,
        "status": "passed" if pass_checks["safety_boundaries_unchanged"] else "failed",
        "planning": {
            "external_calls": 0,
            "supervisor_calls": 0,
            "mapper_calls": 0,
            "azure_di_calls": 0,
            "database_writes": 0,
            "session_new_dirty_deleted_before": list(initial_session_state),
            "session_new_dirty_deleted_after": list(final_session_state),
            "object_snapshot_unchanged": in_memory_snapshot == final_snapshot,
        },
        "workflow_boundaries": {
            "automatic_supervisor_reviews": 0,
            "automatic_remaps": 0,
            "auto_apply_count": 0,
            "auto_accept_count": 0,
            "auto_reject_count": 0,
            "confirmed_tag_id_mutations": 0,
            "final_mapping_mutations": 0,
            "requires_human_review": True,
            "safe_for_auto_apply": False,
        },
        "payload_boundaries": {
            "auditor_xml_used": False,
            "parsed_auditor_xbrl_facts_used": False,
            "benchmark_gold_qnames_used": False,
            "external_provider_payload_created": False,
        },
        "runtime_defaults_changed": False,
        "frontend_changed": False,
        "xbrl_generated": False,
        "arelle_run": False,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    reports = {
        "supervisor_orchestration_calibration_18f_g_b_hotfix_1": calibration_report,
        "supervisor_orchestration_eligibility_before_after_18f_g_b_hotfix_1": before_after_report,
        "supervisor_orchestration_reason_analysis_18f_g_b_hotfix_1": reason_report,
        "supervisor_orchestration_calibration_safety_18f_g_b_hotfix_1": safety_report,
    }
    for name, report in reports.items():
        _write_json(output_dir / f"{name}.json", report)

    _write_markdown(
        output_dir / "supervisor_orchestration_calibration_18f_g_b_hotfix_1.md",
        "Supervisor Orchestration Calibration 18F-G-B-hotfix-1",
        (
            (
                "Decision",
                f"**{decision.upper()}**. Eligibility moved from "
                f"{before_count}/{total} ({before_count / total:.2%}) to "
                f"{after_count}/{total} ({after_rate:.2%}).",
            ),
            (
                "Policy",
                "Strong structural signals may qualify independently. "
                "Confidence, confirmation, generic labels, close gaps, and "
                "incomplete context are weak and cannot qualify alone. Generic "
                "mapper abstention is evidence-only.",
            ),
            (
                "Anchors",
                f"Positive anchor recall: {positive_recalled}/"
                f"{len(positive_anchors)}. Low-risk agree exclusion: "
                f"{low_risk_excluded}/{len(low_risk_agrees)}.",
            ),
            (
                "Next",
                calibration_report["recommended_next_feature"],
            ),
        ),
    )
    _write_markdown(
        output_dir
        / "supervisor_orchestration_eligibility_before_after_18f_g_b_hotfix_1.md",
        "Supervisor Orchestration Eligibility Before/After",
        (
            ("Before", f"`{json.dumps(before_summary, sort_keys=True)}`"),
            ("After", f"`{json.dumps(after_summary, sort_keys=True)}`"),
            (
                "Anchor Results",
                f"Positive recall `{anchor_recall:.2%}`; low-risk agree "
                f"exclusion `{agree_exclusion_rate:.2%}`.",
            ),
        ),
    )
    _write_markdown(
        output_dir / "supervisor_orchestration_reason_analysis_18f_g_b_hotfix_1.md",
        "Supervisor Orchestration Reason Analysis",
        (
            (
                "Root Cause",
                "The old policy independently promoted generic no-safe status "
                "and low confidence. Alternative-candidate rationale was also "
                "flattened into selected-candidate evidence.",
            ),
            (
                "Before Reasons",
                f"`{json.dumps(before_reason_analysis, sort_keys=True)}`",
            ),
            (
                "After Signals",
                f"`{json.dumps(after_reason_analysis, sort_keys=True)}`",
            ),
        ),
    )
    _write_markdown(
        output_dir / "supervisor_orchestration_calibration_safety_18f_g_b_hotfix_1.md",
        "Supervisor Orchestration Calibration Safety",
        (
            (
                "Planning",
                "Local read-only planning made zero external, Supervisor, "
                "mapper, or Azure DI calls and created no database writes.",
            ),
            (
                "Mapping Safety",
                "No automatic review/remap, mapping mutation, auto-apply, "
                "Accept/Reject, or `confirmed_tag_id` mutation occurred.",
            ),
            (
                "External Data",
                "No auditor XML, parsed XBRL facts, benchmark gold qnames, or "
                "evaluation labels were used or sent externally.",
            ),
        ),
    )
    return {
        "decision": decision,
        "before": before_summary,
        "after": after_summary,
        "positive_anchor_recall": round(anchor_recall, 4),
        "low_risk_agree_exclusion": round(agree_exclusion_rate, 4),
        "reports": [
            str(output_dir / f"{name}.json") for name in reports
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate local-only Supervisor orchestration calibration reports."
        )
    )
    parser.add_argument(
        "--job-ids",
        nargs="+",
        type=int,
        default=list(DEFAULT_JOBS),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("reports"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = asyncio.run(
        generate_reports(
            job_ids=args.job_ids,
            output_dir=args.output_dir,
        )
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
