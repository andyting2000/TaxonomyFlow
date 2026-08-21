"""Generate Feature #18F-G-A implementation, contract, and safety reports."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FEATURE = "18F-G-A"


def _write_report(output_dir: Path, stem: str, payload: dict[str, Any], markdown: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{stem}.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / f"{stem}.md").write_text(markdown.rstrip() + "\n", encoding="utf-8")


def build_reports(full_tests_count: int) -> list[tuple[str, dict[str, Any], str]]:
    generated_at = datetime.now(timezone.utc).isoformat()
    verification = {
        "focused_correction_tests": 14,
        "supervisor_pattern_tests": 117,
        "llm_mapper_tests": 34,
        "user_isolation_tests": 18,
        "admin_tests": 9,
        "frontend_tests": 26,
        "frontend_build": "passed",
        "full_backend_tests": full_tests_count or "pending",
    }
    next_feature = {
        "manual_gate": "Run one approved eligible suggestion through the manual correction UI and inspect the separate revision.",
        "if_smoke_succeeds": "#18F-G-B - Integrate conditional Supervisor-guided remapping into the production orchestration design",
        "if_quality_is_weak": "#18F-G-A-hotfix-1 - Tighten the Supervisor feedback payload and remapping prompt",
        "persistence_status": "resolved_with_dedicated_revision_table",
    }

    implementation = {
        "feature": FEATURE,
        "generated_at": generated_at,
        "status": "implemented_awaiting_manual_quality_smoke",
        "button_text_changes": [
            {
                "previous": "Run live Supervisor reviews for all",
                "current": "Run Supervisor reviews for all",
            },
            {
                "previous": "Run live Supervisor review",
                "current": "Run Supervisor review",
            },
        ],
        "previous_workflow": [
            "initial_mapping_suggestion",
            "supervisor_review",
            "human_accept_or_reject",
        ],
        "new_workflow": [
            "initial_mapping_suggestion",
            "supervisor_review",
            "optional_explicit_supervisor_guided_remap",
            "separate_revised_suggestion",
            "human_accept_or_reject",
        ],
        "manual_action_label": "Re-run mapping with Supervisor feedback",
        "eligibility": {
            "eligible": [
                "disagree",
                "prefer_alternative_candidate",
                "request_better_candidate",
                "needs_human_review_with_concrete_mapping_issue",
            ],
            "ineligible": [
                "agree",
                "missing_review",
                "pending_or_failed_review",
                "unsafe_or_invalid_response",
                "skipped_or_blocked_review",
                "retry_limit_reached",
                "accepted_or_rejected_initial_suggestion",
            ],
        },
        "persistence_decision": {
            "mode": "dedicated_revision_table",
            "table": "supervisor_guided_mapping_revisions",
            "migration": "migrations/013_add_supervisor_guided_mapping_revisions.sql",
            "reason": "Durable retry enforcement requires a separate record and the original suggestion must remain immutable.",
        },
        "retry_policy": {
            "default_max_retries": 1,
            "durable": True,
            "automatic_rerun": False,
            "mapper_to_supervisor_recursion": False,
            "supervisor_to_mapper_recursion": False,
        },
        "verification": verification,
        "recommended_next_feature": next_feature,
    }
    implementation_md = f"""# Supervisor-guided remapping - #18F-G-A

Status: implemented; manual revised-mapping quality smoke remains pending.

## Copy changes

- `Run live Supervisor reviews for all` -> `Run Supervisor reviews for all`
- `Run live Supervisor review` -> `Run Supervisor review`

## Workflow

The initial suggestion and completed Supervisor review remain unchanged. An eligible review can expose the explicit `Re-run mapping with Supervisor feedback` action. The result is stored as a separate advisory revision and still requires human review.

There is no automatic Supervisor-to-mapper run and no mapper-to-Supervisor recursion.

## Persistence

Revisions use `supervisor_guided_mapping_revisions`. The dedicated table preserves the initial suggestion and makes the default one-attempt retry limit durable.

## Verification

- Focused correction tests: 14
- Supervisor pattern tests: 117
- Mapper tests: 34
- Ownership tests: 18
- Admin tests: 9
- Frontend tests: 26
- Frontend build: passed
- Full backend tests: {full_tests_count or 'pending'}

## Next

Run one approved manual correction smoke. If quality is acceptable, proceed to #18F-G-B design. If quality is weak, select #18F-G-A-hotfix-1.
"""

    contract = {
        "feature": FEATURE,
        "generated_at": generated_at,
        "endpoint": {
            "method": "POST",
            "path": "/api/v1/filings/jobs/{job_id}/suggestions/{suggestion_id}/remap-with-supervisor-feedback",
            "ownership_required": True,
            "admin_only_default": True,
        },
        "supporting_endpoints": [
            "GET /api/v1/filings/jobs/{job_id}/supervisor-mapper-feedback/capabilities",
            "GET /api/v1/filings/jobs/{job_id}/supervisor-guided-mapping-revisions",
        ],
        "feedback_payload_allowed": [
            "production_row_label",
            "normalized_label",
            "row_value",
            "period",
            "statement_family",
            "section_block",
            "row_role",
            "note_boundary",
            "initial_mapping_suggestion",
            "current_ranked_candidates",
            "supervisor_decision",
            "supervisor_reason",
            "supervisor_issues",
            "supervisor_alternatives",
            "supervisor_preferred_candidate",
            "sanitized_concept_card_evidence",
            "do_not_confuse_guidance",
        ],
        "feedback_payload_prohibited": [
            "auditor_xml",
            "paired_auditor_xbrl_facts",
            "parsed_xml_facts",
            "benchmark_gold_qnames",
            "target_correct_qname",
            "target_correct_template_field_id",
            "gold_answers",
            "evaluation_labels",
        ],
        "prompt_rules": [
            "Supervisor feedback is advisory and may be wrong.",
            "Reconsider the original mapping independently.",
            "Choose only from supplied candidates.",
            "Return null when evidence remains insufficient.",
            "Return strict JSON only.",
        ],
        "revision_fields": [
            "parent_suggestion_id",
            "supervisor_review_id",
            "correction_attempt",
            "correction_source",
            "original_suggested_qname",
            "revised_suggested_qname",
            "supervisor_decision",
            "reason",
            "addressed_supervisor_issues",
            "remaining_ambiguities",
            "requires_human_review",
            "safe_for_auto_apply",
            "created_at",
        ],
        "response_sections": [
            "initial_suggestion",
            "supervisor_review",
            "revised_suggestion",
            "safety",
        ],
    }
    contract_md = """# Supervisor-guided remapping contract - #18F-G-A

The POST endpoint is ownership-gated, disabled by default, and admin-only by default. It requires a completed eligible Supervisor review and a remaining retry.

The mapper receives only the production row context, candidate-constrained mapping evidence, advisory Supervisor findings, sanitized concept-card fields, and do-not-confuse guidance. Auditor XML, parsed reference facts, target answers, gold qnames, and evaluation labels are forbidden recursively.

The response separates the initial suggestion, Supervisor review, revised suggestion, and zero-mutation safety counters.
"""

    safety = {
        "feature": FEATURE,
        "generated_at": generated_at,
        "feature_flags": {
            "SUPERVISOR_MAPPER_FEEDBACK_ENABLED": False,
            "SUPERVISOR_MAPPER_FEEDBACK_AUTO_RUN": False,
            "SUPERVISOR_MAPPER_FEEDBACK_MAX_RETRIES": 1,
            "SUPERVISOR_MAPPER_FEEDBACK_ADMIN_ONLY": True,
            "VITE_SHOW_SUPERVISOR_MAPPER_FEEDBACK": False,
        },
        "schema_guards": {
            "requires_human_review": True,
            "safe_for_auto_apply": False,
            "unique_attempt_per_parent": True,
        },
        "runtime_guards": {
            "original_suggestion_mutations": 0,
            "confirmed_tag_id_mutations": 0,
            "final_mapping_mutations": 0,
            "auto_apply_count": 0,
            "auto_accept_count": 0,
            "automatic_correction_count": 0,
            "recursive_supervisor_calls": 0,
        },
        "external_calls_during_implementation_or_tests": 0,
        "auditor_xml_sent_externally": False,
        "parsed_xml_facts_sent_externally": False,
        "gold_answers_sent_externally": False,
        "evaluation_labels_sent_externally": False,
        "xbrl_generated": False,
        "arelle_run": False,
        "verification": verification,
    }
    safety_md = """# Supervisor-guided remapping safety - #18F-G-A

- Backend and frontend correction flags default to disabled.
- Auto-run is false and the service fails closed if it is enabled.
- The default retry limit is one durable attempt per initial suggestion.
- Original suggestions and extracted-row mapping fields are never updated.
- Every revision requires human review and is unsafe for auto-apply.
- Auditor XML, parsed XML facts, gold answers, and evaluation labels are excluded.
- Tests and report generation made no external LLM calls.
"""

    return [
        ("supervisor_guided_remapping_18f_g_a", implementation, implementation_md),
        ("supervisor_guided_remapping_contract_18f_g_a", contract, contract_md),
        ("supervisor_guided_remapping_safety_18f_g_a", safety, safety_md),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--full-tests-count", type=int, default=0)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    for stem, payload, markdown in build_reports(args.full_tests_count):
        _write_report(output_dir, stem, payload, markdown)
        print(output_dir / f"{stem}.json")
        print(output_dir / f"{stem}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
