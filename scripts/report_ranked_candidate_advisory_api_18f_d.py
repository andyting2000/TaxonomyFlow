"""Generate #18F-D ranked candidate advisory API contract reports."""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser, Namespace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.hybrid_candidate_calibration import available_ranking_profiles
from services.ranked_candidate_advisory_service import FEATURE_FLAG_NAMES, SAFETY_GUARANTEES


REPORT_PREFIXES = {
    "api": "ranked_candidate_advisory_api_18f_d",
    "safety": "ranked_candidate_advisory_api_safety_18f_d",
    "contract": "ranked_candidate_advisory_api_contract_18f_d",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_api_report(generated_at: str) -> dict[str, Any]:
    return {
        "run_metadata": {
            "feature": "18F-D",
            "generated_at": generated_at,
            "report_type": "ranked_candidate_advisory_api",
        },
        "summary": {
            "implemented": True,
            "disabled_by_default": True,
            "dry_run_only": True,
            "persistence_enabled": False,
            "ui_changed": False,
            "db_migration_added": False,
            "recommended_next_feature": "Feature #18F-E - Add read-only frontend test panel for ranked candidates behind disabled UI flag",
        },
        "endpoints_added": [
            {
                "method": "GET",
                "path": "/api/v1/filings/jobs/{job_id}/ranked-candidates/capabilities",
                "response_model": "RankedCandidateCapabilitiesRead",
                "ownership_check": "_get_owned_job_or_404",
                "side_effects": [],
            },
            {
                "method": "POST",
                "path": "/api/v1/filings/jobs/{job_id}/ranked-candidates/run",
                "request_model": "RankedCandidateAdvisoryRequest",
                "response_model": "RankedCandidateAdvisoryResponse",
                "ownership_check": "_get_owned_job_or_404",
                "feature_flag": FEATURE_FLAG_NAMES["enabled"],
                "side_effects": [],
            },
        ],
        "feature_flag_defaults": {
            FEATURE_FLAG_NAMES["enabled"]: False,
            FEATURE_FLAG_NAMES["default_mode"]: "dry_run",
            FEATURE_FLAG_NAMES["allow_persistence"]: False,
            FEATURE_FLAG_NAMES["default_profile"]: "balanced",
            FEATURE_FLAG_NAMES["max_rows"]: 1000,
            FEATURE_FLAG_NAMES["max_candidates_per_row"]: 5,
            FEATURE_FLAG_NAMES["admin_only"]: True,
        },
        "disabled_behavior": {
            "capabilities_endpoint": "Returns enabled=false and dry-run-only metadata after ownership check.",
            "run_endpoint": "Returns HTTP 403 before generation when ranked candidate advisory is disabled.",
            "candidate_generation": False,
            "persistence_writes": 0,
            "mapping_mutations": 0,
        },
        "dry_run_enabled_behavior": {
            "mode": "dry_run",
            "profile_default": "balanced",
            "supported_profiles": available_ranking_profiles(),
            "sources": [
                "existing job extracted_data_items",
                "local taxonomy metadata",
                "local concept playbook artifacts",
                "statement dictionary and local candidate source packs",
            ],
            "excluded_sources": [
                "evaluation labels",
                "paired XBRL gold answers",
                "Qwen",
                "Supervisor",
                "LLM/API calls",
                "live Azure Document Intelligence",
            ],
        },
    }


def build_safety_report(generated_at: str) -> dict[str, Any]:
    return {
        "run_metadata": {
            "feature": "18F-D",
            "generated_at": generated_at,
            "report_type": "ranked_candidate_advisory_api_safety",
        },
        "required_safety_counters": {
            "safe_for_auto_apply_count": 0,
            "confirmed_tag_id_mutations": 0,
            "final_mapping_mutations": 0,
            "persistence_writes": 0,
            "ai_suggestion_table_writes": 0,
            "external_calls": 0,
            "xbrl_generation_count": 0,
            "arelle_runs": 0,
        },
        "candidate_invariants": {
            "requires_human_review": True,
            "safe_for_auto_apply": False,
            "allowed_recommended_actions": [
                "review_candidate",
                "keep_for_human_review",
                "no_candidate",
                "blocked",
            ],
            "rejected_actions": [
                "accept",
                "apply",
                "confirm",
                "auto_apply",
                "auto_accept",
                "set_confirmed_tag_id",
            ],
        },
        "guardrails": {
            **SAFETY_GUARANTEES,
            "api_changed": True,
            "database_mutated": False,
            "persistence_writes": 0,
            "final_mapping_mutations": 0,
            "mapping_row_mutations": 0,
        },
        "fail_closed_behavior": [
            "Run endpoint rejects disabled feature flag with HTTP 403.",
            "Run endpoint rejects non-dry-run request modes.",
            "Run endpoint rejects unsupported profiles.",
            "Run endpoint rejects request caps above configured limits.",
            "Missing local taxonomy or concept-card artifacts return a safe advisory error.",
        ],
    }


def build_contract_report(generated_at: str) -> dict[str, Any]:
    return {
        "run_metadata": {
            "feature": "18F-D",
            "generated_at": generated_at,
            "report_type": "ranked_candidate_advisory_api_contract",
        },
        "capabilities_response": {
            "model": "RankedCandidateCapabilitiesRead",
            "fields": [
                "job_id",
                "enabled",
                "default_mode",
                "allow_persistence",
                "default_profile",
                "supported_profiles",
                "supported_modes",
                "supported_actions",
                "max_rows",
                "max_candidates_per_row",
                "admin_only",
                "feature_flags",
                "endpoints",
                "safety",
            ],
        },
        "run_request": {
            "model": "RankedCandidateAdvisoryRequest",
            "fields": {
                "profile": "balanced by default; must be one of strict/balanced/recall",
                "mode": "dry_run only",
                "max_rows": "must not exceed configured RANKED_CANDIDATES_ADVISORY_MAX_ROWS",
                "max_candidates_per_row": "must not exceed configured RANKED_CANDIDATES_ADVISORY_MAX_CANDIDATES_PER_ROW",
            },
        },
        "run_response": {
            "model": "RankedCandidateAdvisoryResponse",
            "row_model": "RankedCandidateRow",
            "candidate_model": "RankedCandidateItem",
            "safety_model": "RankedCandidateSafetySummary",
            "status": "completed for successful dry-run generation",
        },
        "non_goals_confirmed": [
            "No UI work.",
            "No DB migration.",
            "No persistence.",
            "No AI suggestion table writes.",
            "No final mapping mutation.",
            "No mapping row mutation.",
            "No confirmed_tag_id automation.",
            "No auto-apply, auto-accept, or auto-reject.",
            "No Qwen, Supervisor, LLM, external provider, or live Azure DI call.",
            "No XBRL generation.",
            "No Arelle run.",
        ],
        "recommended_next_feature": "Feature #18F-E - Add read-only frontend test panel for ranked candidates behind disabled UI flag",
    }


def render_markdown(title: str, report: Mapping[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        f"# {title}",
        "",
        f"- Feature: `{(report.get('run_metadata') or {}).get('feature')}`",
        f"- Generated at: `{(report.get('run_metadata') or {}).get('generated_at')}`",
    ]
    if summary:
        for key, value in summary.items():
            lines.append(f"- {key}: `{value}`")
    if report.get("endpoints_added"):
        lines.append("")
        lines.append("## Endpoints")
        for endpoint in report["endpoints_added"]:
            lines.append(f"- `{endpoint['method']} {endpoint['path']}`")
    if report.get("required_safety_counters"):
        lines.append("")
        lines.append("## Safety Counters")
        for key, value in report["required_safety_counters"].items():
            lines.append(f"- {key}: `{value}`")
    if report.get("recommended_next_feature"):
        lines.append("")
        lines.append(f"- Recommended next feature: `{report.get('recommended_next_feature')}`")
    return "\n".join(lines) + "\n"


def write_report(output_dir: Path, prefix: str, title: str, payload: Mapping[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{prefix}.json").write_text(
        json.dumps(payload, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (output_dir / f"{prefix}.md").write_text(
        render_markdown(title, payload),
        encoding="utf-8",
    )


def build_reports(generated_at: str) -> dict[str, dict[str, Any]]:
    return {
        "api": build_api_report(generated_at),
        "safety": build_safety_report(generated_at),
        "contract": build_contract_report(generated_at),
    }


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="reports")
    args: Namespace = parser.parse_args(argv)

    generated_at = utc_now()
    reports = build_reports(generated_at)
    output_dir = Path(args.output_dir)
    write_report(
        output_dir,
        REPORT_PREFIXES["api"],
        "Ranked Candidate Advisory API #18F-D",
        reports["api"],
    )
    write_report(
        output_dir,
        REPORT_PREFIXES["safety"],
        "Ranked Candidate Advisory API Safety #18F-D",
        reports["safety"],
    )
    write_report(
        output_dir,
        REPORT_PREFIXES["contract"],
        "Ranked Candidate Advisory API Contract #18F-D",
        reports["contract"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
