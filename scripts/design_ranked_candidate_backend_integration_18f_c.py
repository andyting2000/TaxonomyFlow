"""Generate backend advisory integration design reports for Feature #18F-C."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.hybrid_candidate_calibration import profile_config_to_dict
from services.ranked_candidate_advisory_service import (
    FEATURE_FLAG_NAMES,
    SAFETY_GUARANTEES,
    RankedCandidateAdvisoryConfig,
    advisory_capabilities,
    feature_flags,
    utc_now,
)
from services.tightened_mapper_evaluation import sanitize_report_value


FEATURE = "18F-C"
RECOMMENDED_NEXT_FEATURE = (
    "Feature #18F-D - Implement dry-run backend ranked-candidate advisory API "
    "behind disabled feature flag"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--calibration-summary",
        default="reports/hybrid_candidate_calibration_summary_18f_b.json",
    )
    parser.add_argument(
        "--recommended-profile",
        default="reports/hybrid_candidate_calibration_recommended_profile_18f_b.json",
    )
    parser.add_argument("--output-dir", default="reports")
    return parser.parse_args()


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    Path(path).write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def write_text(path: str | Path, text: str) -> None:
    Path(path).write_text(text.rstrip() + "\n", encoding="utf-8")


def _metadata(args: argparse.Namespace, generated_at: str) -> dict[str, Any]:
    return {
        "feature": FEATURE,
        "generated_at": generated_at,
        "calibration_summary_report": args.calibration_summary,
        "recommended_profile_report": args.recommended_profile,
        "offline_only": True,
        "design_only": True,
        "dry_run_scaffold_only": True,
        "ui_changed": False,
        "api_changed": False,
        "database_mutated": False,
        "production_persistence_enabled": False,
        "production_mapper_integrated": False,
        "auto_applied": False,
        "auto_accept_recommended": False,
        "auto_reject_recommended": False,
        "confirmed_tag_id_mutated": False,
        "confirmed_tag_id_automation_recommended": False,
        "external_llm_called": False,
        "qwen_called": False,
        "supervisor_called": False,
        "azure_di_live_call_made": False,
        "xbrl_generated": False,
        "arelle_run": False,
    }


def _balanced_summary(
    calibration_summary: Mapping[str, Any],
    recommended_profile: Mapping[str, Any],
) -> dict[str, Any]:
    summary = (calibration_summary.get("summary") or {})
    recommended_metrics = summary.get("recommended_metrics") or {}
    basis = ((recommended_profile.get("recommended_profile") or {}).get("basis") or {})
    return {
        "recommended_profile": summary.get("recommended_profile") or "balanced",
        "candidate_coverage_rate": recommended_metrics.get("candidate_coverage_rate") or basis.get("candidate_coverage_rate"),
        "top1_precision_if_evaluable": recommended_metrics.get("top1_precision_if_evaluable") or basis.get("top1_precision_if_evaluable"),
        "top3_recall_if_evaluable": recommended_metrics.get("top3_recall_if_evaluable") or basis.get("top3_recall_if_evaluable"),
        "top5_recall_if_evaluable": recommended_metrics.get("top5_recall_if_evaluable") or basis.get("top5_recall_if_evaluable"),
        "high_or_critical_candidate_ratio": recommended_metrics.get("high_or_critical_candidate_ratio") or basis.get("high_or_critical_candidate_ratio"),
        "critical_candidate_count": recommended_metrics.get("critical_candidate_count") or basis.get("critical_candidate_count"),
        "safe_for_auto_apply_count": recommended_metrics.get("safe_for_auto_apply_count") or basis.get("safe_for_auto_apply_count"),
        "requires_human_review_count": recommended_metrics.get("requires_human_review_count"),
        "total_candidate_count": recommended_metrics.get("total_candidate_count"),
        "rows_with_at_least_1_candidate": recommended_metrics.get("rows_with_at_least_1_candidate"),
        "rows_with_at_least_3_candidates": recommended_metrics.get("rows_with_at_least_3_candidates"),
        "no_candidate_rows": recommended_metrics.get("no_candidate_rows"),
        "risk_distribution": recommended_metrics.get("risk_distribution") or {},
        "candidate_quality_score": recommended_metrics.get("candidate_quality_score") or basis.get("candidate_quality_score"),
        "backend_advisory_integration_justified": summary.get("backend_advisory_integration_justified"),
        "reason": summary.get("recommended_reason") or (recommended_profile.get("recommended_profile") or {}).get("reason"),
    }


def _job_response_contract() -> list[dict[str, Any]]:
    return [
        {"field": "job_id", "type": "integer", "required": True},
        {"field": "filing_id", "type": "integer|null", "required": False},
        {"field": "profile", "type": "string", "default": "balanced"},
        {"field": "mode", "type": "enum", "values": ["dry_run", "persisted_later"]},
        {"field": "candidate_generation_status", "type": "enum", "values": ["disabled", "ready", "running", "completed", "failed"]},
        {"field": "total_rows", "type": "integer"},
        {"field": "rows_with_candidates", "type": "integer"},
        {"field": "candidate_coverage", "type": "number|null"},
        {"field": "generated_at", "type": "iso8601 string|null"},
        {"field": "feature_flags", "type": "object"},
        {"field": "safety", "type": "RankedCandidateSafetySummary"},
        {"field": "rows", "type": "RankedCandidateRow[]"},
    ]


def _row_contract() -> list[dict[str, Any]]:
    return [
        {"field": "row_id", "type": "string"},
        {"field": "statement_family", "type": "string|null"},
        {"field": "section_block", "type": "string|null"},
        {"field": "row_label", "type": "string|null"},
        {"field": "normalized_label", "type": "string|null"},
        {"field": "row_value", "type": "any"},
        {"field": "period", "type": "object"},
        {"field": "note_boundary_type", "type": "string|null"},
        {"field": "candidate_coverage_status", "type": "string"},
        {"field": "candidates", "type": "RankedCandidateItem[]"},
    ]


def _candidate_contract() -> list[dict[str, Any]]:
    return [
        {"field": "rank", "type": "integer"},
        {"field": "qname", "type": "string"},
        {"field": "concept_label", "type": "string|null"},
        {"field": "namespace", "type": "string|null"},
        {"field": "candidate_sources_combined", "type": "string[]"},
        {"field": "score", "type": "number"},
        {"field": "confidence_bucket", "type": "string"},
        {"field": "risk_level", "type": "string"},
        {"field": "evidence", "type": "RankedCandidateEvidence"},
        {"field": "ambiguity_reasons", "type": "string[]"},
        {"field": "blocking_reasons", "type": "string[]"},
        {"field": "requires_human_review", "type": "boolean", "must_equal": True},
        {"field": "safe_for_auto_apply", "type": "boolean", "must_equal": False},
        {"field": "recommended_action", "type": "enum", "values": ["review_candidate", "keep_for_human_review", "no_candidate", "blocked"]},
        {"field": "profile", "type": "string"},
        {"field": "calibration_version", "type": "string"},
    ]


def build_reports(
    *,
    args: argparse.Namespace,
    generated_at: str,
    calibration_summary: Mapping[str, Any],
    recommended_profile: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    metadata = _metadata(args, generated_at)
    cfg = RankedCandidateAdvisoryConfig()
    enabled_cfg = RankedCandidateAdvisoryConfig(enabled=True)
    balanced = _balanced_summary(calibration_summary, recommended_profile)
    profile_config = profile_config_to_dict("balanced")

    service_boundary = {
        "service_module": "services/ranked_candidate_advisory_service.py",
        "router_wiring_in_this_feature": False,
        "database_persistence_in_this_feature": False,
        "runtime_candidate_generation_inputs": [
            "cached extracted rows for a filing/job in a later dry-run API feature",
            "local taxonomy metadata",
            "local calibrated profile configuration",
            "local non-lexical candidate source evidence",
        ],
        "forbidden_runtime_inputs": [
            "auditor XML",
            "parsed XML facts",
            "gold answers",
            "target correct qnames",
            "evaluation labels",
            "external LLM or provider responses",
        ],
    }
    endpoint_contract = [
        {
            "method": "GET",
            "path": "/api/v1/filings/jobs/{job_id}/ranked-candidates/capabilities",
            "feature": "read capability and safety flags only",
            "this_feature_status": "design_only",
        },
        {
            "method": "POST",
            "path": "/api/v1/filings/jobs/{job_id}/ranked-candidates/run",
            "feature": "future dry-run generation behind disabled feature flag",
            "this_feature_status": "design_only",
        },
        {
            "method": "GET",
            "path": "/api/v1/filings/jobs/{job_id}/ranked-candidates",
            "feature": "future read of persisted advisory candidates after a separate persistence feature",
            "this_feature_status": "design_only",
        },
    ]
    no_auto_apply_guarantees = [
        "requires_human_review is always true for every candidate.",
        "safe_for_auto_apply is always false for every candidate.",
        "recommended_action is limited to review_candidate, keep_for_human_review, no_candidate, or blocked.",
        "No response field carries confirmed_tag_id mutation instructions.",
        "Dry-run service returns payloads only and does not receive a database session.",
        "Persistence and UI are deferred to later explicitly approved features.",
    ]
    failure_modes = [
        {"failure": "feature flag disabled", "behavior": "capabilities show disabled; generation fails closed"},
        {"failure": "invalid profile", "behavior": "safe RankedCandidateAdvisoryError"},
        {"failure": "missing local report/input", "behavior": "safe RankedCandidateAdvisoryError"},
        {"failure": "persistence flag accidentally true", "behavior": "effective allow_persistence remains false"},
        {"failure": "unsupported mode", "behavior": "effective mode remains dry_run"},
        {"failure": "candidate with unsafe flags", "behavior": "schema validation rejects or serializer forces safe values"},
    ]
    implementation_phases = [
        {
            "phase": "18F-C",
            "status": "complete_after_this_feature",
            "scope": "design reports, advisory contract, safe config defaults, dry-run service/schema scaffold, safety tests",
        },
        {
            "phase": "18F-D",
            "status": "recommended_next",
            "scope": "implement dry-run backend ranked-candidate advisory API behind disabled feature flag",
        },
        {
            "phase": "18F-E",
            "status": "future",
            "scope": "optional persistence design and migration for advisory candidate snapshots only",
        },
        {
            "phase": "18F-F",
            "status": "future",
            "scope": "review-workflow/UI consumption of advisory candidates, still no auto-apply",
        },
        {
            "phase": "later_separate_approval",
            "status": "not_approved",
            "scope": "any final mapping mutation, confirmed_tag_id automation, auto-accept, or XBRL generation behavior",
        },
    ]

    design = sanitize_report_value(
        {
            "run_metadata": metadata,
            "current_calibrated_mapper_summary": balanced,
            "recommended_profile": "balanced",
            "recommended_profile_config": profile_config,
            "backend_service_boundary": service_boundary,
            "feature_flags": feature_flags(cfg),
            "capabilities_when_disabled": advisory_capabilities(0, config=cfg),
            "capabilities_when_enabled_for_future_dry_run": advisory_capabilities(0, config=enabled_cfg),
            "dry_run_behavior": {
                "mode": "dry_run",
                "runs_candidate_ranking": "future API should run calibrated local ranking against owned job rows only",
                "current_scaffold": "serializes local ranked rows and applies the balanced profile without DB or router wiring",
                "persists_candidates": False,
                "mutates_final_mapping": False,
                "sets_confirmed_tag_id": False,
            },
            "later_persistence_design": {
                "status": "deferred",
                "allowed_future_storage": "advisory candidate snapshot table only, if separately approved",
                "forbidden_storage": ["confirmed_tag_id", "final mapping mutation instructions", "auto-apply decisions"],
            },
            "endpoint_contract": endpoint_contract,
            "safety_constraints": dict(SAFETY_GUARANTEES),
            "failure_modes": failure_modes,
            "no_auto_apply_guarantees": no_auto_apply_guarantees,
            "recommended_implementation_phases": implementation_phases,
            "recommended_next_feature": RECOMMENDED_NEXT_FEATURE,
        }
    )
    contract = sanitize_report_value(
        {
            "run_metadata": metadata,
            "schema_names": [
                "RankedCandidateAdvisoryRequest",
                "RankedCandidateAdvisoryResponse",
                "RankedCandidateRow",
                "RankedCandidateItem",
                "RankedCandidateEvidence",
                "RankedCandidateSafetySummary",
            ],
            "job_level_response": _job_response_contract(),
            "row_level_payload": _row_contract(),
            "candidate_payload": _candidate_contract(),
            "feature_flags": [
                {"name": name, "default": feature_flags(cfg)[name]}
                for name in FEATURE_FLAG_NAMES.values()
            ],
            "forbidden_fields": [
                "confirmed_tag_id",
                "confirmed_tag_id_mutation",
                "final_mapping_update",
                "auto_apply",
                "auto_accept",
                "auto_reject",
            ],
            "recommended_action_allowed_values": [
                "review_candidate",
                "keep_for_human_review",
                "no_candidate",
                "blocked",
            ],
            "recommended_action_forbidden_values": ["accept", "apply", "confirm"],
            "safety": dict(SAFETY_GUARANTEES),
        }
    )
    guardrails = sanitize_report_value(
        {
            "run_metadata": metadata,
            "guardrails": {
                "feature_disabled_by_default": True,
                "dry_run_only": True,
                "persistence_forced_false": True,
                "admin_only_by_default": True,
                "balanced_profile_default": True,
                "safe_for_auto_apply_always_false": True,
                "requires_human_review_always_true": True,
                "recommended_action_never_accept_apply_confirm": True,
                "confirmed_tag_id_mutations": 0,
                "final_mapping_mutations": 0,
                "external_calls": 0,
                "xbrl_generation": 0,
                "arelle_runs": 0,
            },
            "failure_modes": failure_modes,
            "test_expectations": [
                "disabled default fails closed",
                "invalid profile fails closed",
                "missing input report fails closed",
                "max candidates per row is enforced",
                "response contains no confirmed_tag_id mutation field",
                "schema rejects unsafe candidate flags",
                "service source contains no external call path",
            ],
            "residual_risk": [
                "Backend API wiring still needs ownership and admin/feature-flag enforcement in #18F-D.",
                "Persistence remains intentionally deferred.",
                "Balanced profile still leaves 310 no-candidate rows and top3/top5 recall of 0.5825.",
            ],
            "safety": dict(SAFETY_GUARANTEES),
        }
    )
    phases = sanitize_report_value(
        {
            "run_metadata": metadata,
            "why_advisory_integration_is_justified": balanced,
            "why_production_integration_is_not_enabled": [
                "safe_for_auto_apply_count remains 0",
                "all 983 balanced-profile candidates require human review",
                "top3/top5 recall is useful but not sufficient for final mapping",
                "310 rows still have no candidate under the balanced profile",
                "candidate evidence has not been exposed through ownership-gated backend API tests yet",
            ],
            "phases": implementation_phases,
            "recommended_next_feature": RECOMMENDED_NEXT_FEATURE,
            "fallback_recommendations": {
                "if_schema_boundary_is_unclear": "Feature #18F-C-hotfix-1 - Split advisory contract from persistence contract",
                "if_backend_integration_is_premature": "Feature #18E-F-A-3 - Improve candidate coverage before backend integration",
            },
            "safety": dict(SAFETY_GUARANTEES),
        }
    )
    return {
        "design": design,
        "contract": contract,
        "guardrails": guardrails,
        "phases": phases,
    }


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def render_design_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("current_calibrated_mapper_summary") or {}
    lines = [
        "# Ranked Candidate Backend Integration Design #18F-C",
        "",
        "Design-only backend advisory integration path. No route, database, UI, final mapping, or auto-apply behavior is enabled in this feature.",
        "",
        "## Calibrated Mapper Summary",
        "",
        f"- Recommended profile: `{report.get('recommended_profile')}`",
        f"- Candidate coverage: `{_fmt(summary.get('candidate_coverage_rate'))}`",
        f"- Top-1 precision: `{_fmt(summary.get('top1_precision_if_evaluable'))}`",
        f"- Top-3/Top-5 recall: `{_fmt(summary.get('top3_recall_if_evaluable'))}` / `{_fmt(summary.get('top5_recall_if_evaluable'))}`",
        f"- High-or-critical ratio: `{_fmt(summary.get('high_or_critical_candidate_ratio'))}`",
        f"- Critical candidates: `{_fmt(summary.get('critical_candidate_count'))}`",
        f"- Safe for auto-apply: `{_fmt(summary.get('safe_for_auto_apply_count'))}`",
        "",
        "## Service Boundary",
        "",
    ]
    boundary = report.get("backend_service_boundary") or {}
    for key, value in boundary.items():
        lines.append(f"- {key}: `{_fmt(value)}`")
    lines.extend(["", "## Future Endpoints", ""])
    for endpoint in report.get("endpoint_contract") or []:
        lines.append(f"- `{endpoint.get('method')} {endpoint.get('path')}`: {endpoint.get('feature')} ({endpoint.get('this_feature_status')})")
    lines.extend(["", "## No-Auto-Apply Guarantees", ""])
    for item in report.get("no_auto_apply_guarantees") or []:
        lines.append(f"- {item}")
    lines.extend(["", f"Recommended next feature: {report.get('recommended_next_feature')}", ""])
    return "\n".join(lines)


def render_contract_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Ranked Candidate Advisory Contract #18F-C",
        "",
        "## Schema Names",
        "",
    ]
    for name in report.get("schema_names") or []:
        lines.append(f"- `{name}`")
    lines.extend(["", "## Candidate Payload", ""])
    for field in report.get("candidate_payload") or []:
        lines.append(f"- `{field.get('field')}`: {field.get('type')}")
    lines.extend(["", "## Feature Flags", ""])
    for flag in report.get("feature_flags") or []:
        lines.append(f"- `{flag.get('name')}` default `{flag.get('default')}`")
    lines.extend(["", "Forbidden action values: `accept`, `apply`, `confirm`.", ""])
    return "\n".join(lines)


def render_guardrails_markdown(report: Mapping[str, Any]) -> str:
    lines = ["# Ranked Candidate Safety Guardrails #18F-C", ""]
    for key, value in (report.get("guardrails") or {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Failure Modes", ""])
    for item in report.get("failure_modes") or []:
        lines.append(f"- {item.get('failure')}: {item.get('behavior')}")
    return "\n".join(lines)


def render_phases_markdown(report: Mapping[str, Any]) -> str:
    lines = ["# Ranked Candidate Integration Phases #18F-C", ""]
    for phase in report.get("phases") or []:
        lines.append(f"- `{phase.get('phase')}` ({phase.get('status')}): {phase.get('scope')}")
    lines.extend(["", f"Recommended next feature: {report.get('recommended_next_feature')}", ""])
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = utc_now()
    reports = build_reports(
        args=args,
        generated_at=generated_at,
        calibration_summary=read_json(args.calibration_summary),
        recommended_profile=read_json(args.recommended_profile),
    )
    outputs = {
        "ranked_candidate_backend_integration_design_18f_c": (
            reports["design"],
            render_design_markdown(reports["design"]),
        ),
        "ranked_candidate_advisory_contract_18f_c": (
            reports["contract"],
            render_contract_markdown(reports["contract"]),
        ),
        "ranked_candidate_safety_guardrails_18f_c": (
            reports["guardrails"],
            render_guardrails_markdown(reports["guardrails"]),
        ),
        "ranked_candidate_integration_phases_18f_c": (
            reports["phases"],
            render_phases_markdown(reports["phases"]),
        ),
    }
    for stem, (payload, markdown) in outputs.items():
        write_json(output_dir / f"{stem}.json", payload)
        write_text(output_dir / f"{stem}.md", markdown)
    print(
        {
            "feature": FEATURE,
            "recommended_next_feature": RECOMMENDED_NEXT_FEATURE,
            "reports_written": sorted(outputs),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
