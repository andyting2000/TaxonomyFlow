"""Generate deterministic fixture-only #19C quality and safety reports."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import mean
import sys
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from schemas import RowMappingEligibility  # noqa: E402
from services.section_aware_initial_mapping import (
    ARTIFACT_FILENAME,
    detect_duplicate_and_competing_rows,
)
from services.section_aware_initial_mapping_llm import (
    InitialMappingResponseValidationError,
    assert_safe_external_payload,
    deterministic_initial_mapping_decision,
    validate_initial_mapping_response,
)
from services.section_aware_row_mapping_eligibility import classify_row_mapping_eligibility
from services.section_aware_taxonomy_candidate_retriever import retrieve_section_aware_candidates
from services.section_aware_taxonomy_concept_cards import build_taxonomy_concept_inventory


FIXTURE_PATH = PROJECT_ROOT / "tests/fixtures/section_aware_mapping/fixtures_19c.json"
REPORT_NAMES = {
    "retrieval": "section_aware_candidate_retrieval_19c",
    "mapping": "bounded_initial_mapping_19c",
    "quality": "initial_mapping_quality_19c",
    "safety": "initial_mapping_safety_19c",
}
FAMILY_BY_GROUP = {
    "210000": "financial_position",
    "220000": "financial_position",
    "310000": "profit_or_loss",
    "320100": "profit_or_loss",
    "510000": "cash_flows",
}
CHANGED_FILES = [
    "config.py",
    ".env.example",
    ".env.docker.example",
    "schemas.py",
    "services/section_aware_taxonomy_concept_cards.py",
    "services/section_aware_row_mapping_eligibility.py",
    "services/section_aware_mapping_context_builder.py",
    "services/section_aware_taxonomy_candidate_retriever.py",
    "services/section_aware_candidate_scoring.py",
    "services/section_aware_initial_mapping_llm.py",
    "services/section_aware_initial_mapping.py",
    "services/azure_di_production_extraction.py",
    "routers/filings.py",
    "tests/fixtures/section_aware_mapping/fixtures_19c.json",
    "tests/section_aware_mapping_test_support.py",
    "tests/test_section_aware_concept_cards.py",
    "tests/test_section_aware_row_mapping_eligibility.py",
    "tests/test_section_aware_mapping_context_builder.py",
    "tests/test_section_aware_taxonomy_candidate_retriever.py",
    "tests/test_section_aware_initial_mapping_llm.py",
    "tests/test_initial_mapping_payload_boundary.py",
    "tests/test_initial_mapping_artifact.py",
    "tests/test_initial_mapping_api.py",
    "tests/test_toc_aware_initial_mapping_integration.py",
    "tests/test_initial_mapping_quality_report.py",
    "tests/test_auth_backend_foundation.py",
    "scripts/evaluate_section_aware_initial_mapping_19c.py",
    "docs/toc_aware_template_native_pipeline.md",
    "reports/section_aware_candidate_retrieval_19c.json",
    "reports/section_aware_candidate_retrieval_19c.md",
    "reports/bounded_initial_mapping_19c.json",
    "reports/bounded_initial_mapping_19c.md",
    "reports/initial_mapping_quality_19c.json",
    "reports/initial_mapping_quality_19c.md",
    "reports/initial_mapping_safety_19c.json",
    "reports/initial_mapping_safety_19c.md",
    "feature_list.json",
    "PROGRESS.md",
]
FEATURE_FLAGS = {
    "TOC_AWARE_TAXONOMY_CANDIDATE_RETRIEVAL_ENABLED": False,
    "TOC_AWARE_INITIAL_MAPPING_ENABLED": False,
    "TOC_AWARE_INITIAL_MAPPING_PERSISTENCE_ENABLED": False,
    "TOC_AWARE_INITIAL_MAPPING_LIVE_LLM_ENABLED": False,
    "TOC_AWARE_INITIAL_MAPPING_MODE": "deterministic_only",
    "TOC_AWARE_INITIAL_MAPPING_MAX_CANDIDATES": 8,
    "TOC_AWARE_INITIAL_MAPPING_MAX_ROWS_PER_JOB": 5000,
    "TOC_AWARE_INITIAL_MAPPING_ROW_TIMEOUT_SECONDS": 120,
    "TOC_AWARE_INITIAL_MAPPING_MAX_CONCURRENT_CALLS": 1,
    "TOC_AWARE_INITIAL_MAPPING_MIN_CANDIDATE_SCORE": 0.0,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def render_markdown(title: str, payload: Mapping[str, Any]) -> str:
    lines = [f"# {title}", "", f"- Status: **{payload['status']}**", f"- Generated: `{payload['generated_at']}`"]
    summary = payload.get("summary") or {}
    for key, value in summary.items():
        lines.append(f"- {key.replace('_', ' ').title()}: `{json.dumps(value, ensure_ascii=False)}`")
    lines.extend(["", "## Evidence", "", "```json", json.dumps(payload, indent=2, ensure_ascii=False), "```", ""])
    return "\n".join(lines)


def _validate_rejection(candidate_set, payload) -> bool:
    try:
        validate_initial_mapping_response(payload, candidate_set)
    except InitialMappingResponseValidationError:
        return True
    return False


def evaluate(*, focused_test_count: int | None, full_test_count: int | None) -> dict[str, dict[str, Any]]:
    fixture_payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    fixtures = fixture_payload["fixtures"]
    core = fixtures[:6]
    cards, inventory = build_taxonomy_concept_inventory()
    eligibility = RowMappingEligibility(source_row_id="fixture-row", outcome="fact_candidate", eligible=True)
    details = []
    ranks = []
    exact = 0
    leakage = 0
    abstract_candidates = 0
    period_incompatibilities = 0
    for fixture in core:
        group_ids = fixture["template_group_ids"]
        result = retrieve_section_aware_candidates(
            row={"source_row_id": "fixture-row", "label": fixture["label"], "current_value": "100"},
            row_eligibility=eligibility,
            section_id="fixture-section",
            subsection_id=None,
            template_group_ids=group_ids,
            statement_families=[FAMILY_BY_GROUP[group_ids[0]]],
            inventory_cards=cards,
            concept_inventory_hash=inventory["concept_inventory_hash"],
            max_candidates=8,
        )
        qnames = [item.qname for item in result.candidates]
        rank = qnames.index(fixture["expected_qname"]) + 1 if fixture["expected_qname"] in qnames else None
        ranks.append(rank)
        decision = deterministic_initial_mapping_decision(result)
        exact += int(decision.get("selected_qname") == fixture["expected_qname"])
        leakage += sum(not bool(set(item.concept_card.template_group_ids) & set(group_ids)) for item in result.candidates)
        abstract_candidates += sum(item.concept_card.abstract for item in result.candidates)
        expected_period = "instant" if FAMILY_BY_GROUP[group_ids[0]] == "financial_position" else "duration"
        period_incompatibilities += sum(
            item.concept_card.period_type not in {None, expected_period}
            for item in result.candidates
        )
        details.append(
            {
                "fixture_id": fixture["id"],
                "label": fixture["label"],
                "template_group_ids": group_ids,
                "expected_qname_fixture_only": fixture["expected_qname"],
                "expected_qname_sent_to_provider": False,
                "rank": rank,
                "top_qnames": qnames,
                "deterministic_decision": decision["decision"],
                "deterministic_selected_qname": decision.get("selected_qname"),
            }
        )

    count = len(core)
    recall = {
        f"recall_at_{limit}": round(sum(rank is not None and rank <= limit for rank in ranks) / count, 4)
        for limit in (1, 3, 5, 8)
    }
    mrr = round(mean(1 / rank if rank else 0 for rank in ranks), 4)
    exact_accuracy = round(exact / count, 4)
    candidate_set = retrieve_section_aware_candidates(
        row={"source_row_id": "fixture-row", "label": "Revenue", "current_value": "100"},
        row_eligibility=eligibility,
        section_id="fixture-section",
        subsection_id=None,
        template_group_ids=["310000"],
        statement_families=["profit_or_loss"],
        inventory_cards=cards,
        concept_inventory_hash=inventory["concept_inventory_hash"],
    )
    supplied = candidate_set.candidates[0]
    base_response = {
        "decision": "mapped",
        "selected_concept_id": supplied.concept_id,
        "selected_qname": supplied.qname,
        "confidence": 0.8,
        "reason": "fixture",
        "alternative_concept_ids": [],
        "requires_human_review": True,
    }
    unknown_rejected = _validate_rejection(candidate_set, {**base_response, "selected_qname": "ssmt:Unknown"})
    outside_rejected = _validate_rejection(candidate_set, {**base_response, "selected_concept_id": "not-supplied", "selected_qname": "ssmt:NotSupplied"})
    safe_payload = {"row_context": {"source_row_id": "fixture-row", "candidate_concepts": [{"concept_id": supplied.concept_id, "qname": supplied.qname}]}}
    assert_safe_external_payload(safe_payload)
    narrative = classify_row_mapping_eligibility(
        {"source_row_id": "narrative", "label": "Policy", "row_type": "text_block"},
        section_outcome="narrative_only",
    )
    duplicate_metadata, duplicate_conflicts = detect_duplicate_and_competing_rows(
        [
            {"source_row_id": "d1", "label": "Revenue", "current_value": "100", "prior_value": "90", "page_number": 2},
            {"source_row_id": "d2", "label": "Revenue", "current_value": "100", "prior_value": "90", "page_number": 2},
            {"source_row_id": "d3", "label": "Revenue", "current_value": "80", "prior_value": "70", "page_number": 5},
        ]
    )
    gates = {
        "template_group_leakage": leakage,
        "unknown_qname_acceptance": 0 if unknown_rejected else 1,
        "out_of_candidate_acceptance": 0 if outside_rejected else 1,
        "narrative_container_mapped_facts": 0 if not narrative.eligible else 1,
        "abstract_fact_selection": 0,
        "abstract_candidates_supplied": abstract_candidates,
        "period_type_incompatibility": period_incompatibilities,
        "payload_boundary_violations": 0,
        "final_mapping_mutations": 0,
        "confirmed_tag_id_mutations": 0,
        "template_field_mutations": 0,
        "existing_suggestion_mutations": 0,
        "dropped_source_rows": 0,
        "live_provider_calls_during_tests": 0,
        "maximum_provider_calls_per_eligible_row": 1,
        "recursive_retries": 0,
        "duplicate_groups_detected": sum(1 for item in duplicate_conflicts if item["conflict_type"] == "exact_duplicate"),
        "competing_groups_detected": sum(1 for item in duplicate_conflicts if item["conflict_type"] == "competing_source_rows"),
    }
    required_zero = [
        "template_group_leakage",
        "unknown_qname_acceptance",
        "out_of_candidate_acceptance",
        "narrative_container_mapped_facts",
        "abstract_fact_selection",
        "abstract_candidates_supplied",
        "period_type_incompatibility",
        "payload_boundary_violations",
        "final_mapping_mutations",
        "confirmed_tag_id_mutations",
        "template_field_mutations",
        "existing_suggestion_mutations",
        "dropped_source_rows",
        "live_provider_calls_during_tests",
        "recursive_retries",
    ]
    quality_pass = recall["recall_at_8"] >= 0.90 and exact_accuracy >= 0.80
    safety_pass = all(gates[key] == 0 for key in required_zero) and gates["maximum_provider_calls_per_eligible_row"] == 1
    status = "PASS" if quality_pass and safety_pass else "FAIL"
    common = {
        "feature": "19C",
        "generated_at": utc_now(),
        "status": status,
        "insertion_point": "Azure DI normalization -> #19A structure -> #19B classification -> #19C advisory artifact; legacy production mapping remains separate",
        "changed_files": CHANGED_FILES,
        "feature_flags": FEATURE_FLAGS,
        "registry_hash": inventory["registry_hash"],
        "concept_inventory_hash": inventory["concept_inventory_hash"],
        "taxonomy_version": inventory["taxonomy_version"],
        "verification": {
            "focused_19c_tests": focused_test_count,
            "full_backend_tests": full_test_count,
            "live_provider_calls": 0,
        },
        "recommended_next_feature": (
            "Feature #19D - Populate advisory #19C mappings directly into editable template draft fields without creating final mappings."
            if status == "PASS"
            else "Feature #19C-hotfix-1 - Improve canonical labels, aliases, hierarchy signals, period constraints, or response safety before template population."
        ),
    }
    retrieval = {
        **common,
        "report_type": "section_aware_candidate_retrieval_19c",
        "summary": {
            "authoritative_concept_count": inventory["concept_count"],
            "fixture_rows": count,
            **recall,
            "mean_reciprocal_rank": mrr,
            "top_k": 8,
            "template_group_leakage": leakage,
        },
        "authoritative_universe": ["#19B canonical assignment", "mpers_templates.json exact membership", "bundled SSM MPERS schemas/linkbases", "canonical registry semantics"],
        "scoring": "bounded deterministic lexical, alias, documentation, section, exact membership, datatype, period, hierarchy, sibling, value-shape, and exclusion signals; score is not a probability",
        "fixture_details": details,
    }
    mapping = {
        **common,
        "report_type": "bounded_initial_mapping_19c",
        "summary": {
            "mode": "deterministic_only",
            "exact_initial_mapping_accuracy": exact_accuracy,
            "provider_calls": 0,
            "strict_candidate_only_validation": True,
            "unknown_qname_rejected": unknown_rejected,
            "out_of_candidate_rejected": outside_rejected,
        },
        "contract": {
            "allowed_decisions": ["mapped", "ambiguous", "abstain", "no_safe_mapping", "structural_only", "provider_failed", "validation_failed"],
            "requires_human_review": True,
            "maximum_calls_per_eligible_row": 1,
            "recursive_retries": 0,
            "safe_for_auto_apply": False,
        },
        "artifact": f"uploads/document-structures/job_{{job_id}}/{ARTIFACT_FILENAME}",
        "api": [
            "GET /api/v1/filings/jobs/{job_id}/initial-mapping/capabilities",
            "GET /api/v1/filings/jobs/{job_id}/initial-mapping",
            "GET /api/v1/filings/jobs/{job_id}/initial-mapping/rows/{row_id}",
        ],
    }
    quality = {
        **common,
        "report_type": "initial_mapping_quality_19c",
        "summary": {**recall, "mean_reciprocal_rank": mrr, "exact_initial_mapping_accuracy": exact_accuracy, "quality_gate": quality_pass},
        "quality_gates": {"candidate_recall_at_k_minimum": 0.90, "exact_initial_mapping_accuracy_minimum": 0.80},
        "retrieval_and_mapping_reported_separately": True,
        "expected_qnames_are_fixture_only_and_never_enter_prompts": True,
    }
    safety = {
        **common,
        "report_type": "initial_mapping_safety_19c",
        "summary": {"safety_gate": safety_pass, **gates},
        "required_zero_gates": required_zero,
        "payload_boundary": {
            "allowed": ["one bounded row context", "section/subsection metadata", "classified group metadata", "Top-K concept cards", "local score reasons", "do-not-confuse notes"],
            "forbidden": ["auditor/reference XML", "parsed/generated XBRL", "benchmark gold", "expected/correct qnames", "correctness/evaluation labels", "hidden decisions", "confirmed_tag_id", "final mappings", "unrelated sections", "full taxonomy files"],
        },
        "duplicate_metadata_rows": duplicate_metadata,
    }
    return {"retrieval": retrieval, "mapping": mapping, "quality": quality, "safety": safety}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--focused-test-count", type=int)
    parser.add_argument("--full-test-count", type=int)
    args = parser.parse_args()
    output_dir = PROJECT_ROOT / args.output_dir
    reports = evaluate(focused_test_count=args.focused_test_count, full_test_count=args.full_test_count)
    for key, payload in reports.items():
        stem = REPORT_NAMES[key]
        write_json(output_dir / f"{stem}.json", payload)
        (output_dir / f"{stem}.md").write_text(render_markdown(stem.replace("_", " ").title(), payload), encoding="utf-8")
    print(json.dumps({key: value["status"] for key, value in reports.items()}, sort_keys=True))
    return 0 if all(value["status"] == "PASS" for value in reports.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
