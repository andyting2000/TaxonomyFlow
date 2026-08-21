"""Offline calibration profiles for hybrid candidate ranking.

The calibration layer only reweights, filters, and summarizes already-generated
candidate evidence. It does not create candidates, finalize mappings, write
state, or mark anything safe for auto-apply.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from services.pdf_xbrl_deterministic_alignment import canonical_label
from services.tightened_mapper_evaluation import sanitize_report_value


RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
RISK_BY_ORDER = {value: key for key, value in RISK_ORDER.items()}
CRITICAL_RISK_REASONS = {
    "blocked_by_note_boundary",
    "candidate_has_critical_blocking_reason",
    "note_detail_row_blocks_main_statement_candidate_without_boundary_support",
    "predicted_qname_not_found_locally_before",
}
LOCAL_NON_LEXICAL_SOURCES = {
    "statement_role_pack",
    "section_concept_pack",
    "concept_playbook_lookup",
    "taxonomy_structure_hint",
    "note_total_candidate",
    "cash_flow_movement_pack",
    "equity_movement_pack",
    "format_memory_pack",
    "local_concept_family_pack",
}
VALIDATED_LOCAL_SOURCES = {
    "deterministic_current_mapper",
    "statement_dictionary",
    "statement_role_pack",
    "section_concept_pack",
    "concept_playbook_lookup",
    "cash_flow_movement_pack",
    "format_memory_pack",
}
SAFETY = {
    "external_llm_called": False,
    "external_provider_called": False,
    "qwen_called": False,
    "supervisor_called": False,
    "azure_di_live_call_made": False,
    "database_mutated": False,
    "production_behavior_changed": False,
    "production_mapper_integrated": False,
    "api_changed": False,
    "ui_changed": False,
    "ai_suggestion_table_written": False,
    "auto_applied": False,
    "auto_accept_recommended": False,
    "auto_reject_recommended": False,
    "confirmed_tag_id_mutated": False,
    "confirmed_tag_id_automation_recommended": False,
    "xbrl_generated": False,
    "arelle_run": False,
}


@dataclass(frozen=True)
class RankingProfileConfig:
    name: str
    description: str
    minimum_candidate_score: float
    taxonomy_lexical_minimum_score: float
    non_lexical_candidate_minimum_score: float
    deterministic_candidate_score_floor: float
    candidate_high_threshold: float
    candidate_medium_threshold: float
    candidate_low_threshold: float
    ambiguity_threshold: float
    max_candidates_per_row: int
    per_source_top_n_cap: Mapping[str, int]
    source_weights: Mapping[str, float]
    critical_risk_candidates_filtered: bool = True
    allow_uncorroborated_high_risk_candidates: bool = False
    high_risk_minimum_score: float = 0.58
    high_risk_minimum_sources: int = 2


RANKING_PROFILES: dict[str, RankingProfileConfig] = {
    "strict": RankingProfileConfig(
        name="strict",
        description="Precision-first profile with stronger thresholds, tighter source caps, and broad high-risk blocking.",
        minimum_candidate_score=0.64,
        taxonomy_lexical_minimum_score=0.66,
        non_lexical_candidate_minimum_score=0.60,
        deterministic_candidate_score_floor=0.72,
        candidate_high_threshold=0.84,
        candidate_medium_threshold=0.70,
        candidate_low_threshold=0.58,
        ambiguity_threshold=0.07,
        max_candidates_per_row=3,
        per_source_top_n_cap={
            "taxonomy_lexical": 1,
            "concept_playbook_lookup": 2,
            "section_concept_pack": 2,
            "statement_dictionary": 2,
            "local_concept_family_pack": 1,
            "taxonomy_structure_hint": 1,
            "cash_flow_movement_pack": 2,
            "equity_movement_pack": 1,
            "statement_role_pack": 2,
            "deterministic_current_mapper": 3,
        },
        source_weights={
            "deterministic_current_mapper": 1.12,
            "statement_dictionary": 1.06,
            "statement_role_pack": 1.09,
            "section_concept_pack": 1.07,
            "concept_playbook_lookup": 1.07,
            "cash_flow_movement_pack": 1.03,
            "equity_movement_pack": 1.02,
            "format_memory_pack": 1.07,
            "local_concept_family_pack": 0.99,
            "taxonomy_structure_hint": 0.98,
            "note_total_candidate": 0.96,
            "taxonomy_lexical": 0.90,
            "cached_qwen": 0.94,
        },
        allow_uncorroborated_high_risk_candidates=False,
        high_risk_minimum_score=0.70,
        high_risk_minimum_sources=3,
    ),
    "balanced": RankingProfileConfig(
        name="balanced",
        description="Default profile that preserves useful coverage while controlling risk for backend advisory design.",
        minimum_candidate_score=0.44,
        taxonomy_lexical_minimum_score=0.44,
        non_lexical_candidate_minimum_score=0.44,
        deterministic_candidate_score_floor=0.63,
        candidate_high_threshold=0.78,
        candidate_medium_threshold=0.62,
        candidate_low_threshold=0.45,
        ambiguity_threshold=0.05,
        max_candidates_per_row=5,
        per_source_top_n_cap={
            "taxonomy_lexical": 2,
            "concept_playbook_lookup": 3,
            "section_concept_pack": 3,
            "statement_dictionary": 3,
            "local_concept_family_pack": 2,
            "taxonomy_structure_hint": 1,
            "cash_flow_movement_pack": 3,
            "equity_movement_pack": 2,
            "statement_role_pack": 3,
            "deterministic_current_mapper": 5,
        },
        source_weights={
            "deterministic_current_mapper": 1.09,
            "statement_dictionary": 1.05,
            "statement_role_pack": 1.08,
            "section_concept_pack": 1.06,
            "concept_playbook_lookup": 1.07,
            "cash_flow_movement_pack": 1.03,
            "equity_movement_pack": 1.02,
            "format_memory_pack": 1.06,
            "local_concept_family_pack": 1.01,
            "taxonomy_structure_hint": 0.99,
            "note_total_candidate": 0.98,
            "taxonomy_lexical": 0.94,
            "cached_qwen": 0.97,
        },
        allow_uncorroborated_high_risk_candidates=False,
        high_risk_minimum_score=0.49,
        high_risk_minimum_sources=2,
    ),
    "recall": RankingProfileConfig(
        name="recall",
        description="Human-review profile that keeps more review-required candidates while still filtering critical risk.",
        minimum_candidate_score=0.43,
        taxonomy_lexical_minimum_score=0.44,
        non_lexical_candidate_minimum_score=0.42,
        deterministic_candidate_score_floor=0.52,
        candidate_high_threshold=0.74,
        candidate_medium_threshold=0.58,
        candidate_low_threshold=0.42,
        ambiguity_threshold=0.04,
        max_candidates_per_row=7,
        per_source_top_n_cap={
            "taxonomy_lexical": 3,
            "concept_playbook_lookup": 4,
            "section_concept_pack": 4,
            "statement_dictionary": 4,
            "local_concept_family_pack": 3,
            "taxonomy_structure_hint": 2,
            "cash_flow_movement_pack": 4,
            "equity_movement_pack": 3,
            "statement_role_pack": 4,
            "deterministic_current_mapper": 7,
        },
        source_weights={
            "deterministic_current_mapper": 1.06,
            "statement_dictionary": 1.03,
            "statement_role_pack": 1.05,
            "section_concept_pack": 1.04,
            "concept_playbook_lookup": 1.04,
            "cash_flow_movement_pack": 1.02,
            "equity_movement_pack": 1.02,
            "format_memory_pack": 1.04,
            "local_concept_family_pack": 1.00,
            "taxonomy_structure_hint": 1.00,
            "note_total_candidate": 1.00,
            "taxonomy_lexical": 0.98,
            "cached_qwen": 1.00,
        },
        allow_uncorroborated_high_risk_candidates=True,
        high_risk_minimum_score=0.50,
        high_risk_minimum_sources=1,
    ),
}
DEFAULT_RANKING_PROFILE = "balanced"


def available_ranking_profiles() -> list[str]:
    return list(RANKING_PROFILES)


def get_ranking_profile(profile: str | RankingProfileConfig | None = None) -> RankingProfileConfig:
    if isinstance(profile, RankingProfileConfig):
        return profile
    name = profile or DEFAULT_RANKING_PROFILE
    if name not in RANKING_PROFILES:
        raise ValueError(f"Unknown ranking profile: {name}")
    return RANKING_PROFILES[name]


def profile_config_to_dict(profile: str | RankingProfileConfig | None = None) -> dict[str, Any]:
    config = get_ranking_profile(profile)
    return {
        "name": config.name,
        "description": config.description,
        "minimum_candidate_score": config.minimum_candidate_score,
        "taxonomy_lexical_minimum_score": config.taxonomy_lexical_minimum_score,
        "non_lexical_candidate_minimum_score": config.non_lexical_candidate_minimum_score,
        "deterministic_candidate_score_floor": config.deterministic_candidate_score_floor,
        "candidate_high_threshold": config.candidate_high_threshold,
        "candidate_medium_threshold": config.candidate_medium_threshold,
        "candidate_low_threshold": config.candidate_low_threshold,
        "ambiguity_threshold": config.ambiguity_threshold,
        "max_candidates_per_row": config.max_candidates_per_row,
        "per_source_top_n_cap": dict(config.per_source_top_n_cap),
        "source_weights": dict(config.source_weights),
        "critical_risk_candidates_filtered": config.critical_risk_candidates_filtered,
        "allow_uncorroborated_high_risk_candidates": config.allow_uncorroborated_high_risk_candidates,
        "high_risk_minimum_score": config.high_risk_minimum_score,
        "high_risk_minimum_sources": config.high_risk_minimum_sources,
        "safe_for_auto_apply": False,
        "requires_human_review": True,
    }


def _unique(values: Sequence[Any]) -> list[str]:
    return sorted({str(value) for value in values if value not in (None, "")})


def _sources(candidate: Mapping[str, Any]) -> list[str]:
    return _unique(candidate.get("candidate_sources_combined") or [candidate.get("candidate_source")])


def _is_standalone_taxonomy_lexical(candidate: Mapping[str, Any]) -> bool:
    sources = set(_sources(candidate))
    return sources == {"taxonomy_lexical"} or (candidate.get("candidate_source") == "taxonomy_lexical" and len(sources) <= 1)


def _has_non_lexical_source(candidate: Mapping[str, Any]) -> bool:
    return any(source in LOCAL_NON_LEXICAL_SOURCES for source in _sources(candidate))


def _has_strong_context(candidate: Mapping[str, Any]) -> bool:
    evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), Mapping) else {}
    return bool(
        evidence.get("statement_family_match")
        and (
            evidence.get("section_context_match")
            or evidence.get("template_match")
            or evidence.get("dictionary_match")
            or evidence.get("format_memory_match")
            or evidence.get("note_link_match")
            or evidence.get("row_order_match")
            or evidence.get("local_structured_match")
        )
    )


def _is_strongly_corroborated(candidate: Mapping[str, Any], profile: RankingProfileConfig) -> bool:
    sources = set(_sources(candidate))
    evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), Mapping) else {}
    similarity = float(evidence.get("label_similarity") or 0.0)
    if len(sources) >= profile.high_risk_minimum_sources:
        return True
    if "deterministic_current_mapper" in sources and (sources & (VALIDATED_LOCAL_SOURCES | {"taxonomy_lexical"})):
        return True
    if _has_strong_context(candidate) and similarity >= 0.99 and (sources & VALIDATED_LOCAL_SOURCES or int(evidence.get("prior_exact_match_evidence") or 0) > 0):
        return True
    if _has_strong_context(candidate) and int(evidence.get("prior_exact_match_evidence") or 0) >= 2:
        return True
    return _has_strong_context(candidate) and len(sources) >= 2


def _risk_at_least(current: str, minimum: str) -> str:
    return RISK_BY_ORDER[max(RISK_ORDER.get(current, 0), RISK_ORDER.get(minimum, 0))]


def _calibrated_risk_level(candidate: Mapping[str, Any]) -> str:
    risk = str(candidate.get("risk_level") or "low")
    if risk not in RISK_ORDER:
        risk = "medium"
    reasons = set(str(item) for item in candidate.get("risk_reasons") or [])
    reasons.update(str(item) for item in candidate.get("blocking_reasons") or [])
    reasons.update(str(item) for item in candidate.get("ambiguity_reasons") or [])
    if reasons & CRITICAL_RISK_REASONS:
        return "critical"
    if "multiple_competing_candidates_close_in_score" in reasons or "profile_close_candidate_ambiguity" in reasons:
        risk = _risk_at_least(risk, "medium")
    if "source_conflict" in reasons:
        risk = _risk_at_least(risk, "high")
    return risk


def _source_weight(candidate: Mapping[str, Any], profile: RankingProfileConfig) -> float:
    sources = _sources(candidate)
    if not sources:
        return 1.0
    best = max(float(profile.source_weights.get(source, 1.0)) for source in sources)
    corroboration_bonus = min(0.04, max(0, len(sources) - 1) * 0.015)
    return best + corroboration_bonus


def _candidate_score(candidate: Mapping[str, Any], profile: RankingProfileConfig) -> float:
    base_score = float(candidate.get("score") or 0.0)
    score = base_score * _source_weight(candidate, profile)
    sources = set(_sources(candidate))
    if "deterministic_current_mapper" in sources:
        score = max(score, profile.deterministic_candidate_score_floor)
    risk = _calibrated_risk_level(candidate)
    if risk == "high":
        score -= 0.06 if profile.name == "strict" else 0.025 if profile.name == "balanced" else 0.01
    elif risk == "medium":
        score -= 0.015 if profile.name == "strict" else 0.005 if profile.name == "balanced" else 0.0
    if _is_standalone_taxonomy_lexical(candidate):
        score -= 0.025 if profile.name in {"strict", "balanced"} else 0.0
    return round(max(0.0, min(0.99, score)), 4)


def _confidence_bucket(score: float, risk_level: str, profile: RankingProfileConfig) -> str:
    if risk_level == "critical":
        return "candidate_review_only"
    if score >= profile.candidate_high_threshold and risk_level in {"low", "medium"}:
        return "candidate_high"
    if score >= profile.candidate_medium_threshold and risk_level != "critical":
        return "candidate_medium"
    if score >= profile.candidate_low_threshold:
        return "candidate_low"
    return "candidate_review_only"


def _profile_filter_reasons(
    candidate: Mapping[str, Any],
    *,
    profile: RankingProfileConfig,
    score: float,
    risk: str,
) -> list[str]:
    reasons: list[str] = []
    sources = set(_sources(candidate))
    if profile.critical_risk_candidates_filtered and risk == "critical":
        reasons.append("profile_filters_critical_risk_candidate")
    if score < profile.minimum_candidate_score:
        reasons.append("profile_candidate_score_below_minimum")
    if _is_standalone_taxonomy_lexical(candidate) and score < profile.taxonomy_lexical_minimum_score:
        reasons.append("profile_taxonomy_lexical_score_below_minimum")
    if _has_non_lexical_source(candidate) and score < profile.non_lexical_candidate_minimum_score:
        reasons.append("profile_non_lexical_score_below_minimum")
    if risk == "high":
        corroborated = _is_strongly_corroborated(candidate, profile)
        if score < profile.high_risk_minimum_score:
            reasons.append("profile_high_risk_score_below_minimum")
        if not profile.allow_uncorroborated_high_risk_candidates and not corroborated:
            reasons.append("profile_high_risk_requires_corroboration")
        if profile.name == "strict" and "deterministic_current_mapper" not in sources and len(sources) < profile.high_risk_minimum_sources:
            reasons.append("strict_profile_high_risk_requires_validated_sources")
    return _unique(reasons)


def _primary_source(candidate: Mapping[str, Any], profile: RankingProfileConfig) -> str:
    sources = _sources(candidate)
    if not sources:
        return "unknown"
    return max(sources, key=lambda source: float(profile.source_weights.get(source, 1.0)))


def _filter_record(candidate: Mapping[str, Any], reasons: Sequence[str], profile: RankingProfileConfig) -> dict[str, Any]:
    return {
        "qname": candidate.get("qname"),
        "concept_label": candidate.get("concept_label"),
        "candidate_sources_combined": _sources(candidate),
        "score": candidate.get("score"),
        "risk_level": candidate.get("risk_level"),
        "profile": profile.name,
        "filter_reasons": _unique(reasons),
    }


def _calibrate_candidate(candidate: Mapping[str, Any], profile: RankingProfileConfig) -> dict[str, Any]:
    calibrated = dict(candidate)
    calibrated["base_score"] = round(float(candidate.get("score") or 0.0), 4)
    calibrated["candidate_sources_combined"] = _sources(candidate)
    calibrated["candidate_source"] = calibrated.get("candidate_source") or (_sources(candidate)[0] if _sources(candidate) else "unknown")
    calibrated["requires_human_review"] = True
    calibrated["safe_for_auto_apply"] = False
    calibrated["calibration_profile"] = profile.name
    calibrated["source_weight"] = round(_source_weight(candidate, profile), 4)
    calibrated["score"] = _candidate_score(candidate, profile)
    calibrated["risk_level"] = _calibrated_risk_level(candidate)
    calibrated["confidence_bucket"] = _confidence_bucket(float(calibrated["score"]), str(calibrated["risk_level"]), profile)
    calibrated["profile_filter_reasons"] = _profile_filter_reasons(
        calibrated,
        profile=profile,
        score=float(calibrated["score"]),
        risk=str(calibrated["risk_level"]),
    )
    return calibrated


def apply_ranking_profile_to_row(
    row: Mapping[str, Any],
    profile: str | RankingProfileConfig | None = None,
    *,
    top_n: int | None = None,
) -> dict[str, Any]:
    config = get_ranking_profile(profile)
    effective_top_n = min(top_n or config.max_candidates_per_row, config.max_candidates_per_row)
    filtered_candidates = [dict(item) for item in row.get("filtered_candidates") or [] if isinstance(item, Mapping)]
    blocked_candidates = [dict(item) for item in row.get("blocked_candidates") or [] if isinstance(item, Mapping)]

    candidates = []
    for candidate in row.get("candidates") or []:
        if not isinstance(candidate, Mapping):
            continue
        calibrated = _calibrate_candidate(candidate, config)
        reasons = calibrated.pop("profile_filter_reasons", [])
        if reasons:
            filtered_candidates.append(_filter_record(calibrated, reasons, config))
            continue
        candidates.append(calibrated)

    candidates.sort(key=lambda item: (-float(item.get("score") or 0.0), RISK_ORDER.get(str(item.get("risk_level")), 9), str(item.get("qname") or "")))
    kept: list[dict[str, Any]] = []
    source_counts: Counter[str] = Counter()
    for candidate in candidates:
        primary = _primary_source(candidate, config)
        cap = config.per_source_top_n_cap.get(primary)
        if cap is not None and source_counts[primary] >= cap:
            filtered_candidates.append(_filter_record(candidate, [f"profile_per_source_top_n_cap:{primary}"], config))
            continue
        if len(kept) >= effective_top_n:
            filtered_candidates.append(_filter_record(candidate, ["profile_max_candidates_per_row"], config))
            continue
        source_counts[primary] += 1
        kept.append(candidate)

    if len(kept) > 1 and (float(kept[0].get("score") or 0.0) - float(kept[1].get("score") or 0.0)) <= config.ambiguity_threshold:
        for candidate in kept[:2]:
            candidate["ambiguity_reasons"] = _unique([*(candidate.get("ambiguity_reasons") or []), "profile_close_candidate_ambiguity"])
            candidate["risk_level"] = _risk_at_least(str(candidate.get("risk_level") or "low"), "medium")
            candidate["confidence_bucket"] = _confidence_bucket(float(candidate.get("score") or 0.0), str(candidate["risk_level"]), config)

    for index, candidate in enumerate(kept, start=1):
        candidate["rank"] = index
        candidate["requires_human_review"] = True
        candidate["safe_for_auto_apply"] = False

    if kept:
        deterministic_only = all(candidate.get("candidate_sources_combined") == ["deterministic_current_mapper"] for candidate in kept)
        status = "deterministic_candidate_available" if deterministic_only else "ranked_candidates_available"
    elif blocked_candidates:
        status = "blocked_by_note_boundary"
    elif row.get("value") in (None, "") and row.get("pdf_value") in (None, ""):
        status = "not_evaluable"
    else:
        status = "profile_filtered_all_candidates"

    output = dict(row)
    output.update(
        {
            "ranking_profile": config.name,
            "candidate_coverage_status": status,
            "candidate_count": len(kept),
            "filtered_candidate_count": len(filtered_candidates),
            "filtered_candidates": filtered_candidates[:40],
            "candidates": kept,
            "requires_human_review": True,
            "safe_for_auto_apply": False,
        }
    )
    return sanitize_report_value(output)


def apply_ranking_profile_to_rows(
    rows: Sequence[Mapping[str, Any]],
    profile: str | RankingProfileConfig | None = None,
    *,
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    return [apply_ranking_profile_to_row(row, profile, top_n=top_n) for row in rows]


def _summary_from_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    covered = [row for row in rows if int(row.get("candidate_count") or 0) > 0]
    with_three = [row for row in rows if int(row.get("candidate_count") or 0) >= 3]
    candidates = [candidate for row in rows for candidate in row.get("candidates") or []]
    risk_counts: Counter[str] = Counter(str(candidate.get("risk_level") or "unknown") for candidate in candidates)
    source_counts: Counter[str] = Counter(source for candidate in candidates for source in candidate.get("candidate_sources_combined") or [])
    source_row_counts: Counter[str] = Counter()
    confidence_counts: Counter[str] = Counter(str(candidate.get("confidence_bucket") or "unknown") for candidate in candidates)
    ambiguity_count = sum(1 for candidate in candidates if candidate.get("ambiguity_reasons"))
    for row in rows:
        row_sources = {source for candidate in row.get("candidates") or [] for source in candidate.get("candidate_sources_combined") or []}
        source_row_counts.update(row_sources)
    candidate_total = len(candidates)
    high_or_critical = int(risk_counts.get("high") or 0) + int(risk_counts.get("critical") or 0)
    return {
        "total_observations": total,
        "rows_with_at_least_1_candidate": len(covered),
        "rows_with_at_least_3_candidates": len(with_three),
        "no_candidate_rows": total - len(covered),
        "total_candidate_count": candidate_total,
        "average_candidates_per_covered_row": round(candidate_total / len(covered), 4) if covered else None,
        "candidate_coverage_rate": round(len(covered) / total, 4) if total else None,
        "three_candidate_coverage_rate": round(len(with_three) / total, 4) if total else None,
        "risk_distribution": dict(sorted(risk_counts.items())),
        "high_or_critical_candidate_count": high_or_critical,
        "high_or_critical_candidate_ratio": round(high_or_critical / candidate_total, 4) if candidate_total else 0.0,
        "critical_candidate_count": int(risk_counts.get("critical") or 0),
        "confidence_bucket_distribution": dict(sorted(confidence_counts.items())),
        "ambiguity_count": ambiguity_count,
        "ambiguity_ratio": round(ambiguity_count / candidate_total, 4) if candidate_total else 0.0,
        "candidate_source_counts": dict(sorted(source_counts.items())),
        "candidate_source_row_counts": dict(sorted(source_row_counts.items())),
        "safe_for_auto_apply_count": sum(1 for candidate in candidates if candidate.get("safe_for_auto_apply") is True),
        "requires_human_review_count": sum(1 for candidate in candidates if candidate.get("requires_human_review") is True),
        "safety": dict(SAFETY),
    }


def _row_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row.get("sample_id") or ""), str(row.get("row_id") or row.get("pdf_row_id") or "")


def _top_affected_labels(
    baseline_rows: Sequence[Mapping[str, Any]] | None,
    profile_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    baseline_index = {_row_key(row): row for row in baseline_rows or []}
    affected: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "candidate_delta": 0})
    for row in profile_rows:
        base = baseline_index.get(_row_key(row))
        if base is None:
            continue
        before = int(base.get("candidate_count") or 0)
        after = int(row.get("candidate_count") or 0)
        if before == after:
            continue
        label = str(row.get("normalized_label") or canonical_label(row.get("pdf_label")))
        affected[label]["count"] += 1
        affected[label]["candidate_delta"] += after - before
    return [
        {"normalized_label": label, "count": values["count"], "candidate_delta": values["candidate_delta"]}
        for label, values in sorted(affected.items(), key=lambda item: (-abs(item[1]["candidate_delta"]), item[0]))[:40]
    ]


def _rows_losing_all_candidates(
    baseline_rows: Sequence[Mapping[str, Any]] | None,
    profile_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    baseline_index = {_row_key(row): row for row in baseline_rows or []}
    rows = []
    for row in profile_rows:
        base = baseline_index.get(_row_key(row))
        if not base or int(base.get("candidate_count") or 0) == 0 or int(row.get("candidate_count") or 0) > 0:
            continue
        rows.append(
            {
                "sample_id": row.get("sample_id"),
                "row_id": row.get("row_id"),
                "normalized_label": row.get("normalized_label") or canonical_label(row.get("pdf_label")),
                "baseline_candidate_count": base.get("candidate_count"),
                "profile_filtered_candidate_count": row.get("filtered_candidate_count"),
                "filtered_candidates": row.get("filtered_candidates"),
            }
        )
    return rows


def _high_risk_labels(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    labels: Counter[str] = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        label = str(row.get("normalized_label") or canonical_label(row.get("pdf_label")))
        for candidate in row.get("candidates") or []:
            if candidate.get("risk_level") not in {"high", "critical"}:
                continue
            labels[label] += 1
            if len(examples[label]) < 5:
                examples[label].append(str(candidate.get("qname") or ""))
    return [
        {"normalized_label": label, "candidate_count": count, "example_qnames": examples[label]}
        for label, count in labels.most_common(40)
    ]


def _uncovered_labels(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    labels = Counter(
        str(row.get("normalized_label") or canonical_label(row.get("pdf_label")))
        for row in rows
        if int(row.get("candidate_count") or 0) == 0
    )
    return [{"normalized_label": label, "count": count} for label, count in labels.most_common(60)]


def candidate_quality_score(summary: Mapping[str, Any], evaluation_summary: Mapping[str, Any]) -> float:
    coverage = float(summary.get("candidate_coverage_rate") or 0.0)
    top1 = float(evaluation_summary.get("top1_precision_if_evaluable") or 0.0)
    top3 = float(evaluation_summary.get("top3_recall_if_evaluable") or 0.0)
    top5 = float(evaluation_summary.get("top5_recall_if_evaluable") or 0.0)
    high_ratio = float(summary.get("high_or_critical_candidate_ratio") or 0.0)
    ambiguity_ratio = float(summary.get("ambiguity_ratio") or 0.0)
    score = (
        coverage * 22.0
        + top1 * 34.0
        + top3 * 20.0
        + top5 * 14.0
        + max(0.0, 1.0 - high_ratio) * 8.0
        - ambiguity_ratio * 6.0
    )
    return round(max(0.0, min(100.0, score)), 4)


def risk_controlled(summary: Mapping[str, Any]) -> bool:
    return (
        int(summary.get("critical_candidate_count") or 0) == 0
        and float(summary.get("high_or_critical_candidate_ratio") or 0.0) <= 0.32
        and int(summary.get("safe_for_auto_apply_count") or 0) == 0
    )


def build_profile_metrics(
    *,
    profile: str | RankingProfileConfig,
    rows: Sequence[Mapping[str, Any]],
    evaluation: Mapping[str, Any] | None = None,
    baseline_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    config = get_ranking_profile(profile)
    summary = _summary_from_rows(rows)
    evaluation_summary = dict((evaluation or {}).get("summary") or {})
    losing_rows = _rows_losing_all_candidates(baseline_rows, rows)
    quality = candidate_quality_score(summary, evaluation_summary)
    return sanitize_report_value(
        {
            "profile": config.name,
            "profile_config": profile_config_to_dict(config),
            "summary": {
                **summary,
                "top1_precision_if_evaluable": evaluation_summary.get("top1_precision_if_evaluable"),
                "top3_recall_if_evaluable": evaluation_summary.get("top3_recall_if_evaluable"),
                "top5_recall_if_evaluable": evaluation_summary.get("top5_recall_if_evaluable"),
                "locally_evaluable_unique_support_rows": evaluation_summary.get("locally_evaluable_unique_support_rows"),
                "candidate_rows_with_local_support": evaluation_summary.get("candidate_rows_with_local_support"),
                "risk_controlled": risk_controlled(summary),
                "candidate_quality_score": quality,
                "rows_losing_all_candidates": len(losing_rows),
            },
            "source_contribution": summary.get("candidate_source_counts") or {},
            "source_row_contribution": summary.get("candidate_source_row_counts") or {},
            "rows_losing_all_candidates": losing_rows[:160],
            "labels_most_affected": _top_affected_labels(baseline_rows, rows),
            "high_risk_labels_still_present": _high_risk_labels(rows),
            "still_uncovered_labels": _uncovered_labels(rows),
            "evaluation_summary": evaluation_summary,
            "safety": dict(SAFETY),
        }
    )


def select_recommended_profile(profile_metrics: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    balanced = profile_metrics.get("balanced", {}).get("summary") or {}
    recall = profile_metrics.get("recall", {}).get("summary") or {}
    strict = profile_metrics.get("strict", {}).get("summary") or {}

    balanced_ok = (
        float(balanced.get("candidate_coverage_rate") or 0.0) >= 0.60
        and float(balanced.get("top1_precision_if_evaluable") or 0.0) >= 0.75
        and bool(balanced.get("risk_controlled"))
    )
    recall_ok = (
        float(recall.get("candidate_coverage_rate") or 0.0) >= 0.60
        and float(recall.get("top1_precision_if_evaluable") or 0.0) >= 0.72
        and int(recall.get("critical_candidate_count") or 0) == 0
    )
    all_noisy = all(
        float((profile_metrics.get(name, {}).get("summary") or {}).get("high_or_critical_candidate_ratio") or 0.0) > 0.40
        for name in ("strict", "balanced", "recall")
    )

    if balanced_ok:
        profile = "balanced"
        next_feature = "Feature #18F-C - Design backend advisory integration for ranked candidates, no auto-apply"
        reason = "Balanced preserves >=60% coverage, keeps top-1 precision >=0.75, and controls high/critical risk without critical candidates."
    elif recall_ok and float(balanced.get("candidate_coverage_rate") or 0.0) < 0.60:
        profile = "recall"
        next_feature = "Feature #18F-B-hotfix-1 - Adjust balanced thresholds and source weights"
        reason = "Recall is acceptable for human review, but balanced is too restrictive for advisory integration."
    elif all_noisy:
        profile = "strict" if float(strict.get("candidate_quality_score") or 0.0) >= float(balanced.get("candidate_quality_score") or 0.0) else "balanced"
        next_feature = "Feature #18E-F-A-hotfix-3 - Disable noisy lexical families and require source corroboration"
        reason = "All profiles remain noisy, so lexical-family suppression and stronger corroboration gates are needed before integration design."
    elif max(float((profile_metrics.get(name, {}).get("summary") or {}).get("candidate_coverage_rate") or 0.0) for name in profile_metrics) < 0.60:
        profile = "recall"
        next_feature = "Feature #18E-F-A-3 - Add statement-specific candidate packs for remaining uncovered rows"
        reason = "All profiles remain below 60% coverage after calibration."
    else:
        scores = {
            name: float((metrics.get("summary") or {}).get("candidate_quality_score") or 0.0)
            for name, metrics in profile_metrics.items()
        }
        profile = max(scores, key=scores.get)
        next_feature = "Feature #18F-B-hotfix-1 - Adjust balanced thresholds and source weights"
        reason = "No profile fully satisfies the balanced integration gate; use the highest quality profile as calibration evidence and tune balanced next."

    selected = profile_metrics.get(profile, {}).get("summary") or {}
    return sanitize_report_value(
        {
            "recommended_profile": profile,
            "reason": reason,
            "recommended_next_feature": next_feature,
            "backend_advisory_integration_justified": next_feature.startswith("Feature #18F-C"),
            "basis": {
                "candidate_coverage_rate": selected.get("candidate_coverage_rate"),
                "top1_precision_if_evaluable": selected.get("top1_precision_if_evaluable"),
                "top3_recall_if_evaluable": selected.get("top3_recall_if_evaluable"),
                "top5_recall_if_evaluable": selected.get("top5_recall_if_evaluable"),
                "high_or_critical_candidate_ratio": selected.get("high_or_critical_candidate_ratio"),
                "critical_candidate_count": selected.get("critical_candidate_count"),
                "risk_controlled": selected.get("risk_controlled"),
                "candidate_quality_score": selected.get("candidate_quality_score"),
                "safe_for_auto_apply_count": selected.get("safe_for_auto_apply_count"),
            },
            "profile_order": {
                name: (metrics.get("summary") or {}).get("candidate_quality_score")
                for name, metrics in profile_metrics.items()
            },
            "safety": dict(SAFETY),
        }
    )
