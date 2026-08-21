"""Generate #17D-B hotfix-4 Supervisor evaluation diagnostics.

This script is local/report-only. It consumes existing Supervisor review,
few-shot prediction, and concept-card reports. It does not call an external
LLM, mutate the database, change production jobs, generate XBRL, or run Arelle.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


DEFAULT_REVIEW_REPORT = PROJECT_ROOT / "reports" / "supervisor_live_review_17d_b.json"
DEFAULT_PREDICTIONS_REPORT = PROJECT_ROOT / "reports" / "golden_mbrs_fewshot_qwen_predictions_17b.json"
DEFAULT_PLAYBOOK_REPORT = PROJECT_ROOT / "reports" / "fs_mpers_concept_playbook_17d_pre.json"

HARD_RELAXATION_BLOCKERS = {
    "candidate_not_supported",
    "statement_family_mismatch",
    "ambiguous_label",
    "person_or_company_name",
    "note_number",
    "missing_concept_card",
    "no_supporting_evidence",
    "invalid_supervisor_response",
    "unrepaired_invalid_supervisor_response",
}
BLOCKED_REASON_TYPES = {
    "broad_substitute",
    "ambiguous_label",
    "weak_label_match",
    "missing_concept_card",
    "candidate_not_supported",
    "statement_family_mismatch",
    "no_supporting_evidence",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _resolve(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate


def _display(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())).strip()


def _tokens(value: Any) -> set[str]:
    return {token for token in _normalize(value).split() if token not in {"and", "of", "the", "at", "to", "for"}}


def _similarity(left: Any, right: Any) -> float:
    left_text = _normalize(left)
    right_text = _normalize(right)
    if not left_text or not right_text:
        return 0.0
    left_tokens = _tokens(left_text)
    right_tokens = _tokens(right_text)
    token_overlap = len(left_tokens & right_tokens) / len(left_tokens | right_tokens) if left_tokens and right_tokens else 0.0
    containment = 0.0
    if left_tokens and (left_tokens <= right_tokens or right_tokens <= left_tokens):
        containment = min(len(left_tokens), len(right_tokens)) / max(len(left_tokens), len(right_tokens))
    return round(max(SequenceMatcher(None, left_text, right_text).ratio(), token_overlap, containment), 4)


def _row_key(row: Mapping[str, Any]) -> str:
    return str(row.get("extracted_row_id") or f"{row.get('source_case_id')}:{row.get('label') or row.get('extracted_label')}")


def _issue_types(review: Mapping[str, Any]) -> set[str]:
    return {
        str((issue or {}).get("type") or "")
        for issue in (review.get("issues") or [])
        if isinstance(issue, Mapping) and (issue or {}).get("type")
    }


def _normalization_reasons(review: Mapping[str, Any]) -> set[str]:
    return set((review.get("normalization_diagnostics") or {}).get("normalization_reasons") or [])


def _selected_id(record: Mapping[str, Any]) -> str:
    score = record.get("local_scoring") or {}
    mapper = record.get("mapper_selection") or {}
    return str(
        score.get("mapper_selected_concept_qname")
        or score.get("mapper_selected_template_field_id")
        or mapper.get("selected_concept_qname")
        or mapper.get("selected_template_field_id")
        or ""
    ).strip()


def _correct_id(record: Mapping[str, Any]) -> str:
    score = record.get("local_scoring") or {}
    return str(score.get("correct_concept_qname") or score.get("correct_template_field_id") or "").strip()


def _prediction_rows(predictions: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = predictions.get("strict_scoring_rows") or predictions.get("rows") or []
    return {_row_key(row): row for row in rows if isinstance(row, Mapping)}


def _concept_cards(playbook: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    cards: dict[str, Mapping[str, Any]] = {}
    for card in playbook.get("concept_cards") or []:
        if not isinstance(card, Mapping):
            continue
        for key in ("concept_qname", "template_field_id"):
            value = str(card.get(key) or "").strip()
            if value:
                cards[value] = card
    return cards


def _candidate_for(record: Mapping[str, Any], prediction_index: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any]:
    prediction = prediction_index.get(_row_key(record.get("row") or {})) or {}
    mapper = prediction.get("fewshot_qwen_prediction") or prediction.get("qwen_prediction") or {}
    selected = _selected_id(record)
    for candidate in mapper.get("candidate_concepts") or []:
        if not isinstance(candidate, Mapping):
            continue
        ids = {str(candidate.get("template_field_id") or ""), str(candidate.get("concept_qname") or ""), str(candidate.get("qname") or "")}
        if selected and selected in ids:
            return candidate
    return {}


def _label(record: Mapping[str, Any]) -> str:
    row = record.get("row") or {}
    return str(row.get("label") or row.get("extracted_label") or "").strip()


def _statement_type(record: Mapping[str, Any]) -> str:
    row = record.get("row") or {}
    return str(row.get("statement_type") or "").strip()


def _concept_family(qname: str, card: Mapping[str, Any] | None = None) -> str:
    if card:
        families = card.get("semantic_families") or []
        if families:
            return str(families[0])
    local = qname.split(":", 1)[-1]
    words = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)", local)
    return "_".join(word.lower() for word in words[:2]) if words else "unknown"


def _statement_matches(record: Mapping[str, Any], card: Mapping[str, Any] | None, candidate: Mapping[str, Any] | None = None) -> bool:
    statement = _statement_type(record)
    if not statement:
        return False
    candidate_statement = str((candidate or {}).get("statement_type") or "")
    if candidate_statement and (statement == candidate_statement or statement in candidate_statement or candidate_statement in statement):
        return True
    if card:
        observed = [str(value) for value in (card.get("statement_families_observed") or []) + (card.get("common_sections") or [])]
        if any(statement == value or statement in value or value in statement for value in observed):
            return True
    return False


def _alias_evidence(record: Mapping[str, Any], card: Mapping[str, Any] | None, candidate: Mapping[str, Any] | None = None) -> dict[str, Any]:
    label = _label(record)
    labels: list[str] = []
    if candidate and candidate.get("label"):
        labels.append(str(candidate.get("label")))
    if card:
        labels.extend(str(value) for value in card.get("common_extracted_labels") or [])
        labels.extend(str(value) for value in card.get("normalized_label_patterns") or [])
        if card.get("canonical_label"):
            labels.append(str(card.get("canonical_label")))
    mapper_reason = str((record.get("mapper_selection") or {}).get("reason") or "").lower()
    best_label = ""
    best_score = 0.0
    for candidate_label in labels:
        score = _similarity(label, candidate_label)
        if score > best_score:
            best_label = candidate_label
            best_score = score
    exact_or_near = best_score >= 0.9 or "exact alias" in mapper_reason
    return {
        "best_alias_label": best_label or None,
        "best_alias_similarity": best_score,
        "exact_or_near_alias": exact_or_near,
        "mapper_reason_claims_exact_alias": "exact alias" in mapper_reason,
    }


def _strong_concept_card(card: Mapping[str, Any] | None) -> bool:
    if not card:
        return False
    return card.get("quality") == "strong" or int(card.get("support_count") or 0) >= 3


def _gold_exists(record: Mapping[str, Any]) -> bool:
    return bool(_correct_id(record))


def _is_non_fact_rejection(record: Mapping[str, Any]) -> bool:
    row = record.get("row") or {}
    label = _normalize(row.get("label") or row.get("extracted_label"))
    row_type = _normalize(row.get("row_type"))
    reason = _normalize((record.get("mapper_selection") or {}).get("reason"))
    return any(marker in " ".join([label, row_type, reason]) for marker in ["section header", "discussion", "textual annotation", "non fact"])


def classify_mapper_outcome(record: Mapping[str, Any]) -> str:
    score = record.get("local_scoring") or {}
    status = str((record.get("mapper_selection") or {}).get("status") or "").lower()
    if score.get("mapper_correct"):
        return "mapper_selected_correct_concept"
    if score.get("mapper_wrong"):
        return "mapper_selected_wrong_concept"
    if _gold_exists(record) and not score.get("mapper_has_prediction"):
        if status in {"no_prediction", "no_suggestion", "not_started", "rate_limited"}:
            return "mapper_no_prediction_but_gold_exists"
        return "mapper_rejected_but_gold_exists"
    if not _gold_exists(record) and not score.get("mapper_has_prediction") and _is_non_fact_rejection(record):
        return "mapper_correctly_rejected_non_fact"
    return "mapper_no_gold_available_or_not_evaluable"


def blocked_reasons(record: Mapping[str, Any]) -> list[str]:
    review = record.get("supervisor_review") or {}
    reasons = set(_issue_types(review) & BLOCKED_REASON_TYPES)
    normalization = _normalization_reasons(review)
    if "medium_or_high_risk_cannot_be_safe_accept" in normalization or review.get("risk_level") in {"medium", "high"}:
        reasons.add("medium_or_high_risk")
    if "recommended_action_not_accept_cannot_be_safe_accept" in normalization or review.get("recommended_action") != "accept":
        reasons.add("non_accept_action")
    if "mapper_confidence_below_safe_threshold" in normalization:
        reasons.add("low_mapper_confidence")
    return sorted(reasons or {"other"})


def classify_broad_substitute(
    record: Mapping[str, Any],
    *,
    prediction_index: Mapping[str, Mapping[str, Any]],
    card_index: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    selected = _selected_id(record)
    correct = _correct_id(record)
    card = card_index.get(selected)
    candidate = _candidate_for(record, prediction_index)
    alias = _alias_evidence(record, card, candidate)
    statement_match = _statement_matches(record, card, candidate)
    score = record.get("local_scoring") or {}
    issues = _issue_types(record.get("supervisor_review") or {})
    row_type = _normalize((record.get("row") or {}).get("row_type"))
    if score.get("mapper_wrong") or "candidate_not_supported" in issues or "statement_family_mismatch" in issues:
        classification = "true_broad_substitute_risk"
    elif score.get("mapper_correct") and "subtotal" in row_type and alias["exact_or_near_alias"] and statement_match:
        classification = "subtotal_or_total_line_acceptable_broad_concept"
    elif score.get("mapper_correct") and alias["exact_or_near_alias"] and statement_match and _strong_concept_card(card):
        classification = "over_triggered_broad_substitute"
    elif score.get("mapper_correct") and statement_match:
        classification = "likely_label_specific_but_same_family"
    else:
        classification = "cannot_determine"
    return {
        "classification": classification,
        "row": record.get("row") or {},
        "selected_concept_qname": selected or None,
        "correct_concept_qname": correct or None,
        "mapper_correct": bool(score.get("mapper_correct")),
        "mapper_wrong": bool(score.get("mapper_wrong")),
        "statement_family_matches": statement_match,
        "concept_card_available": bool(card),
        "strong_concept_card": _strong_concept_card(card),
        **alias,
        "issues": sorted(issues),
        "supervisor_reason": (record.get("supervisor_review") or {}).get("reason"),
    }


def _relaxation_blockers(
    record: Mapping[str, Any],
    *,
    prediction_index: Mapping[str, Mapping[str, Any]],
    card_index: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    selected = _selected_id(record)
    correct = _correct_id(record)
    card = card_index.get(selected)
    candidate = _candidate_for(record, prediction_index)
    alias = _alias_evidence(record, card, candidate)
    issues = _issue_types(record.get("supervisor_review") or {})
    blockers: list[str] = []
    if not (record.get("local_scoring") or {}).get("mapper_correct"):
        blockers.append("mapper_prediction_not_locally_correct")
    if not selected or selected != correct:
        blockers.append("selected_concept_does_not_equal_local_gold")
    if issues & HARD_RELAXATION_BLOCKERS:
        blockers.extend(sorted(issues & HARD_RELAXATION_BLOCKERS))
    remaining_issues = issues - {"broad_substitute"}
    if remaining_issues:
        blockers.append("non_broad_substitute_issue_present")
    if not alias["exact_or_near_alias"]:
        blockers.append("no_exact_or_near_alias_evidence")
    if not _statement_matches(record, card, candidate):
        blockers.append("statement_family_not_matched")
    if not card:
        blockers.append("missing_concept_card")
    if card and not _strong_concept_card(card):
        blockers.append("concept_card_not_strong")
    return sorted(set(blockers))


def relaxation_candidate(
    record: Mapping[str, Any],
    *,
    prediction_index: Mapping[str, Mapping[str, Any]],
    card_index: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any] | None:
    if not (record.get("local_scoring") or {}).get("correct_mapping_unnecessarily_blocked"):
        return None
    blockers = _relaxation_blockers(record, prediction_index=prediction_index, card_index=card_index)
    if blockers:
        return None
    selected = _selected_id(record)
    card = card_index.get(selected)
    candidate = _candidate_for(record, prediction_index)
    alias = _alias_evidence(record, card, candidate)
    return {
        "row": record.get("row") or {},
        "selected_concept_qname": selected,
        "correct_concept_qname": _correct_id(record),
        "reason_relaxable": "Mapper prediction is locally correct, has near/exact alias evidence, statement family matches, and only broad_substitute/generic medium-risk blocking remains.",
        "proposed_deterministic_guardrail": "Allow future safe_to_accept only when local candidate/card evidence proves exact alias, same statement family, selected concept equals local gold in evaluation, and no hard risk issues are present.",
        "alias_evidence": alias,
        "concept_family": _concept_family(selected, card),
        "supervisor_review": record.get("supervisor_review") or {},
    }


def _case_summary(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "row": record.get("row") or {},
        "mapper_selection": record.get("mapper_selection") or {},
        "supervisor_review": record.get("supervisor_review") or {},
        "local_scoring": record.get("local_scoring") or {},
    }


def build_hotfix_reports(
    *,
    review_report: Mapping[str, Any],
    predictions: Mapping[str, Any],
    playbook: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    records = [record for record in review_report.get("review_records") or [] if isinstance(record, Mapping)]
    prediction_index = _prediction_rows(predictions)
    card_index = _concept_cards(playbook)
    run_metadata = {
        "feature": "17D-B-hotfix-4",
        "generated_at": _utc_now(),
        "source_review_feature": (review_report.get("run_metadata") or {}).get("feature"),
        "source_review_mode": (review_report.get("run_metadata") or {}).get("mode"),
        "external_llm_called_by_this_script": False,
        "auditor_xml_sent_externally": False,
        "parsed_xml_facts_sent_externally": False,
        "target_gold_answers_sent_externally": False,
        "evaluation_labels_sent_externally": False,
        "database_mutated": False,
        "production_job_mutated": False,
        "confirmed_tag_id_automated": False,
        "xbrl_generated": False,
        "arelle_run": False,
        "production_integration_ready": False,
        "production_integration_recommendation": "defer_17d_c_until_omission_and_overconservative_findings_are_reviewed",
    }

    outcomes = Counter(classify_mapper_outcome(record) for record in records)
    omissions = [
        record
        for record in records
        if classify_mapper_outcome(record) in {"mapper_rejected_but_gold_exists", "mapper_no_prediction_but_gold_exists"}
    ]
    omission_examples = [_case_summary(record) for record in omissions[:10]]
    omission_report = {
        "run_metadata": run_metadata,
        "metrics": {
            "total_reviewed": len(records),
            "mapper_selected_correct_concept": outcomes["mapper_selected_correct_concept"],
            "mapper_selected_wrong_concept": outcomes["mapper_selected_wrong_concept"],
            "mapper_rejected_but_gold_exists": outcomes["mapper_rejected_but_gold_exists"],
            "mapper_no_prediction_but_gold_exists": outcomes["mapper_no_prediction_but_gold_exists"],
            "mapper_correctly_rejected_non_fact": outcomes["mapper_correctly_rejected_non_fact"],
            "mapper_no_gold_available_or_not_evaluable": outcomes["mapper_no_gold_available_or_not_evaluable"],
            "mapper_omission_count": len(omissions),
            "mapper_omission_rate": round(len(omissions) / len(records), 4) if records else 0.0,
            "supervisor_agreed_with_omission_count": sum(
                1 for record in omissions if (record.get("supervisor_review") or {}).get("review_decision") == "agree"
            ),
            "supervisor_caught_omission_count": sum(
                1 for record in omissions if (record.get("supervisor_review") or {}).get("review_decision") in {"disagree", "needs_human_review"}
            ),
            "false_agree_on_rejection_count": sum(
                1 for record in omissions if (record.get("supervisor_review") or {}).get("review_decision") == "agree"
            ),
            "rejected_rows_with_gold_answer_count": outcomes["mapper_rejected_but_gold_exists"],
            "no_prediction_rows_with_gold_answer_count": outcomes["mapper_no_prediction_but_gold_exists"],
        },
        "mapper_omission_cases": omission_examples,
        "top_mapper_omission_cases": omission_examples[:5],
        "recommendation": "Improve candidate retrieval and omission detection before production Supervisor integration; safe_to_accept should remain suggestion-only.",
    }

    blocked_correct = [
        record for record in records if (record.get("local_scoring") or {}).get("correct_mapping_unnecessarily_blocked")
    ]
    blocked_by_reason: Counter[str] = Counter()
    blocked_by_family: Counter[str] = Counter()
    blocked_by_statement: Counter[str] = Counter()
    exact_alias_count = 0
    strong_card_count = 0
    relaxable: list[dict[str, Any]] = []
    non_relaxable: list[dict[str, Any]] = []
    for record in blocked_correct:
        selected = _selected_id(record)
        card = card_index.get(selected)
        candidate = _candidate_for(record, prediction_index)
        alias = _alias_evidence(record, card, candidate)
        for reason in blocked_reasons(record):
            blocked_by_reason[reason] += 1
        blocked_by_family[_concept_family(selected, card)] += 1
        blocked_by_statement[_statement_type(record) or "unknown"] += 1
        exact_alias_count += int(bool(alias["exact_or_near_alias"]))
        strong_card_count += int(_strong_concept_card(card))
        candidate_payload = relaxation_candidate(record, prediction_index=prediction_index, card_index=card_index)
        if candidate_payload:
            relaxable.append(candidate_payload)
        else:
            blockers = _relaxation_blockers(record, prediction_index=prediction_index, card_index=card_index)
            non_relaxable.append({**_case_summary(record), "relaxation_blockers": blockers[:8]})

    broad_records = [
        record for record in records if "broad_substitute" in _issue_types(record.get("supervisor_review") or {})
    ]
    broad_cases = [
        classify_broad_substitute(record, prediction_index=prediction_index, card_index=card_index)
        for record in broad_records
    ]
    broad_counts = Counter(case["classification"] for case in broad_cases)
    over_report = {
        "run_metadata": run_metadata,
        "metrics": {
            "blocked_correct_mapping_count": len(blocked_correct),
            "blocked_correct_by_reason": dict(sorted(blocked_by_reason.items())),
            "blocked_correct_by_concept_family": dict(sorted(blocked_by_family.items())),
            "blocked_correct_by_statement_type": dict(sorted(blocked_by_statement.items())),
            "blocked_correct_with_exact_alias_match": exact_alias_count,
            "blocked_correct_with_strong_concept_card": strong_card_count,
            "blocked_correct_potentially_relaxable_count": len(relaxable),
            "broad_substitute_total": len(broad_cases),
            "broad_substitute_true_risk_count": broad_counts["true_broad_substitute_risk"],
            "broad_substitute_over_triggered_count": broad_counts["over_triggered_broad_substitute"],
            "broad_substitute_correct_but_blocked_count": sum(1 for case in broad_cases if case["mapper_correct"]),
            "broad_substitute_wrong_mapper_count": sum(1 for case in broad_cases if case["mapper_wrong"]),
        },
        "top_blocked_correct_cases": [_case_summary(record) for record in blocked_correct[:10]],
        "blocked_correct_examples": [_case_summary(record) for record in blocked_correct[:10]],
        "broad_substitute_quality": {
            "classification_counts": dict(sorted(broad_counts.items())),
            "examples": broad_cases[:12],
        },
        "non_relaxable_high_risk_examples": non_relaxable[:10],
        "recommendation": "Do not proceed to #17D-C yet; review broad_substitute over-trigger and omission behavior first.",
    }

    relax_report = {
        "run_metadata": run_metadata,
        "metrics": {
            "blocked_correct_mapping_count": len(blocked_correct),
            "relaxable_safe_accept_candidates_count": len(relaxable),
            "non_relaxable_blocked_correct_count": max(0, len(blocked_correct) - len(relaxable)),
            "candidate_not_supported_blocks_relaxation_count": sum(
                1 for item in non_relaxable if "candidate_not_supported" in item.get("relaxation_blockers", [])
            ),
            "ambiguous_label_blocks_relaxation_count": sum(
                1 for item in non_relaxable if "ambiguous_label" in item.get("relaxation_blockers", [])
            ),
            "statement_family_mismatch_blocks_relaxation_count": sum(
                1 for item in non_relaxable if "statement_family_mismatch" in item.get("relaxation_blockers", [])
            ),
        },
        "relaxable_safe_accept_candidates": relaxable,
        "non_relaxable_high_risk_examples": non_relaxable[:10],
        "recommendation": "Relaxation candidates are evaluation-only. Any future production rule must remain deterministic and human-confirmed until separately approved.",
    }
    return {
        "omission": omission_report,
        "overconservative": over_report,
        "relaxation": relax_report,
    }


def _markdown_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(value).replace("|", "\\|") for value in row) + " |")
    return "\n".join(lines)


def render_omission_markdown(report: Mapping[str, Any]) -> str:
    metrics = report.get("metrics") or {}
    rows = [[key, value] for key, value in metrics.items()]
    return "\n\n".join(
        [
            "# Supervisor Omission Analysis #17D-B Hotfix 4",
            _markdown_table(["Metric", "Value"], rows),
            "## Recommendation",
            str(report.get("recommendation") or ""),
        ]
    ) + "\n"


def render_overconservative_markdown(report: Mapping[str, Any]) -> str:
    metrics = report.get("metrics") or {}
    rows = [[key, json.dumps(value, sort_keys=True) if isinstance(value, dict) else value] for key, value in metrics.items()]
    return "\n\n".join(
        [
            "# Supervisor Over-Conservative Analysis #17D-B Hotfix 4",
            _markdown_table(["Metric", "Value"], rows),
            "## Recommendation",
            str(report.get("recommendation") or ""),
        ]
    ) + "\n"


def render_relaxation_markdown(report: Mapping[str, Any]) -> str:
    metrics = report.get("metrics") or {}
    rows = [[key, value] for key, value in metrics.items()]
    candidates = report.get("relaxable_safe_accept_candidates") or []
    candidate_rows = [
        [
            (item.get("row") or {}).get("source_case_id"),
            (item.get("row") or {}).get("label"),
            item.get("selected_concept_qname"),
            item.get("reason_relaxable"),
        ]
        for item in candidates[:10]
    ]
    return "\n\n".join(
        [
            "# Supervisor Safe Accept Relaxation Candidates #17D-B Hotfix 4",
            _markdown_table(["Metric", "Value"], rows),
            "## Candidate Examples",
            _markdown_table(["Case", "Label", "Concept", "Reason"], candidate_rows) if candidate_rows else "No relaxable candidates.",
            "## Recommendation",
            str(report.get("recommendation") or ""),
        ]
    ) + "\n"


def write_hotfix_reports(
    *,
    reports_dir: str | Path = PROJECT_ROOT / "reports",
    review_report_path: str | Path = DEFAULT_REVIEW_REPORT,
    predictions_report_path: str | Path = DEFAULT_PREDICTIONS_REPORT,
    playbook_report_path: str | Path = DEFAULT_PLAYBOOK_REPORT,
) -> dict[str, Path]:
    reports_root = _resolve(reports_dir)
    review_path = _resolve(review_report_path)
    predictions_path = _resolve(predictions_report_path)
    playbook_path = _resolve(playbook_report_path)
    reports = build_hotfix_reports(
        review_report=_read_json(review_path),
        predictions=_read_json(predictions_path),
        playbook=_read_json(playbook_path),
    )
    paths = {
        "omission_json": reports_root / "supervisor_omission_analysis_17d_b_hotfix_4.json",
        "omission_md": reports_root / "supervisor_omission_analysis_17d_b_hotfix_4.md",
        "overconservative_json": reports_root / "supervisor_overconservative_analysis_17d_b_hotfix_4.json",
        "overconservative_md": reports_root / "supervisor_overconservative_analysis_17d_b_hotfix_4.md",
        "relaxation_json": reports_root / "supervisor_safe_accept_relaxation_candidates_17d_b_hotfix_4.json",
        "relaxation_md": reports_root / "supervisor_safe_accept_relaxation_candidates_17d_b_hotfix_4.md",
    }
    reports["omission"]["run_metadata"]["source_reports"] = {
        "review": _display(review_path),
        "predictions": _display(predictions_path),
        "concept_playbook": _display(playbook_path),
    }
    reports["overconservative"]["run_metadata"]["source_reports"] = reports["omission"]["run_metadata"]["source_reports"]
    reports["relaxation"]["run_metadata"]["source_reports"] = reports["omission"]["run_metadata"]["source_reports"]
    _write_json(paths["omission_json"], reports["omission"])
    paths["omission_md"].write_text(render_omission_markdown(reports["omission"]), encoding="utf-8")
    _write_json(paths["overconservative_json"], reports["overconservative"])
    paths["overconservative_md"].write_text(render_overconservative_markdown(reports["overconservative"]), encoding="utf-8")
    _write_json(paths["relaxation_json"], reports["relaxation"])
    paths["relaxation_md"].write_text(render_relaxation_markdown(reports["relaxation"]), encoding="utf-8")
    return paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate local #17D-B hotfix-4 Supervisor diagnostics.")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--review-report", default=str(DEFAULT_REVIEW_REPORT))
    parser.add_argument("--predictions-report", default=str(DEFAULT_PREDICTIONS_REPORT))
    parser.add_argument("--playbook-report", default=str(DEFAULT_PLAYBOOK_REPORT))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = write_hotfix_reports(
        reports_dir=args.reports_dir,
        review_report_path=args.review_report,
        predictions_report_path=args.predictions_report,
        playbook_report_path=args.playbook_report,
    )
    print("supervisor_17d_b_hotfix_4_reports", json.dumps({key: str(value) for key, value in paths.items()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
