"""Company-format template memory for Feature #18E-B-3.

The memory is intentionally conservative: it produces review-only candidate
evidence from repeated local patterns, never confirmed mappings.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from services.pdf_xbrl_deterministic_alignment import canonical_label, clean_text, concept_label, normalize_label
from services.pdf_note_detail_boundaries import boundary_blocks_qname


SAFETY = {
    "external_llm_called": False,
    "external_provider_called": False,
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

FORMAT_MEMORY_ALLOWED_QNAMES = {
    "ifrs-smes:Assets",
    "ifrs-smes:CashAndCashEquivalents",
    "ifrs-smes:CashFlowsFromUsedInFinancingActivities",
    "ifrs-smes:CashFlowsFromUsedInInvestingActivities",
    "ifrs-smes:CashFlowsFromUsedInOperatingActivities",
    "ifrs-smes:CurrentAssets",
    "ifrs-smes:CurrentLiabilities",
    "ifrs-smes:Equity",
    "ifrs-smes:EquityAndLiabilities",
    "ifrs-smes:IncreaseDecreaseInCashAndCashEquivalents",
    "ifrs-smes:IssuedCapital",
    "ifrs-smes:Liabilities",
    "ifrs-smes:NoncurrentAssets",
    "ifrs-smes:NoncurrentLiabilities",
    "ifrs-smes:OtherIncome",
    "ifrs-smes:ProfitLoss",
    "ifrs-smes:PropertyPlantAndEquipment",
    "ifrs-smes:RetainedEarnings",
}

DISABLED_LABEL_TERMS = {
    "payable",
    "payables",
    "receivable",
    "receivables",
    "tax",
    "taxation",
    "borrow",
    "borrowings",
    "loan",
    "loans",
    "deferred tax",
}

GENERIC_LABELS = {"amount", "balance", "current", "less", "net", "other", "subtotal", "total"}
GOOD_STATUSES = {"exact_qname_value_period_match", "qname_value_match_period_uncertain"}

STRUCTURAL_ALIAS_PATTERNS: tuple[dict[str, Any], ...] = (
    {
        "memory_entry_id": "18E-B3-format-cf-cash-equivalent-beginning",
        "statement_family": "cash_flow",
        "section_blocks": ["cash_flow_reconciliation", "cash_flow_other"],
        "row_roles": ["component"],
        "labels": [
            "cash and cash equivalent at beginning of the year",
            "cash and cash equivalent at beginning of year",
        ],
        "preferred_qname": "ifrs-smes:CashAndCashEquivalents",
        "canonical_position": "cash_flow_cash_equivalent_beginning",
        "evidence_qname": "ifrs-smes:CashAndCashEquivalents",
    },
    {
        "memory_entry_id": "18E-B3-format-cf-cash-equivalent-ending",
        "statement_family": "cash_flow",
        "section_blocks": ["cash_flow_reconciliation", "cash_flow_other"],
        "row_roles": ["component"],
        "labels": [
            "cash and cash equivalent at the end of the year",
            "cash and cash equivalent at end of year",
        ],
        "preferred_qname": "ifrs-smes:CashAndCashEquivalents",
        "canonical_position": "cash_flow_cash_equivalent_ending",
        "evidence_qname": "ifrs-smes:CashAndCashEquivalents",
    },
    {
        "memory_entry_id": "18E-B3-format-cf-net-change-cash-equivalent",
        "statement_family": "cash_flow",
        "section_blocks": ["cash_flow_reconciliation", "cash_flow_other"],
        "row_roles": ["subtotal", "total"],
        "labels": [
            "net increase in cash and cash equivalent",
            "net decrease in cash and cash equivalent",
            "net increase decrease in cash and cash equivalent",
            "net decrease increase in cash and cash equivalent",
        ],
        "preferred_qname": "ifrs-smes:IncreaseDecreaseInCashAndCashEquivalents",
        "canonical_position": "cash_flow_net_change_cash_equivalent",
        "evidence_qname": "ifrs-smes:IncreaseDecreaseInCashAndCashEquivalents",
    },
    {
        "memory_entry_id": "18E-B3-format-sfp-total-deferred-liabilities",
        "statement_family": "financial_position",
        "section_blocks": ["non_current_liabilities"],
        "row_roles": ["total", "subtotal"],
        "labels": ["total deferred liabilities"],
        "preferred_qname": "ifrs-smes:NoncurrentLiabilities",
        "canonical_position": "sfp_total_noncurrent_liabilities",
        "evidence_qname": "ifrs-smes:NoncurrentLiabilities",
    },
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _unique(values: Sequence[Any]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if value not in (None, "")))


def _context(record_or_context: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not record_or_context:
        return {}
    row_context = record_or_context.get("row_context")
    if isinstance(row_context, Mapping):
        return row_context
    return record_or_context


def _context_label(context: Mapping[str, Any]) -> str:
    return canonical_label(context.get("normalized_label") or context.get("original_label") or context.get("pdf_label"))


def _raw_label(context: Mapping[str, Any]) -> str:
    return normalize_label(context.get("original_label") or context.get("pdf_label") or context.get("normalized_label"))


def _is_main_context(context: Mapping[str, Any]) -> bool:
    return bool(context.get("is_main_statement")) and not bool(context.get("is_notes_context"))


def _context_confidence(context: Mapping[str, Any]) -> float:
    try:
        return float(context.get("context_confidence") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _label_disabled(label: str) -> bool:
    return any(term in label for term in DISABLED_LABEL_TERMS)


def _is_good_status(status: Any) -> bool:
    return str(status or "") in GOOD_STATUSES


def _entry_key(record: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    context = _context(record)
    return (
        str(context.get("statement_family") or ""),
        str(context.get("section_block") or ""),
        str(context.get("row_role") or ""),
        canonical_label(record.get("normalized_label") or record.get("pdf_label") or context.get("normalized_label")),
        str(record.get("predicted_qname") or ""),
    )


def _confidence_tier(sample_support_count: int, observation_count: int) -> str:
    if sample_support_count >= 3 and observation_count >= 4:
        return "format_memory_strong"
    if sample_support_count >= 2 and observation_count >= 2:
        return "format_memory_usable"
    return "format_memory_review_required"


def _entry_from_group(
    key: tuple[str, str, str, str, str],
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    family, section, row_role, label, qname = key
    sample_ids = sorted({str(row.get("sample_id") or "") for row in rows if row.get("sample_id")})
    observed_labels = Counter(str(row.get("pdf_label") or row.get("normalized_label") or label) for row in rows)
    status_counts = Counter(str(row.get("evaluation_status") or "") for row in rows)
    memory_id_label = "-".join(label.split())[:48] or qname.split(":")[-1].lower()
    return {
        "memory_entry_id": f"18E-B3-format-{family or 'unknown'}-{memory_id_label}-{qname.split(':')[-1].lower()}",
        "statement_family": family,
        "section_block": section,
        "canonical_position": f"{family}:{section}:{row_role}:{label}",
        "normalized_label_pattern": label,
        "label_aliases": [label],
        "observed_labels": [{"label": key, "count": count} for key, count in observed_labels.most_common(10)],
        "sample_support_count": len(sample_ids),
        "sample_ids": sample_ids,
        "expected_row_role": row_role,
        "expected_qname_candidates": [qname],
        "preferred_qname": qname,
        "preferred_concept_label": concept_label(qname),
        "required_context_conditions": {
            "statement_family": family,
            "section_block": section,
            "row_role": row_role,
            "is_main_statement": True,
            "is_notes_context": False,
        },
        "blocking_conditions": ["format_memory_candidate_requires_review"],
        "source_evidence": {
            "exact_match_evidence": status_counts.get("exact_qname_value_period_match", 0),
            "period_uncertain_match_evidence": status_counts.get("qname_value_match_period_uncertain", 0),
            "previous_template_evidence": sum(1 for row in rows if row.get("matched_template_pattern_id")),
            "row_order_evidence": sum(1 for row in rows if row.get("row_order_alignment_id")),
        },
        "confidence_tier": _confidence_tier(len(sample_ids), len(rows)),
        "false_positive_risk_notes": [],
        "safe_for_auto_apply": False,
        "requires_human_review": True,
    }


def _evidence_qname_counts(records: Sequence[Mapping[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for record in records:
        if record.get("predicted_qname") and _is_good_status(record.get("evaluation_status")):
            counts[str(record.get("predicted_qname"))] += 1
    return counts


def _alias_entry_from_pattern(pattern: Mapping[str, Any], evidence_counts: Counter[str]) -> dict[str, Any] | None:
    qname = str(pattern.get("preferred_qname") or "")
    evidence_qname = str(pattern.get("evidence_qname") or qname)
    if not qname or evidence_counts.get(evidence_qname, 0) < 2:
        return None
    labels = [canonical_label(label) for label in pattern.get("labels") or [] if canonical_label(label)]
    family = str(pattern.get("statement_family") or "")
    section_blocks = [str(item) for item in pattern.get("section_blocks") or []]
    row_roles = [str(item) for item in pattern.get("row_roles") or []]
    return {
        "memory_entry_id": pattern.get("memory_entry_id"),
        "statement_family": family,
        "section_block": section_blocks[0] if section_blocks else "",
        "section_blocks": section_blocks,
        "canonical_position": pattern.get("canonical_position"),
        "normalized_label_pattern": labels[0] if labels else "",
        "label_aliases": labels,
        "observed_labels": [{"label": label, "count": 0} for label in labels],
        "sample_support_count": 0,
        "sample_ids": [],
        "expected_row_role": row_roles[0] if row_roles else "",
        "row_roles": row_roles,
        "expected_qname_candidates": [qname],
        "preferred_qname": qname,
        "preferred_concept_label": concept_label(qname),
        "required_context_conditions": {
            "statement_family": family,
            "section_blocks": section_blocks,
            "row_roles": row_roles,
            "is_main_statement": True,
            "is_notes_context": False,
        },
        "blocking_conditions": ["format_memory_candidate_requires_review"],
        "source_evidence": {
            "exact_match_evidence": evidence_counts.get(evidence_qname, 0),
            "period_uncertain_match_evidence": 0,
            "previous_template_evidence": evidence_counts.get(evidence_qname, 0),
            "row_order_evidence": 0,
            "structural_alias_evidence": True,
        },
        "confidence_tier": "format_memory_review_required",
        "false_positive_risk_notes": ["structural_alias_requires_label_and_context_agreement"],
        "safe_for_auto_apply": False,
        "requires_human_review": True,
    }


def build_company_format_template_memory(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Build conservative memory entries from locally good evaluated mapper rows."""
    grouped: dict[tuple[str, str, str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        context = _context(record)
        label = canonical_label(record.get("normalized_label") or record.get("pdf_label") or context.get("normalized_label"))
        qname = str(record.get("predicted_qname") or "")
        if not qname or qname not in FORMAT_MEMORY_ALLOWED_QNAMES:
            continue
        if not _is_good_status(record.get("evaluation_status")):
            continue
        if not _is_main_context(context):
            continue
        if _label_disabled(label):
            continue
        key = _entry_key(record)
        grouped[key].append(record)

    entries = [
        _entry_from_group(key, rows)
        for key, rows in grouped.items()
        if len({str(row.get("sample_id") or "") for row in rows}) >= 2 and len(rows) >= 2
    ]
    evidence_counts = _evidence_qname_counts(records)
    for pattern in STRUCTURAL_ALIAS_PATTERNS:
        entry = _alias_entry_from_pattern(pattern, evidence_counts)
        if entry:
            entries.append(entry)
    entries.sort(key=lambda item: str(item.get("memory_entry_id") or ""))
    return entries


def _entry_sections(entry: Mapping[str, Any]) -> set[str]:
    sections = set(str(item) for item in entry.get("section_blocks") or [] if str(item))
    if entry.get("section_block"):
        sections.add(str(entry.get("section_block")))
    return sections


def _entry_roles(entry: Mapping[str, Any]) -> set[str]:
    roles = set(str(item) for item in entry.get("row_roles") or [] if str(item))
    if entry.get("expected_row_role"):
        roles.add(str(entry.get("expected_row_role")))
    return roles


def _labels_match(label: str, raw_label: str, entry: Mapping[str, Any]) -> bool:
    aliases = {canonical_label(alias) for alias in entry.get("label_aliases") or [] if canonical_label(alias)}
    aliases.add(canonical_label(entry.get("normalized_label_pattern")))
    aliases.discard("")
    if label in aliases or raw_label in aliases:
        return True
    label_singular = label.replace("equivalents", "equivalent")
    raw_singular = raw_label.replace("equivalents", "equivalent")
    return any(alias.replace("equivalents", "equivalent") in {label_singular, raw_singular} for alias in aliases)


def match_company_format_memory_candidate(
    context: Mapping[str, Any] | None,
    memory_entries: Sequence[Mapping[str, Any]],
    *,
    note_boundary: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not context:
        return None
    label = _context_label(context)
    raw_label = _raw_label(context)
    if not label or label in GENERIC_LABELS or _label_disabled(label):
        return None
    if not _is_main_context(context) or _context_confidence(context) < 0.75:
        return None

    matches = []
    for entry in memory_entries:
        qname = str(entry.get("preferred_qname") or "")
        if not qname or qname not in FORMAT_MEMORY_ALLOWED_QNAMES:
            continue
        if str(entry.get("statement_family") or "") != str(context.get("statement_family") or ""):
            continue
        sections = _entry_sections(entry)
        if sections and str(context.get("section_block") or "") not in sections:
            continue
        roles = _entry_roles(entry)
        if roles and str(context.get("row_role") or "") not in roles:
            continue
        if not _labels_match(label, raw_label, entry):
            continue
        blocked, boundary_reasons = boundary_blocks_qname(note_boundary, qname)
        confidence = min(0.64, max(0.5, _context_confidence(context) - 0.2))
        matches.append(
            {
                "matched_rule_id": entry.get("memory_entry_id"),
                "memory_entry_id": entry.get("memory_entry_id"),
                "target_qname": qname,
                "target_concept_label": entry.get("preferred_concept_label") or concept_label(qname),
                "confidence_score": round(confidence, 4),
                "confidence_bucket": "no_match" if blocked else "review_required",
                "candidate_source": "company_format_template_memory",
                "candidate_blocked": blocked,
                "match_reasons": _unique(
                    [
                        "company_format_template_memory_match",
                        f"statement_family:{context.get('statement_family')}",
                        f"section_block:{context.get('section_block')}",
                        f"row_role:{context.get('row_role')}",
                        f"memory_entry:{entry.get('memory_entry_id')}",
                    ]
                ),
                "blocking_reasons": _unique(
                    [
                        "format_memory_candidate_requires_review",
                        *boundary_reasons,
                        *(entry.get("blocking_conditions") or []),
                    ]
                ),
                "format_memory_entry": {
                    "memory_entry_id": entry.get("memory_entry_id"),
                    "statement_family": entry.get("statement_family"),
                    "section_block": entry.get("section_block"),
                    "canonical_position": entry.get("canonical_position"),
                    "normalized_label_pattern": entry.get("normalized_label_pattern"),
                    "preferred_qname": qname,
                    "confidence_tier": entry.get("confidence_tier"),
                    "source_evidence": entry.get("source_evidence") or {},
                },
            }
        )
    if not matches:
        return None
    matches.sort(key=lambda item: (bool(item.get("candidate_blocked")), -float(item.get("confidence_score") or 0), str(item.get("memory_entry_id"))))
    return matches[0]


def summarize_company_format_template_memory(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_family = Counter(str(item.get("statement_family") or "unknown") for item in entries)
    by_qname = Counter(str(item.get("preferred_qname") or "") for item in entries)
    by_tier = Counter(str(item.get("confidence_tier") or "unknown") for item in entries)
    return {
        "feature": "18E-B-3",
        "memory_entry_count": len(entries),
        "entry_count_by_statement_family": dict(sorted(by_family.items())),
        "entry_count_by_qname": dict(sorted(by_qname.items())),
        "entry_count_by_confidence_tier": dict(sorted(by_tier.items())),
        "safe_for_auto_apply_count": 0,
        "requires_human_review_count": len(entries),
        "safety": SAFETY,
    }


def build_company_format_template_memory_report(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    entries = build_company_format_template_memory(records)
    return {
        "run_metadata": {
            "feature": "18E-B-3",
            "generated_at": utc_now(),
            "read_only": True,
            "offline_only": True,
            **SAFETY,
        },
        "summary": summarize_company_format_template_memory(entries),
        "format_memory_entries": entries,
    }


def render_company_format_template_memory_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Company Format Template Memory - Feature #18E-B-3",
        "",
        f"- Memory entries: {summary.get('memory_entry_count', 0)}",
        f"- Safe for auto-apply: {summary.get('safe_for_auto_apply_count', 0)}",
        "",
        "## Entry Counts by QName",
        "",
        "| QName | Count |",
        "| --- | ---: |",
    ]
    for qname, count in (summary.get("entry_count_by_qname") or {}).items():
        lines.append(f"| {clean_text(qname)} | {count} |")
    lines.extend(["", "## Entries", "", "| Entry | Family | Label | QName | Tier |", "| --- | --- | --- | --- | --- |"])
    for entry in report.get("format_memory_entries") or []:
        lines.append(
            f"| {clean_text(entry.get('memory_entry_id'))} | {entry.get('statement_family')} | "
            f"{clean_text(entry.get('normalized_label_pattern'))} | {entry.get('preferred_qname')} | {entry.get('confidence_tier')} |"
        )
    lines.append("")
    return "\n".join(lines)
