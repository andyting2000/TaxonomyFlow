"""Report-only reviewed mapping decision simulation for Azure DI candidates."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


DEFAULT_REVIEW_QUEUE = Path("reports/azure_di_manual_mapping_review_queue_14b.json")
DEFAULT_REVIEW_POLICY = Path("reports/azure_di_mapping_review_policy_14b.json")
DEFAULT_HANDOFF_CONTRACT = Path("reports/azure_di_mapping_review_handoff_contract_14b.json")
DEFAULT_OUTPUT_DIR = Path("reports")

NUMERIC_ROW_TYPES = {"numeric_fact", "comparative_numeric_fact", "subtotal_or_total"}
APPROVAL_DECISION = "approve_suggested_concept_simulated"
DEFER_DECISION = "defer_mapping"


@dataclass(frozen=True)
class SimulationPolicy:
    approve_ready_only: bool = True
    simulate_confirm_medium: bool = False
    simulate_choose_top_ambiguous: bool = False
    strict: bool = True


@dataclass(frozen=True)
class SimulationOutputPaths:
    decisions_json: Path
    decisions_md: Path
    handoff_json: Path
    handoff_md: Path
    eligibility_json: Path
    eligibility_md: Path
    policy_json: Path
    policy_md: Path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def no_side_effect_metadata() -> dict[str, Any]:
    return {
        "feature": "14C",
        "generated_at": utc_now_iso(),
        "read_only": True,
        "database_mutated": False,
        "db_schema_changed": False,
        "migration_created": False,
        "api_routes_implemented": False,
        "frontend_code_modified": False,
        "production_behavior_changed": False,
        "production_extraction_behavior_changed": False,
        "production_mapping_behavior_changed": False,
        "final_mapping_approved": False,
        "real_human_approval_recorded": False,
        "production_mapping_approval_produced": False,
        "semantic_matcher_called": False,
        "production_semantic_matcher_called": False,
        "embeddings_used": False,
        "xbrl_generated": False,
        "automatic_xbrl_generation": False,
        "arelle_validation_run": False,
        "azure_di_live_call_made": False,
        "live_huggingface_calls_made": False,
        "live_openai_calls_made": False,
        "external_provider_calls": False,
        "reference_xml_sent_to_model": False,
        "reference_xml_sent_to_provider": False,
    }


def output_paths_from_prefix(output_prefix: str | Path | None = None) -> SimulationOutputPaths:
    if output_prefix is None:
        root = DEFAULT_OUTPUT_DIR
        return SimulationOutputPaths(
            decisions_json=root / "azure_di_reviewed_mapping_decisions_14c.json",
            decisions_md=root / "azure_di_reviewed_mapping_decisions_14c.md",
            handoff_json=root / "azure_di_reviewed_mapping_handoff_14c.json",
            handoff_md=root / "azure_di_reviewed_mapping_handoff_14c.md",
            eligibility_json=root / "azure_di_xbrl_eligibility_summary_14c.json",
            eligibility_md=root / "azure_di_xbrl_eligibility_summary_14c.md",
            policy_json=root / "azure_di_review_simulation_policy_14c.json",
            policy_md=root / "azure_di_review_simulation_policy_14c.md",
        )
    prefix = Path(output_prefix)
    return SimulationOutputPaths(
        decisions_json=Path(f"{prefix}_reviewed_mapping_decisions_14c.json"),
        decisions_md=Path(f"{prefix}_reviewed_mapping_decisions_14c.md"),
        handoff_json=Path(f"{prefix}_reviewed_mapping_handoff_14c.json"),
        handoff_md=Path(f"{prefix}_reviewed_mapping_handoff_14c.md"),
        eligibility_json=Path(f"{prefix}_xbrl_eligibility_summary_14c.json"),
        eligibility_md=Path(f"{prefix}_xbrl_eligibility_summary_14c.md"),
        policy_json=Path(f"{prefix}_review_simulation_policy_14c.json"),
        policy_md=Path(f"{prefix}_review_simulation_policy_14c.md"),
    )


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def _top_suggestion(item: Mapping[str, Any]) -> dict[str, Any] | None:
    suggestion = item.get("top_suggestion")
    return dict(suggestion) if isinstance(suggestion, Mapping) and suggestion else None


def _score(item: Mapping[str, Any]) -> float:
    try:
        return float(item.get("score") or (_top_suggestion(item) or {}).get("score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _confidence_tier(item: Mapping[str, Any]) -> str:
    return str(item.get("confidence_tier") or (_top_suggestion(item) or {}).get("confidence_tier") or "none")


def _major_blockers(item: Mapping[str, Any]) -> list[str]:
    blockers = [str(blocker) for blocker in item.get("blockers") or []]
    blockers.extend(str(reason) for reason in item.get("review_reasons") or [] if "concept_type_mismatch" in str(reason))
    return sorted(set(blockers))


def _has_type_mismatch(item: Mapping[str, Any]) -> bool:
    top = _top_suggestion(item) or {}
    evidence = top.get("evidence") or {}
    if evidence.get("concept_type_match") is False or evidence.get("row_type_match") is False:
        return True
    row_type = str(item.get("row_type") or "")
    if row_type in NUMERIC_ROW_TYPES and top.get("is_text_block_concept") is True:
        return True
    if row_type == "text_block" and top.get("is_numeric_concept") is True:
        return True
    return any("concept_type_mismatch" in blocker or "row_type_or_concept_type_mismatch" in blocker for blocker in _major_blockers(item))


def _can_simulate_ready_approval(item: Mapping[str, Any], policy: SimulationPolicy) -> tuple[bool, list[str]]:
    top = _top_suggestion(item)
    tier = _confidence_tier(item)
    row_type = str(item.get("row_type") or "")
    blockers: list[str] = []
    if not top:
        blockers.append("missing_top_suggestion")
    if tier not in {"high", "medium"}:
        blockers.append("confidence_below_medium")
    if tier == "medium" and _score(item) < 0.70:
        blockers.append("medium_score_below_ready_threshold")
    if _has_type_mismatch(item):
        blockers.append("concept_type_mismatch")
    if policy.strict and row_type in NUMERIC_ROW_TYPES and tier == "low":
        blockers.append("strict_mode_blocks_low_confidence_numeric")
    blockers.extend(_major_blockers(item))
    return not blockers, sorted(set(blockers))


def _decision_for_item(item: Mapping[str, Any], policy: SimulationPolicy) -> tuple[str, bool, dict[str, Any] | None, str, list[str]]:
    workflow = str(item.get("workflow_status") or "")
    tier = _confidence_tier(item)
    top = _top_suggestion(item)

    if workflow == "ready_for_review_approval":
        allowed, blockers = _can_simulate_ready_approval(item, policy)
        if allowed and (policy.approve_ready_only or not policy.strict):
            return APPROVAL_DECISION, True, top, "Ready item has a compatible high/strong-medium suggestion.", []
        return DEFER_DECISION, False, None, "Ready item was deferred by conservative simulation policy.", blockers

    if workflow == "needs_confirmation":
        blockers = []
        if not policy.simulate_confirm_medium:
            blockers.append("simulate_confirm_medium_not_enabled")
        if tier not in {"high", "medium"}:
            blockers.append("confirmation_candidate_below_medium_confidence")
        if not top:
            blockers.append("missing_top_suggestion")
        if _has_type_mismatch(item):
            blockers.append("concept_type_mismatch")
        if not blockers:
            return APPROVAL_DECISION, True, top, "Confirmation-required item was simulated as approved because medium confirmation simulation is enabled.", []
        return DEFER_DECISION, False, None, "Confirmation-required item remains deferred by default.", sorted(set(blockers))

    if workflow == "needs_human_concept_choice":
        if policy.simulate_choose_top_ambiguous and top and not _has_type_mismatch(item):
            return APPROVAL_DECISION, True, top, "Ambiguous item used explicit simulation flag to choose the top suggestion.", [
                "ambiguous_choice_simulated_not_human_reviewed"
            ]
        return "require_manual_taxonomy_mapping", False, None, "Ambiguous item needs human concept choice; no automatic winner selected.", [
            "ambiguous_multiple_suggestions"
        ]

    if workflow == "needs_alias_or_metadata_enrichment":
        blockers = [str(blocker) for blocker in item.get("blockers") or []]
        if any("metadata" in blocker for blocker in blockers):
            return "request_concept_metadata_enrichment", False, None, "Concept metadata enrichment is required before mapping.", [
                "concept_metadata_enrichment_needed"
            ]
        return "request_alias_enrichment", False, None, "Alias enrichment is required before mapping.", ["alias_enrichment_needed"]

    if workflow == "blocked_from_xbrl":
        return "blocked_from_xbrl", False, None, "Item remains blocked from XBRL eligibility.", _major_blockers(item) or ["blocked_from_xbrl"]

    if workflow == "context_only":
        return "keep_for_context_only", False, None, "Item is retained only as context.", ["context_only_not_mapped_fact"]

    return "no_decision_simulated", False, None, "No supported workflow status matched.", ["unsupported_workflow_status"]


def build_simulated_decisions_report(
    *,
    review_queue: Mapping[str, Any],
    review_policy: Mapping[str, Any],
    handoff_contract: Mapping[str, Any],
    run_id: str | None,
    input_paths: Mapping[str, Any],
    simulation_policy: SimulationPolicy,
) -> dict[str, Any]:
    decisions: list[dict[str, Any]] = []
    for index, item in enumerate(review_queue.get("queue_items") or [], start=1):
        decision_type, eligible, selected, reason, blockers = _decision_for_item(item, simulation_policy)
        decision = {
            "simulated_decision_id": f"14C-SIM-{index:04d}",
            "review_mapping_item_id": item.get("review_mapping_item_id"),
            "mapping_input_id": item.get("mapping_input_id"),
            "source_candidate_id": item.get("source_candidate_id"),
            "case_id": item.get("case_id"),
            "row_type": item.get("row_type"),
            "workflow_status": item.get("workflow_status"),
            "priority": item.get("priority"),
            "original_mapping_status": item.get("mapping_status"),
            "original_confidence_tier": _confidence_tier(item),
            "original_requires_confirmation": bool(item.get("requires_confirmation")),
            "selected_suggestion": selected,
            "selected_concept_qname": (selected or {}).get("concept_qname"),
            "selected_concept_label": (selected or {}).get("concept_label"),
            "decision_type": decision_type,
            "decision_reason": reason,
            "simulated_only": True,
            "human_approved": False,
            "xbrl_eligible": bool(eligible),
            "xbrl_blockers": [] if eligible else blockers,
            "requires_confirmation": bool(item.get("requires_confirmation")),
            "reviewer_notes": "Generated by #14C deterministic simulation; not a human review decision.",
            "audit_trail": {
                "source": "14C_report_based_reviewed_mapping_simulator",
                "source_review_mapping_item_id": item.get("review_mapping_item_id"),
                "source_mapping_input_id": item.get("mapping_input_id"),
                "source_candidate_id": item.get("source_candidate_id"),
                "source_14b_audit_trail": item.get("audit_trail") or {},
                "simulated_only": True,
                "human_approved": False,
                "production_mapping_approved": False,
            },
            "source_evidence": item.get("source_evidence") or {},
            "provenance": item.get("provenance") or {},
            "warnings": sorted(
                set(
                    [
                        "simulated_decision_not_human_approval",
                        *[str(warning) for warning in item.get("warnings") or []],
                    ]
                )
            ),
        }
        decisions.append(decision)

    decision_counts = Counter(decision["decision_type"] for decision in decisions)
    return {
        "run_metadata": {
            **no_side_effect_metadata(),
            "run_id": run_id,
            "report_type": "azure_di_reviewed_mapping_decisions",
            "script": "scripts/simulate_azure_di_reviewed_mapping_decisions_14c.py",
        },
        "input_reports": dict(input_paths),
        "source_feature_chain": ["13X", "13Y", "13Z", "14A", "14B", "14C"],
        "simulation_policy": simulation_policy.__dict__,
        "source_review_policy_summary": {
            "workflow_statuses": sorted((review_policy.get("workflow_status_definitions") or {}).keys()),
            "handoff_contract_status": handoff_contract.get("contract_status"),
        },
        "total_review_items": len(review_queue.get("queue_items") or []),
        "simulated_decision_count": len(decisions),
        "decision_type_counts": dict(decision_counts),
        "simulated_approved_count": decision_counts.get(APPROVAL_DECISION, 0),
        "xbrl_eligible_count": sum(1 for decision in decisions if decision.get("xbrl_eligible")),
        "simulated_decisions": decisions,
        "traceability_summary": _traceability_summary(decisions),
        "limitations": _simulation_limitations(),
    }


def _handoff_item_from_decision(decision: Mapping[str, Any], index: int) -> dict[str, Any]:
    selected = decision.get("selected_suggestion") or {}
    evidence = dict(decision.get("source_evidence") or {})
    provenance = dict(decision.get("provenance") or {})
    return {
        "reviewed_mapping_id": f"14C-REVIEWED-MAP-{index:04d}",
        "simulated_decision_id": decision.get("simulated_decision_id"),
        "mapping_input_id": decision.get("mapping_input_id"),
        "source_candidate_id": decision.get("source_candidate_id"),
        "case_id": decision.get("case_id"),
        "final_concept_qname": selected.get("concept_qname"),
        "final_concept_label": selected.get("concept_label"),
        "final_concept_type": selected.get("concept_type"),
        "final_label": evidence.get("label"),
        "final_value": evidence.get("value"),
        "final_previous_value": evidence.get("previous_value"),
        "final_text": evidence.get("text_preview"),
        "final_row_type": decision.get("row_type") or provenance.get("row_type"),
        "final_statement_section": evidence.get("statement_section"),
        "approval_status": "simulated_approved",
        "simulated_only": True,
        "human_approved": False,
        "requires_confirmation": bool(decision.get("requires_confirmation")),
        "source_suggestion_id": selected.get("suggestion_id") or selected.get("concept_qname"),
        "evidence": evidence,
        "provenance": provenance,
        "audit_trail": {
            "source": "14C_simulated_reviewed_mapping_handoff",
            "source_simulated_decision_id": decision.get("simulated_decision_id"),
            "simulated_only": True,
            "human_approved": False,
            "production_mapping_approved": False,
        },
        "xbrl_eligible": True,
        "xbrl_blockers": [],
    }


def build_simulated_handoff_report(
    *,
    decisions_report: Mapping[str, Any],
    run_id: str | None,
    input_paths: Mapping[str, Any],
) -> dict[str, Any]:
    eligible = [decision for decision in decisions_report.get("simulated_decisions") or [] if decision.get("xbrl_eligible")]
    handoff_items = [_handoff_item_from_decision(decision, index) for index, decision in enumerate(eligible, start=1)]
    return {
        "run_metadata": {
            **no_side_effect_metadata(),
            "run_id": run_id,
            "report_type": "azure_di_reviewed_mapping_handoff",
            "script": "scripts/simulate_azure_di_reviewed_mapping_decisions_14c.py",
        },
        "input_reports": dict(input_paths),
        "source_feature_chain": ["13X", "13Y", "13Z", "14A", "14B", "14C"],
        "package_status": "simulated_only_not_human_approved_not_xbrl_ready",
        "total_simulated_decisions": decisions_report.get("simulated_decision_count", 0),
        "xbrl_eligible_count": len(handoff_items),
        "handoff_items": handoff_items,
        "eligibility_statement": [
            "This is not production approval.",
            "This is not human approval.",
            "This is not ready for XBRL filing.",
            "It exists only to test downstream package shape and future XBRL eligibility logic.",
        ],
        "limitations": _simulation_limitations(),
    }


def build_eligibility_summary_report(
    *,
    decisions_report: Mapping[str, Any],
    handoff_report: Mapping[str, Any],
    run_id: str | None,
    input_paths: Mapping[str, Any],
) -> dict[str, Any]:
    decisions = list(decisions_report.get("simulated_decisions") or [])
    decision_counts = Counter(str(decision.get("decision_type") or "unknown") for decision in decisions)
    blockers = Counter(blocker for decision in decisions for blocker in decision.get("xbrl_blockers") or [])
    by_row_type: dict[str, Counter[str]] = {}
    by_workflow: dict[str, Counter[str]] = {}
    by_tier: dict[str, Counter[str]] = {}
    for decision in decisions:
        status = "eligible" if decision.get("xbrl_eligible") else "not_eligible"
        row_type = str(decision.get("row_type") or (decision.get("source_evidence") or {}).get("row_type") or "unknown")
        workflow = str(decision.get("workflow_status") or "unknown")
        tier = str(decision.get("original_confidence_tier") or "none")
        by_row_type.setdefault(row_type, Counter())[status] += 1
        by_workflow.setdefault(workflow, Counter())[status] += 1
        by_tier.setdefault(tier, Counter())[status] += 1
    return {
        "run_metadata": {
            **no_side_effect_metadata(),
            "run_id": run_id,
            "report_type": "azure_di_xbrl_eligibility_summary",
            "script": "scripts/simulate_azure_di_reviewed_mapping_decisions_14c.py",
        },
        "input_reports": dict(input_paths),
        "total_review_items": len(decisions),
        "simulated_approved_count": decision_counts.get(APPROVAL_DECISION, 0),
        "xbrl_eligible_count": handoff_report.get("xbrl_eligible_count", 0),
        "xbrl_blocked_count": len([decision for decision in decisions if not decision.get("xbrl_eligible")]),
        "deferred_count": decision_counts.get(DEFER_DECISION, 0),
        "alias_enrichment_needed_count": decision_counts.get("request_alias_enrichment", 0),
        "metadata_enrichment_needed_count": decision_counts.get("request_concept_metadata_enrichment", 0),
        "manual_taxonomy_mapping_needed_count": decision_counts.get("require_manual_taxonomy_mapping", 0),
        "rejected_count": decision_counts.get("reject_mapping", 0),
        "context_only_count": decision_counts.get("keep_for_context_only", 0),
        "decision_type_counts": dict(decision_counts),
        "per_row_type_eligibility": {key: dict(value) for key, value in sorted(by_row_type.items())},
        "per_workflow_status_eligibility": {key: dict(value) for key, value in sorted(by_workflow.items())},
        "per_confidence_tier_eligibility": {key: dict(value) for key, value in sorted(by_tier.items())},
        "top_xbrl_blockers": [{"blocker": key, "count": value} for key, value in blockers.most_common(20)],
        "why_xbrl_generation_is_still_not_allowed": [
            "Every approval is simulated_only=true and human_approved=false.",
            "No final production mapping approval exists.",
            "Ambiguous, no-safe, blocked, and default confirmation-required records remain excluded.",
            "This feature does not generate XBRL or run Arelle validation.",
        ],
        "recommended_next_feature": recommend_next_feature(decisions_report),
        "limitations": _simulation_limitations(),
    }


def build_simulation_policy_report(
    *,
    simulation_policy: SimulationPolicy,
    run_id: str | None,
    input_paths: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "run_metadata": {
            **no_side_effect_metadata(),
            "run_id": run_id,
            "report_type": "azure_di_review_simulation_policy",
            "script": "scripts/simulate_azure_di_reviewed_mapping_decisions_14c.py",
        },
        "input_reports": dict(input_paths),
        "simulation_strategy": {
            "default_conservative_behavior": "Approve only ready_for_review_approval items with high/strong-medium compatible top suggestions.",
            "active_policy": simulation_policy.__dict__,
        },
        "optional_flags": {
            "approve_ready_only": "Default true; limits simulated approvals to ready_for_review_approval items unless explicit scenarios are enabled.",
            "simulate_confirm_medium": "When enabled, medium-or-better needs_confirmation items may be simulated as approved.",
            "simulate_choose_top_ambiguous": "When enabled, ambiguous items may choose the top suggestion for simulation only.",
            "strict": "Default true; blocks low-confidence numeric and type-mismatch approvals.",
        },
        "simulated_xbrl_eligibility_rules": [
            "Simulated approvals must have a selected concept and compatible row/concept evidence.",
            "Default simulation excludes ambiguous, no-safe, blocked, context-only, and low-confidence risky records.",
            "Eligible handoff items remain simulated_only=true and human_approved=false.",
        ],
        "blocked_rules": [
            "No real human approval is recorded.",
            "No production mapping approval is produced.",
            "No XBRL generation is allowed from #14C outputs.",
            "No Arelle validation is run.",
        ],
        "future_work_preparation": [
            "The decisions report models future reviewer-decision shape.",
            "The handoff report tests downstream package shape for reviewed mappings.",
            "The eligibility summary shows how much review/enrichment remains before sandbox XBRL work is justified.",
        ],
        "non_goals": [
            "No DB/API/UI implementation.",
            "No production cutover.",
            "No Azure DI, Hugging Face, OpenAI, embedding, or semantic matcher calls.",
            "No reference XML is sent to any model or provider.",
        ],
    }


def build_reviewed_mapping_simulation_reports(
    *,
    review_queue: Mapping[str, Any],
    review_policy: Mapping[str, Any],
    handoff_contract: Mapping[str, Any],
    run_id: str | None = "azure_di_reviewed_mapping_simulation_14c",
    input_paths: Mapping[str, Any] | None = None,
    simulation_policy: SimulationPolicy | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    policy = simulation_policy or SimulationPolicy()
    inputs = dict(input_paths or {})
    decisions = build_simulated_decisions_report(
        review_queue=review_queue,
        review_policy=review_policy,
        handoff_contract=handoff_contract,
        run_id=run_id,
        input_paths=inputs,
        simulation_policy=policy,
    )
    handoff = build_simulated_handoff_report(decisions_report=decisions, run_id=run_id, input_paths=inputs)
    eligibility = build_eligibility_summary_report(
        decisions_report=decisions,
        handoff_report=handoff,
        run_id=run_id,
        input_paths=inputs,
    )
    simulation_policy_report = build_simulation_policy_report(
        simulation_policy=policy,
        run_id=run_id,
        input_paths=inputs,
    )
    return decisions, handoff, eligibility, simulation_policy_report


def _traceability_summary(decisions: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(decisions)
    traceable = sum(
        1
        for row in rows
        if row.get("review_mapping_item_id") and row.get("mapping_input_id") and row.get("source_candidate_id")
    )
    return {
        "decisions": len(rows),
        "decisions_with_review_mapping_item_id": sum(1 for row in rows if row.get("review_mapping_item_id")),
        "decisions_with_mapping_input_id": sum(1 for row in rows if row.get("mapping_input_id")),
        "decisions_with_source_candidate_id": sum(1 for row in rows if row.get("source_candidate_id")),
        "coverage_ratio": 1.0 if not rows else round(traceable / len(rows), 4),
    }


def _simulation_limitations() -> list[str]:
    return [
        "All decisions are simulated_only=true and human_approved=false.",
        "No final production mapping approval occurs.",
        "No XBRL is generated and no Arelle validation is run.",
        "No live provider, model, embedding, semantic matcher, DB, API, or UI path is used.",
    ]


def recommend_next_feature(decisions_report: Mapping[str, Any]) -> str:
    total = int(decisions_report.get("simulated_decision_count") or 0)
    eligible = int(decisions_report.get("xbrl_eligible_count") or 0)
    if total and eligible >= total * 0.5:
        return "Feature #14D - Sandbox XBRL package shape design from simulated reviewed mappings, no XBRL generation yet."
    if total and eligible >= total * 0.2:
        return "Feature #14D - Reviewed mapping quality evaluation against reference XML, no DB mutation."
    return "Feature #14D - Concept metadata enrichment v2 if simulation approves too few mappings."


def render_decisions_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Azure DI Reviewed Mapping Decisions - Feature #14C",
        "",
        "## Summary",
        "",
        f"- Total review items: {report.get('total_review_items', 0)}",
        f"- Simulated decisions: {report.get('simulated_decision_count', 0)}",
        f"- Simulated approved: {report.get('simulated_approved_count', 0)}",
        f"- XBRL eligible: {report.get('xbrl_eligible_count', 0)}",
        f"- Decision types: {report.get('decision_type_counts', {})}",
        f"- Final mapping approved: {report.get('run_metadata', {}).get('final_mapping_approved')}",
        "",
        "## Decision Preview",
        "",
    ]
    for decision in (report.get("simulated_decisions") or [])[:25]:
        lines.append(
            f"- `{decision.get('simulated_decision_id')}` {decision.get('decision_type')} "
            f"eligible={decision.get('xbrl_eligible')} - {decision.get('mapping_input_id')}"
        )
    if not report.get("simulated_decisions"):
        lines.append("- None")
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.get("limitations", []))
    lines.append("")
    return "\n".join(lines)


def render_handoff_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Azure DI Reviewed Mapping Handoff - Feature #14C",
        "",
        "## Summary",
        "",
        f"- Package status: {report.get('package_status')}",
        f"- Simulated decisions: {report.get('total_simulated_decisions', 0)}",
        f"- XBRL eligible simulated handoff items: {report.get('xbrl_eligible_count', 0)}",
        "",
        "## Handoff Preview",
        "",
    ]
    for item in (report.get("handoff_items") or [])[:25]:
        lines.append(
            f"- `{item.get('reviewed_mapping_id')}` {item.get('final_concept_qname')} "
            f"human_approved={item.get('human_approved')}"
        )
    if not report.get("handoff_items"):
        lines.append("- None")
    lines.extend(["", "## Eligibility Statement", ""])
    lines.extend(f"- {item}" for item in report.get("eligibility_statement", []))
    lines.append("")
    return "\n".join(lines)


def render_eligibility_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Azure DI XBRL Eligibility Summary - Feature #14C",
        "",
        "## Summary",
        "",
        f"- Total review items: {report.get('total_review_items', 0)}",
        f"- Simulated approved: {report.get('simulated_approved_count', 0)}",
        f"- XBRL eligible: {report.get('xbrl_eligible_count', 0)}",
        f"- XBRL blocked: {report.get('xbrl_blocked_count', 0)}",
        f"- Deferred: {report.get('deferred_count', 0)}",
        f"- Alias enrichment needed: {report.get('alias_enrichment_needed_count', 0)}",
        f"- Metadata enrichment needed: {report.get('metadata_enrichment_needed_count', 0)}",
        f"- Manual taxonomy mapping needed: {report.get('manual_taxonomy_mapping_needed_count', 0)}",
        f"- Recommended next feature: {report.get('recommended_next_feature')}",
        "",
        "## Why XBRL Generation Is Still Not Allowed",
        "",
    ]
    lines.extend(f"- {item}" for item in report.get("why_xbrl_generation_is_still_not_allowed", []))
    lines.extend(["", "## Top XBRL Blockers", ""])
    blockers = report.get("top_xbrl_blockers") or []
    lines.extend(f"- {row.get('blocker')}: {row.get('count')}" for row in blockers[:20]) if blockers else lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def render_policy_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Azure DI Review Simulation Policy - Feature #14C",
        "",
        "## Strategy",
        "",
        f"- Default behavior: {report.get('simulation_strategy', {}).get('default_conservative_behavior')}",
        f"- Active policy: {report.get('simulation_strategy', {}).get('active_policy', {})}",
        "",
        "## Optional Flags",
        "",
    ]
    for key, value in (report.get("optional_flags") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Simulated XBRL Eligibility Rules", ""])
    lines.extend(f"- {item}" for item in report.get("simulated_xbrl_eligibility_rules", []))
    lines.extend(["", "## Blocked Rules", ""])
    lines.extend(f"- {item}" for item in report.get("blocked_rules", []))
    lines.append("")
    return "\n".join(lines)


def run_reviewed_mapping_simulation(
    *,
    review_queue_path: str | Path = DEFAULT_REVIEW_QUEUE,
    review_policy_path: str | Path = DEFAULT_REVIEW_POLICY,
    handoff_contract_path: str | Path = DEFAULT_HANDOFF_CONTRACT,
    run_id: str | None = "azure_di_reviewed_mapping_simulation_14c",
    output_prefix: str | Path | None = None,
    simulation_policy: SimulationPolicy | None = None,
) -> dict[str, Any]:
    queue_path = Path(review_queue_path)
    policy_path = Path(review_policy_path)
    contract_path = Path(handoff_contract_path)
    paths = output_paths_from_prefix(output_prefix)
    input_paths = {
        "review_queue": str(queue_path),
        "review_policy": str(policy_path),
        "handoff_contract": str(contract_path),
    }
    decisions, handoff, eligibility, policy = build_reviewed_mapping_simulation_reports(
        review_queue=_load_json(queue_path),
        review_policy=_load_json(policy_path),
        handoff_contract=_load_json(contract_path),
        run_id=run_id,
        input_paths=input_paths,
        simulation_policy=simulation_policy,
    )
    for report, path in [
        (decisions, paths.decisions_json),
        (handoff, paths.handoff_json),
        (eligibility, paths.eligibility_json),
        (policy, paths.policy_json),
    ]:
        metadata = dict(report.get("run_metadata") or {})
        metadata["output_path"] = str(path)
        report["run_metadata"] = metadata

    _write_json(paths.decisions_json, decisions)
    _write_text(paths.decisions_md, render_decisions_markdown(decisions))
    _write_json(paths.handoff_json, handoff)
    _write_text(paths.handoff_md, render_handoff_markdown(handoff))
    _write_json(paths.eligibility_json, eligibility)
    _write_text(paths.eligibility_md, render_eligibility_markdown(eligibility))
    _write_json(paths.policy_json, policy)
    _write_text(paths.policy_md, render_policy_markdown(policy))

    return {
        "paths": paths,
        "decisions_report": decisions,
        "handoff_report": handoff,
        "eligibility_report": eligibility,
        "policy_report": policy,
    }
