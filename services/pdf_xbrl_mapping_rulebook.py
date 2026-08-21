"""Offline reusable PDF-row to XBRL mapping rulebook builder for Feature #18B."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Sequence

from services.pdf_xbrl_deterministic_alignment import canonical_label, normalize_label


ACTIVE_BUCKETS = {"high", "medium"}
UNSAFE_BUCKETS = {"ambiguous", "low"}
MAJOR_CONFLICTS = {
    "sign_mismatch_absolute_value_only",
    "statement_family_mismatch",
    "period_type_mismatch",
    "current_comparative_period_confusion",
    "one_xbrl_fact_matches_multiple_pdf_rows",
}
GENERIC_LABELS = {
    "amount",
    "addition",
    "balance",
    "current",
    "disposal",
    "less",
    "movement",
    "net",
    "other",
    "total",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    text = _clean_text(value)
    if not text:
        return None
    text = text.replace(",", "").replace(" ", "")
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    text = re.sub(r"[^0-9.+-]", "", text)
    if text in {"", "-", "+", ".", "-.", "+."}:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _is_zero(value: Any) -> bool:
    number = _decimal(value)
    return number is not None and number == 0


def _period_type(alignment: Mapping[str, Any]) -> str | None:
    period = alignment.get("xbrl_period") or {}
    if isinstance(period, Mapping):
        value = period.get("type")
        return str(value) if value else None
    return None


def _source_alignment_id(alignment: Mapping[str, Any]) -> str:
    return ":".join(
        str(part or "")
        for part in (
            alignment.get("sample_id"),
            alignment.get("pdf_row_id"),
            alignment.get("xbrl_fact_id"),
        )
    )


def _score_values(observations: Sequence[Mapping[str, Any]]) -> list[int]:
    scores = []
    for item in observations:
        try:
            scores.append(int(item.get("score") or 0))
        except (TypeError, ValueError):
            continue
    return scores


def _mean(values: Sequence[int]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _unique_sorted(values: Sequence[Any]) -> list[str]:
    return sorted({str(value) for value in values if value not in (None, "")})


def _most_common(values: Sequence[Any]) -> str | None:
    counter = Counter(str(value) for value in values if value not in (None, ""))
    return counter.most_common(1)[0][0] if counter else None


def _is_generic_label(pattern: str) -> bool:
    tokens = pattern.split()
    if not pattern:
        return True
    if pattern in GENERIC_LABELS:
        return True
    if len(tokens) == 1 and tokens[0] in GENERIC_LABELS:
        return True
    if len(tokens) <= 1 and pattern.startswith(("total", "other", "current")):
        return True
    return False


def _simple_alias_variants(label: str) -> list[str]:
    normalized = normalize_label(label)
    variants = {normalized}
    canonical = canonical_label(label)
    if canonical:
        variants.add(canonical)
    tokens = normalized.split()
    if tokens:
        last = tokens[-1]
        if last.endswith("s") and not last.endswith("ss") and len(last) > 3:
            variants.add(" ".join([*tokens[:-1], last[:-1]]))
        elif len(last) > 3:
            variants.add(" ".join([*tokens[:-1], f"{last}s"]))
    return sorted(value for value in variants if value)


def _competing_qnames(observations: Sequence[Mapping[str, Any]]) -> list[str]:
    qnames = set()
    for item in observations:
        for candidate in item.get("competing_candidates") or []:
            qname = candidate.get("xbrl_qname")
            if qname:
                qnames.add(str(qname))
    return sorted(qnames)


def _entry_key(alignment: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        canonical_label(alignment.get("pdf_label")),
        str(alignment.get("pdf_statement_family") or "unknown"),
        str(alignment.get("xbrl_qname") or ""),
    )


def _label_statement_key(alignment: Mapping[str, Any]) -> tuple[str, str]:
    return (canonical_label(alignment.get("pdf_label")), str(alignment.get("pdf_statement_family") or "unknown"))


def _label_qname_key(alignment: Mapping[str, Any]) -> tuple[str, str]:
    return (canonical_label(alignment.get("pdf_label")), str(alignment.get("xbrl_qname") or ""))


def _status_counts(observations: Sequence[Mapping[str, Any]]) -> Counter[str]:
    return Counter(str(item.get("confidence_bucket") or "unknown") for item in observations)


def _safe_observations(observations: Sequence[Mapping[str, Any]], include_medium: bool) -> list[Mapping[str, Any]]:
    allowed = {"high", "medium"} if include_medium else {"high"}
    return [item for item in observations if item.get("confidence_bucket") in allowed]


def _entry_conflicts(
    *,
    pattern: str,
    statement_family: str,
    target_qname: str,
    observations: Sequence[Mapping[str, Any]],
    safe_observations: Sequence[Mapping[str, Any]],
    label_statement_qnames: Mapping[tuple[str, str], set[str]],
    label_qname_families: Mapping[tuple[str, str], set[str]],
    qname_label_patterns: Mapping[str, set[str]],
    exclude_zero_only: bool,
) -> tuple[list[str], list[str], str | None]:
    conflict_reasons = set()
    exclusion_reasons = []
    observed_conflicts = {
        str(reason)
        for item in observations
        for reason in (item.get("conflict_reasons") or [])
        if reason
    }
    conflict_reasons.update(observed_conflicts)
    if observed_conflicts & MAJOR_CONFLICTS:
        conflict_reasons.add("major_alignment_conflict")

    qname_options = label_statement_qnames.get((pattern, statement_family), set())
    if len(qname_options) > 1:
        conflict_reasons.add("label_statement_maps_to_multiple_qnames")
        exclusion_reasons.append("conflicting_qnames")

    family_options = label_qname_families.get((pattern, target_qname), set())
    if len(family_options) > 1:
        conflict_reasons.add("statement_family_conflict")

    label_options = qname_label_patterns.get(target_qname, set())
    if len(label_options) >= 4:
        conflict_reasons.add("target_qname_maps_from_many_label_patterns")

    values = [item.get("pdf_value") for item in safe_observations or observations]
    zero_only = bool(values) and all(_is_zero(value) for value in values)
    if exclude_zero_only and zero_only:
        conflict_reasons.add("zero_only_evidence")
        exclusion_reasons.append("zero_only_evidence")

    if _is_generic_label(pattern) and statement_family == "unknown":
        conflict_reasons.add("generic_label_without_statement_context")
        exclusion_reasons.append("generic_label_without_statement_context")
    elif _is_generic_label(pattern):
        conflict_reasons.add("generic_label_requires_review")

    if not safe_observations:
        if any(item.get("confidence_bucket") == "ambiguous" for item in observations):
            exclusion_reasons.append("ambiguous_alignment_only")
        elif any(item.get("confidence_bucket") == "low" for item in observations):
            exclusion_reasons.append("low_confidence_only")
        else:
            exclusion_reasons.append("no_active_evidence")

    if any(item.get("confidence_bucket") == "ambiguous" for item in observations):
        conflict_reasons.add("ambiguous_observations_present")

    exclusion_reason = "; ".join(dict.fromkeys(exclusion_reasons)) or None
    return sorted(conflict_reasons), sorted(exclusion_reasons), exclusion_reason


def _label_support(safe_observations: Sequence[Mapping[str, Any]]) -> bool:
    reasons = {
        str(reason)
        for item in safe_observations
        for reason in (item.get("match_reasons") or [])
    }
    return bool({"exact_normalized_label", "alias_match", "label_containment"} & reasons)


def _classify_entry(
    *,
    safe_observations: Sequence[Mapping[str, Any]],
    status_counts: Counter[str],
    scores: Sequence[int],
    conflict_reasons: Sequence[str],
    exclusion_reason: str | None,
    min_strong_support: int,
) -> tuple[str, str, str | None, list[str]]:
    notes = []
    if exclusion_reason:
        return "excluded", "excluded", exclusion_reason, notes

    high_count = status_counts.get("high", 0)
    medium_count = status_counts.get("medium", 0)
    safe_count = len(safe_observations)
    major_conflict = bool(set(conflict_reasons) & (MAJOR_CONFLICTS | {"major_alignment_conflict"}))
    review_flags = {
        "statement_family_conflict",
        "generic_label_requires_review",
        "ambiguous_observations_present",
    }

    if "label_statement_maps_to_multiple_qnames" in conflict_reasons:
        return "excluded", "excluded", "conflicting_qnames", notes
    if major_conflict or (set(conflict_reasons) & review_flags):
        return "weak", "review_required", None, ["Requires human review before rulebook replay."]
    if high_count and safe_count >= min_strong_support:
        return "strong", "active", None, notes
    if high_count == 1 and max(scores or [0]) >= 95 and _label_support(safe_observations):
        return "strong", "active", None, notes
    if high_count >= 1 or medium_count >= 2:
        return "usable", "active", None, notes
    if medium_count == 1:
        return "weak", "review_required", None, ["Only one medium-confidence observation."]
    return "excluded", "excluded", "insufficient_active_evidence", notes


def _rule_id(index: int, pattern: str, qname: str) -> str:
    stem = re.sub(r"[^a-z0-9]+", "-", f"{pattern}-{qname}".lower()).strip("-")
    return f"18B-R{index:04d}-{stem[:60]}"


def build_rulebook_entries(
    alignments: Sequence[Mapping[str, Any]],
    *,
    min_strong_support: int = 2,
    include_medium: bool = True,
    exclude_zero_only: bool = True,
    debug_label: str | None = None,
) -> list[dict[str, Any]]:
    filtered = [
        item
        for item in alignments
        if item.get("xbrl_qname") and item.get("confidence_bucket") in (ACTIVE_BUCKETS | UNSAFE_BUCKETS)
    ]
    if debug_label:
        wanted = normalize_label(debug_label)
        filtered = [item for item in filtered if wanted in normalize_label(item.get("pdf_label"))]

    label_statement_qnames: dict[tuple[str, str], set[str]] = defaultdict(set)
    label_qname_families: dict[tuple[str, str], set[str]] = defaultdict(set)
    qname_label_patterns: dict[str, set[str]] = defaultdict(set)
    grouped: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for item in filtered:
        key = _entry_key(item)
        if not key[0] or not key[2]:
            continue
        grouped[key].append(item)
        label_statement_qnames[_label_statement_key(item)].add(str(item.get("xbrl_qname")))
        label_qname_families[_label_qname_key(item)].add(str(item.get("pdf_statement_family") or "unknown"))
        qname_label_patterns[str(item.get("xbrl_qname"))].add(key[0])

    entries: list[dict[str, Any]] = []
    sorted_groups = sorted(grouped.items(), key=lambda pair: (pair[0][0], pair[0][1], pair[0][2]))
    for index, ((pattern, statement_family, qname), observations) in enumerate(sorted_groups, start=1):
        safe = _safe_observations(observations, include_medium=include_medium)
        stats_observations = safe or observations
        status_counts = _status_counts(observations)
        scores = _score_values(stats_observations)
        observed_labels = _unique_sorted([item.get("pdf_label") for item in observations])
        statement_types = _unique_sorted([item.get("pdf_statement_type") for item in observations])
        conflict_reasons, _exclusion_reasons, exclusion_reason = _entry_conflicts(
            pattern=pattern,
            statement_family=statement_family,
            target_qname=qname,
            observations=observations,
            safe_observations=safe,
            label_statement_qnames=label_statement_qnames,
            label_qname_families=label_qname_families,
            qname_label_patterns=qname_label_patterns,
            exclude_zero_only=exclude_zero_only,
        )
        tier, status, classification_exclusion, notes = _classify_entry(
            safe_observations=safe,
            status_counts=status_counts,
            scores=scores,
            conflict_reasons=conflict_reasons,
            exclusion_reason=exclusion_reason,
            min_strong_support=min_strong_support,
        )
        exclusion_reason = exclusion_reason or classification_exclusion
        aliases = sorted({variant for label in observed_labels for variant in _simple_alias_variants(label)})
        entries.append(
            {
                "rule_id": _rule_id(index, pattern, qname),
                "normalized_label_pattern": pattern,
                "observed_labels": observed_labels,
                "aliases": aliases,
                "target_qname": qname,
                "target_concept_label": _most_common([item.get("xbrl_label") for item in observations]),
                "statement_family": None if statement_family == "unknown" else statement_family,
                "statement_type_examples": statement_types,
                "period_type_hint": _most_common([_period_type(item) for item in stats_observations]),
                "context_hint": {
                    "pdf_value_roles": _unique_sorted([item.get("pdf_value_role") for item in stats_observations]),
                    "xbrl_context_examples": _unique_sorted([item.get("xbrl_context_id") for item in stats_observations])[:5],
                    "period_years": _unique_sorted([item.get("pdf_expected_year") for item in stats_observations]),
                },
                "sample_support_count": len({item.get("sample_id") for item in stats_observations if item.get("sample_id")}),
                "sample_ids": _unique_sorted([item.get("sample_id") for item in stats_observations]),
                "observation_count": len(stats_observations),
                "total_observation_count": len(observations),
                "high_confidence_count": status_counts.get("high", 0),
                "medium_confidence_count": status_counts.get("medium", 0),
                "ambiguous_observation_count": status_counts.get("ambiguous", 0),
                "low_confidence_count": status_counts.get("low", 0),
                "source_alignment_ids": [_source_alignment_id(item) for item in stats_observations],
                "score_min": min(scores) if scores else None,
                "score_max": max(scores) if scores else None,
                "score_avg": _mean(scores),
                "evidence_summary": {
                    "label_support": _label_support(safe),
                    "zero_value_count": sum(1 for item in stats_observations if _is_zero(item.get("pdf_value"))),
                    "nonzero_value_count": sum(1 for item in stats_observations if not _is_zero(item.get("pdf_value"))),
                    "match_reasons": sorted(
                        {
                            str(reason)
                            for item in stats_observations
                            for reason in (item.get("match_reasons") or [])
                            if reason
                        }
                    ),
                },
                "confidence_tier": tier,
                "rule_status": status,
                "exclusion_reason": exclusion_reason,
                "conflict_reasons": conflict_reasons,
                "competing_qnames": _competing_qnames(observations),
                "competing_label_patterns": sorted(qname_label_patterns.get(qname, set()) - {pattern})[:20],
                "notes": notes,
            }
        )
    return entries


def _alias_dictionary(entries: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    aliases: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        if entry.get("rule_status") == "excluded":
            continue
        for alias in entry.get("aliases") or []:
            aliases[str(alias)].append(
                {
                    "rule_id": entry.get("rule_id"),
                    "target_qname": entry.get("target_qname"),
                    "confidence_tier": entry.get("confidence_tier"),
                    "statement_family": entry.get("statement_family"),
                }
            )
    return dict(sorted(aliases.items()))


def _conflict_records(entries: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    conflicts = []
    for entry in entries:
        if not entry.get("conflict_reasons"):
            continue
        conflicts.append(
            {
                "rule_id": entry.get("rule_id"),
                "normalized_label_pattern": entry.get("normalized_label_pattern"),
                "target_qname": entry.get("target_qname"),
                "rule_status": entry.get("rule_status"),
                "confidence_tier": entry.get("confidence_tier"),
                "sample_support_count": entry.get("sample_support_count"),
                "observation_count": entry.get("observation_count"),
                "conflict_reasons": entry.get("conflict_reasons"),
                "competing_qnames": entry.get("competing_qnames"),
                "competing_label_patterns": entry.get("competing_label_patterns"),
                "exclusion_reason": entry.get("exclusion_reason"),
            }
        )
    return sorted(
        conflicts,
        key=lambda item: (
            0 if item.get("rule_status") == "excluded" else 1,
            -int(item.get("observation_count") or 0),
            str(item.get("normalized_label_pattern")),
        ),
    )


def _concept_coverage(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    active = [entry for entry in entries if entry.get("rule_status") == "active"]
    return {
        "active_concept_count": len({entry.get("target_qname") for entry in active if entry.get("target_qname")}),
        "candidate_concept_count": len({entry.get("target_qname") for entry in entries if entry.get("target_qname")}),
        "strong_concept_count": len(
            {
                entry.get("target_qname")
                for entry in active
                if entry.get("confidence_tier") == "strong" and entry.get("target_qname")
            }
        ),
    }


def _sample_support_summary(entries: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_sample: dict[str, Counter[str]] = defaultdict(Counter)
    for entry in entries:
        for sample_id in entry.get("sample_ids") or []:
            by_sample[str(sample_id)][str(entry.get("rule_status"))] += 1
            by_sample[str(sample_id)][str(entry.get("confidence_tier"))] += 1
    return [
        {
            "sample_id": sample_id,
            "active_rules": counts.get("active", 0),
            "review_required_rules": counts.get("review_required", 0),
            "excluded_rules": counts.get("excluded", 0),
            "strong_rules": counts.get("strong", 0),
            "usable_rules": counts.get("usable", 0),
        }
        for sample_id, counts in sorted(by_sample.items())
    ]


def _recommendation(summary: Mapping[str, Any]) -> dict[str, Any]:
    active = int(summary.get("active_strong_rules") or 0) + int(summary.get("active_usable_rules") or 0)
    justified = active >= 5
    return {
        "feature_18c_holdout_replay_justified": justified,
        "recommended_next_feature": (
            "Feature #18C - Replay rulebook on holdout sample and measure deterministic coverage/accuracy."
            if justified
            else "Review #18B rulebook exclusions before holdout replay."
        ),
        "basis": {
            "active_rule_count": active,
            "strong_rule_count": int(summary.get("active_strong_rules") or 0),
            "usable_rule_count": int(summary.get("active_usable_rules") or 0),
        },
    }


def build_rulebook_reports(
    *,
    alignment_report: Mapping[str, Any],
    summary_report: Mapping[str, Any] | None = None,
    ambiguous_report: Mapping[str, Any] | None = None,
    min_strong_support: int = 2,
    include_medium: bool = True,
    exclude_zero_only: bool = True,
    debug_label: str | None = None,
) -> dict[str, Any]:
    del summary_report, ambiguous_report
    alignments = alignment_report.get("alignments") or []
    entries = build_rulebook_entries(
        alignments,
        min_strong_support=min_strong_support,
        include_medium=include_medium,
        exclude_zero_only=exclude_zero_only,
        debug_label=debug_label,
    )
    active_strong = [entry for entry in entries if entry.get("rule_status") == "active" and entry.get("confidence_tier") == "strong"]
    active_usable = [entry for entry in entries if entry.get("rule_status") == "active" and entry.get("confidence_tier") == "usable"]
    review_required = [entry for entry in entries if entry.get("rule_status") == "review_required"]
    excluded = [entry for entry in entries if entry.get("rule_status") == "excluded"]
    conflicts = _conflict_records(entries)
    summary = {
        "feature": "18B",
        "generated_at": _utc_now(),
        "candidate_pattern_count": len(entries),
        "active_strong_rules": len(active_strong),
        "active_usable_rules": len(active_usable),
        "review_required_rules": len(review_required),
        "excluded_rules": len(excluded),
        "zero_only_exclusions": sum(1 for entry in excluded if "zero_only_evidence" in (entry.get("conflict_reasons") or [])),
        "generic_label_exclusions": sum(
            1
            for entry in excluded
            if "generic_label_without_statement_context" in (entry.get("conflict_reasons") or [])
        ),
        "statement_family_conflicts": sum(1 for entry in entries if "statement_family_conflict" in (entry.get("conflict_reasons") or [])),
        "concept_coverage_summary": _concept_coverage(entries),
        "sample_support_summary": _sample_support_summary(entries),
        "top_strong_rules": sorted(active_strong, key=lambda item: (-int(item.get("observation_count") or 0), str(item.get("normalized_label_pattern"))))[:20],
        "top_usable_rules": sorted(active_usable, key=lambda item: (-int(item.get("observation_count") or 0), str(item.get("normalized_label_pattern"))))[:20],
        "top_conflicts": conflicts[:20],
        "safety": {
            "external_llm_called": False,
            "external_provider_called": False,
            "azure_di_live_call_made": False,
            "database_mutated": False,
            "production_behavior_changed": False,
            "api_changed": False,
            "ui_changed": False,
            "xbrl_generated": False,
            "arelle_run": False,
        },
    }
    summary["recommendation"] = _recommendation(summary)
    run_metadata = {
        "feature": "18B",
        "generated_at": summary["generated_at"],
        "read_only": True,
        "offline_only": True,
        **summary["safety"],
    }
    return {
        "rulebook": {
            "run_metadata": run_metadata,
            "summary": summary,
            "alias_dictionary": _alias_dictionary(entries),
            "rules": entries,
        },
        "summary": {
            "run_metadata": run_metadata,
            "summary": summary,
        },
        "conflicts": {
            "run_metadata": run_metadata,
            "summary": {
                "conflict_count": len(conflicts),
                "top_conflicts": conflicts[:20],
            },
            "conflicts": conflicts,
        },
        "excluded": {
            "run_metadata": run_metadata,
            "summary": {
                "excluded_rule_count": len(excluded),
                "zero_only_exclusions": summary["zero_only_exclusions"],
                "generic_label_exclusions": summary["generic_label_exclusions"],
            },
            "excluded_rules": excluded,
        },
    }


def render_rulebook_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# PDF-XBRL Mapping Rulebook - Feature #18B",
        "",
        f"- Candidate patterns: {summary.get('candidate_pattern_count', 0)}",
        f"- Strong active rules: {summary.get('active_strong_rules', 0)}",
        f"- Usable active rules: {summary.get('active_usable_rules', 0)}",
        f"- Review-required rules: {summary.get('review_required_rules', 0)}",
        f"- Excluded rules: {summary.get('excluded_rules', 0)}",
        "",
        "## Top Strong Rules",
        "",
        "| Pattern | Target qname | Observations | Samples |",
        "| --- | --- | ---: | ---: |",
    ]
    for entry in summary.get("top_strong_rules") or []:
        lines.append(
            f"| {entry.get('normalized_label_pattern')} | {entry.get('target_qname')} | "
            f"{entry.get('observation_count')} | {entry.get('sample_support_count')} |"
        )
    lines.extend(["", "## Top Usable Rules", "", "| Pattern | Target qname | Observations | Samples |", "| --- | --- | ---: | ---: |"])
    for entry in summary.get("top_usable_rules") or []:
        lines.append(
            f"| {entry.get('normalized_label_pattern')} | {entry.get('target_qname')} | "
            f"{entry.get('observation_count')} | {entry.get('sample_support_count')} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_summary_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    recommendation = summary.get("recommendation") or {}
    lines = ["# PDF-XBRL Mapping Rulebook Summary - Feature #18B", "", "## Metrics", ""]
    for key in (
        "candidate_pattern_count",
        "active_strong_rules",
        "active_usable_rules",
        "review_required_rules",
        "excluded_rules",
        "zero_only_exclusions",
        "generic_label_exclusions",
        "statement_family_conflicts",
    ):
        lines.append(f"- {key}: {summary.get(key, 0)}")
    coverage = summary.get("concept_coverage_summary") or {}
    lines.extend(
        [
            "",
            "## Concept Coverage",
            "",
            f"- Active concepts: {coverage.get('active_concept_count', 0)}",
            f"- Candidate concepts: {coverage.get('candidate_concept_count', 0)}",
            f"- Strong concepts: {coverage.get('strong_concept_count', 0)}",
            "",
            "## Recommendation",
            "",
            f"- #18C justified: {recommendation.get('feature_18c_holdout_replay_justified')}",
            f"- Next: {recommendation.get('recommended_next_feature')}",
            "",
            "## Safety",
            "",
        ]
    )
    for key, value in (summary.get("safety") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    return "\n".join(lines)


def render_conflicts_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# PDF-XBRL Mapping Rulebook Conflicts - Feature #18B",
        "",
        f"- Conflict records: {(report.get('summary') or {}).get('conflict_count', 0)}",
        "",
        "| Pattern | Target qname | Status | Reasons |",
        "| --- | --- | --- | --- |",
    ]
    for item in (report.get("summary") or {}).get("top_conflicts") or []:
        lines.append(
            f"| {item.get('normalized_label_pattern')} | {item.get('target_qname')} | "
            f"{item.get('rule_status')} | {', '.join(item.get('conflict_reasons') or [])} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_excluded_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# PDF-XBRL Mapping Rulebook Exclusions - Feature #18B",
        "",
        f"- Excluded rules: {(report.get('summary') or {}).get('excluded_rule_count', 0)}",
        f"- Zero-only exclusions: {(report.get('summary') or {}).get('zero_only_exclusions', 0)}",
        f"- Generic-label exclusions: {(report.get('summary') or {}).get('generic_label_exclusions', 0)}",
        "",
        "| Pattern | Target qname | Reason |",
        "| --- | --- | --- |",
    ]
    for item in (report.get("excluded_rules") or [])[:30]:
        lines.append(
            f"| {item.get('normalized_label_pattern')} | {item.get('target_qname')} | {item.get('exclusion_reason')} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_rulebook_reports(
    *,
    alignment_report_path: str | Path,
    output_dir: str | Path,
    summary_report_path: str | Path | None = None,
    ambiguous_report_path: str | Path | None = None,
    min_strong_support: int = 2,
    include_medium: bool = True,
    exclude_zero_only: bool = True,
    debug_label: str | None = None,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    reports = build_rulebook_reports(
        alignment_report=_read_json(alignment_report_path),
        summary_report=_read_json(summary_report_path),
        ambiguous_report=_read_json(ambiguous_report_path),
        min_strong_support=min_strong_support,
        include_medium=include_medium,
        exclude_zero_only=exclude_zero_only,
        debug_label=debug_label,
    )
    paths = {
        "rulebook_json": output / "pdf_xbrl_mapping_rulebook_18b.json",
        "rulebook_md": output / "pdf_xbrl_mapping_rulebook_18b.md",
        "summary_json": output / "pdf_xbrl_mapping_rulebook_summary_18b.json",
        "summary_md": output / "pdf_xbrl_mapping_rulebook_summary_18b.md",
        "conflicts_json": output / "pdf_xbrl_mapping_rulebook_conflicts_18b.json",
        "conflicts_md": output / "pdf_xbrl_mapping_rulebook_conflicts_18b.md",
        "excluded_json": output / "pdf_xbrl_mapping_rulebook_excluded_18b.json",
        "excluded_md": output / "pdf_xbrl_mapping_rulebook_excluded_18b.md",
    }
    for path, payload in (
        (paths["rulebook_json"], reports["rulebook"]),
        (paths["summary_json"], reports["summary"]),
        (paths["conflicts_json"], reports["conflicts"]),
        (paths["excluded_json"], reports["excluded"]),
    ):
        path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    paths["rulebook_md"].write_text(render_rulebook_markdown(reports["rulebook"]), encoding="utf-8")
    paths["summary_md"].write_text(render_summary_markdown(reports["summary"]), encoding="utf-8")
    paths["conflicts_md"].write_text(render_conflicts_markdown(reports["conflicts"]), encoding="utf-8")
    paths["excluded_md"].write_text(render_excluded_markdown(reports["excluded"]), encoding="utf-8")
    return {"paths": paths, **reports}
