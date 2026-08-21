"""Run #14D targeted Azure DI mapping refinement and simulation reports."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.azure_di_concept_metadata_enricher_v2 import (  # noqa: E402
    build_enriched_concept_metadata_v2,
    build_refinement_comparison_14d,
    no_side_effect_metadata,
    render_enrichment_v2_markdown,
    render_refinement_comparison_14d_markdown,
)
from services.azure_di_mapping_candidate_generator import (  # noqa: E402
    generate_mapping_candidate_reports,
    render_candidates_markdown,
    render_confidence_markdown,
    render_gap_analysis_markdown,
)
from services.azure_di_manual_mapping_review import (  # noqa: E402
    build_manual_mapping_review_reports,
    render_queue_markdown,
)
from services.azure_di_reviewed_mapping_simulator import (  # noqa: E402
    SimulationPolicy,
    build_reviewed_mapping_simulation_reports,
    render_decisions_markdown,
    render_eligibility_markdown,
    render_handoff_markdown,
)


DEFAULT_MAPPING_REPORT = Path("reports/azure_di_mapping_candidates_14a.json")
DEFAULT_CONFIDENCE_REPORT = Path("reports/azure_di_mapping_confidence_14a.json")
DEFAULT_GAP_REPORT = Path("reports/azure_di_mapping_gap_analysis_14a.json")
DEFAULT_REVIEW_QUEUE = Path("reports/azure_di_manual_mapping_review_queue_14b.json")
DEFAULT_DECISIONS_REPORT = Path("reports/azure_di_reviewed_mapping_decisions_14c.json")
DEFAULT_14C_ELIGIBILITY = Path("reports/azure_di_xbrl_eligibility_summary_14c.json")
DEFAULT_HANDOFF_REPORT = Path("reports/azure_di_normalized_mapping_handoff_13y.json")
DEFAULT_REFERENCE_REPORT = Path("reports/reference_xbrl_report_20260511T082343Z.json")
DEFAULT_OUTPUT_DIR = Path("reports")


@dataclass(frozen=True)
class Refinement14DOutputPaths:
    enrichment_json: Path
    enrichment_md: Path
    candidates_json: Path
    candidates_md: Path
    confidence_json: Path
    confidence_md: Path
    gap_json: Path
    gap_md: Path
    review_queue_json: Path
    review_queue_md: Path
    decisions_json: Path
    decisions_md: Path
    handoff_json: Path
    handoff_md: Path
    eligibility_json: Path
    eligibility_md: Path
    comparison_json: Path
    comparison_md: Path


def output_paths_from_prefix(output_prefix: str | Path | None = None) -> Refinement14DOutputPaths:
    if output_prefix is None:
        root = DEFAULT_OUTPUT_DIR
        return Refinement14DOutputPaths(
            enrichment_json=root / "azure_di_concept_metadata_enrichment_14d.json",
            enrichment_md=root / "azure_di_concept_metadata_enrichment_14d.md",
            candidates_json=root / "azure_di_mapping_candidates_14d.json",
            candidates_md=root / "azure_di_mapping_candidates_14d.md",
            confidence_json=root / "azure_di_mapping_confidence_14d.json",
            confidence_md=root / "azure_di_mapping_confidence_14d.md",
            gap_json=root / "azure_di_mapping_gap_analysis_14d.json",
            gap_md=root / "azure_di_mapping_gap_analysis_14d.md",
            review_queue_json=root / "azure_di_manual_mapping_review_queue_14d.json",
            review_queue_md=root / "azure_di_manual_mapping_review_queue_14d.md",
            decisions_json=root / "azure_di_reviewed_mapping_decisions_14d.json",
            decisions_md=root / "azure_di_reviewed_mapping_decisions_14d.md",
            handoff_json=root / "azure_di_reviewed_mapping_handoff_14d.json",
            handoff_md=root / "azure_di_reviewed_mapping_handoff_14d.md",
            eligibility_json=root / "azure_di_xbrl_eligibility_summary_14d.json",
            eligibility_md=root / "azure_di_xbrl_eligibility_summary_14d.md",
            comparison_json=root / "azure_di_refinement_comparison_14d.json",
            comparison_md=root / "azure_di_refinement_comparison_14d.md",
        )
    prefix = Path(output_prefix)
    return Refinement14DOutputPaths(
        enrichment_json=Path(f"{prefix}_concept_metadata_enrichment_14d.json"),
        enrichment_md=Path(f"{prefix}_concept_metadata_enrichment_14d.md"),
        candidates_json=Path(f"{prefix}_mapping_candidates_14d.json"),
        candidates_md=Path(f"{prefix}_mapping_candidates_14d.md"),
        confidence_json=Path(f"{prefix}_mapping_confidence_14d.json"),
        confidence_md=Path(f"{prefix}_mapping_confidence_14d.md"),
        gap_json=Path(f"{prefix}_mapping_gap_analysis_14d.json"),
        gap_md=Path(f"{prefix}_mapping_gap_analysis_14d.md"),
        review_queue_json=Path(f"{prefix}_manual_mapping_review_queue_14d.json"),
        review_queue_md=Path(f"{prefix}_manual_mapping_review_queue_14d.md"),
        decisions_json=Path(f"{prefix}_reviewed_mapping_decisions_14d.json"),
        decisions_md=Path(f"{prefix}_reviewed_mapping_decisions_14d.md"),
        handoff_json=Path(f"{prefix}_reviewed_mapping_handoff_14d.json"),
        handoff_md=Path(f"{prefix}_reviewed_mapping_handoff_14d.md"),
        eligibility_json=Path(f"{prefix}_xbrl_eligibility_summary_14d.json"),
        eligibility_md=Path(f"{prefix}_xbrl_eligibility_summary_14d.md"),
        comparison_json=Path(f"{prefix}_refinement_comparison_14d.json"),
        comparison_md=Path(f"{prefix}_refinement_comparison_14d.md"),
    )


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def _retag(report: dict[str, Any], *, report_type: str, output_path: Path, run_id: str | None) -> None:
    report["run_metadata"] = {
        **dict(report.get("run_metadata") or {}),
        **no_side_effect_metadata(),
        "run_id": run_id,
        "report_type": report_type,
        "script": "scripts/refine_azure_di_mapping_candidates_14d.py",
        "output_path": str(output_path),
    }
    report["source_feature_chain"] = ["13X", "13Y", "13Z", "14A", "14B", "14C", "14D"]


def _retag_review_queue(queue: dict[str, Any], *, run_id: str | None, output_path: Path) -> None:
    _retag(queue, report_type="azure_di_manual_mapping_review_queue", output_path=output_path, run_id=run_id)
    for index, item in enumerate(queue.get("queue_items") or [], start=1):
        item["review_mapping_item_id"] = f"14D-REVIEW-{index:04d}"
        audit = dict(item.get("audit_trail") or {})
        audit["source"] = "14D_report_based_manual_mapping_review_from_refined_candidates"
        audit["final_mapping_approved"] = False
        item["audit_trail"] = audit


def _retag_simulation_reports(
    decisions: dict[str, Any],
    handoff: dict[str, Any],
    eligibility: dict[str, Any],
    policy: dict[str, Any],
    *,
    run_id: str | None,
    paths: Refinement14DOutputPaths,
) -> None:
    _retag(decisions, report_type="azure_di_reviewed_mapping_decisions", output_path=paths.decisions_json, run_id=run_id)
    _retag(handoff, report_type="azure_di_reviewed_mapping_handoff", output_path=paths.handoff_json, run_id=run_id)
    _retag(eligibility, report_type="azure_di_xbrl_eligibility_summary", output_path=paths.eligibility_json, run_id=run_id)
    _retag(policy, report_type="azure_di_review_simulation_policy", output_path=paths.eligibility_json, run_id=run_id)
    for index, decision in enumerate(decisions.get("simulated_decisions") or [], start=1):
        decision["simulated_decision_id"] = f"14D-SIM-{index:04d}"
        audit = dict(decision.get("audit_trail") or {})
        audit["source"] = "14D_report_based_reviewed_mapping_simulator"
        audit["simulated_only"] = True
        audit["human_approved"] = False
        audit["production_mapping_approved"] = False
        decision["audit_trail"] = audit
        decision["simulated_only"] = True
        decision["human_approved"] = False
        if isinstance(decision.get("reviewer_notes"), str):
            decision["reviewer_notes"] = decision["reviewer_notes"].replace("#14C", "#14D")
    decisions_by_mapping_id = {
        decision.get("mapping_input_id"): decision for decision in decisions.get("simulated_decisions") or []
    }
    for index, item in enumerate(handoff.get("handoff_items") or [], start=1):
        item["reviewed_mapping_id"] = f"14D-REVIEWED-MAP-{index:04d}"
        source_decision = decisions_by_mapping_id.get(item.get("mapping_input_id"))
        if source_decision:
            item["simulated_decision_id"] = source_decision.get("simulated_decision_id")
        audit = dict(item.get("audit_trail") or {})
        audit["source"] = "14D_simulated_reviewed_mapping_handoff"
        if source_decision:
            audit["source_simulated_decision_id"] = source_decision.get("simulated_decision_id")
        audit["simulated_only"] = True
        audit["human_approved"] = False
        audit["production_mapping_approved"] = False
        item["audit_trail"] = audit
        item["simulated_only"] = True
        item["human_approved"] = False


def _augment_confidence(confidence: dict[str, Any], baseline: Mapping[str, Any], refined: Mapping[str, Any]) -> None:
    before = dict(baseline.get("status_counts") or {})
    after = dict(refined.get("status_counts") or {})
    confidence["baseline_14a_status_counts"] = before
    confidence["after_14d_status_counts"] = after
    confidence["before_after_confidence_comparison"] = {
        key: {"before": int(before.get(key) or 0), "after": int(after.get(key) or 0), "delta": int(after.get(key) or 0) - int(before.get(key) or 0)}
        for key in sorted(set(before) | set(after))
    }


def _augment_gap(gap: dict[str, Any], candidates: Mapping[str, Any], enrichment: Mapping[str, Any]) -> None:
    records = list(candidates.get("mapping_records") or [])
    gap["labels_still_ambiguous"] = [
        {
            "mapping_input_id": record.get("mapping_input_id"),
            "label": record.get("label"),
            "row_type": record.get("row_type"),
            "suggestions": record.get("suggestions") or [],
        }
        for record in records
        if record.get("mapping_status") == "ambiguous_multiple_suggestions"
    ]
    gap["alias_gaps_v2"] = enrichment.get("unresolved_aliases") or []
    gap["blocker_diagnosis"] = enrichment.get("blocker_diagnosis") or {}
    gap["recommended_next_feature"] = "Feature #14E - Reviewed mapping quality evaluation against reference XML, no DB mutation."


def _retag_mapping_records(candidates: dict[str, Any]) -> None:
    for record in candidates.get("mapping_records") or []:
        audit = dict(record.get("audit_trail") or {})
        audit["source"] = "14D_enriched_v2_deterministic_report_based_mapping_suggestion"
        audit["baseline_source_feature"] = "14A"
        audit["mapping_decision_status"] = "suggested_only"
        audit["final_mapping_approved"] = False
        record["audit_trail"] = audit
        for suggestion in record.get("suggestions") or []:
            suggestion["mapping_decision_status"] = "suggested_only"


def _feature_markdown(text: str) -> str:
    return text.replace("Feature #14B", "Feature #14D").replace("Feature #14C", "Feature #14D")


def run_refinement_14d(
    *,
    mapping_report_path: str | Path = DEFAULT_MAPPING_REPORT,
    confidence_report_path: str | Path = DEFAULT_CONFIDENCE_REPORT,
    gap_report_path: str | Path = DEFAULT_GAP_REPORT,
    review_queue_path: str | Path = DEFAULT_REVIEW_QUEUE,
    decisions_report_path: str | Path = DEFAULT_DECISIONS_REPORT,
    handoff_report_path: str | Path = DEFAULT_HANDOFF_REPORT,
    reference_report_path: str | Path | None = DEFAULT_REFERENCE_REPORT,
    run_id: str | None = "azure_di_metadata_enrichment_v2_14d",
    output_prefix: str | Path | None = None,
) -> dict[str, Any]:
    paths = output_paths_from_prefix(output_prefix)
    mapping_path = Path(mapping_report_path)
    confidence_path = Path(confidence_report_path)
    gap_path = Path(gap_report_path)
    review_path = Path(review_queue_path)
    decisions_path = Path(decisions_report_path)
    handoff_path = Path(handoff_report_path)
    reference_path = Path(reference_report_path) if reference_report_path else None
    eligibility_path = PROJECT_ROOT / DEFAULT_14C_ELIGIBILITY

    mapping_14a = _load_json(mapping_path)
    confidence_14a = _load_json(confidence_path)
    gap_14a = _load_json(gap_path)
    review_14b = _load_json(review_path)
    decisions_14c = _load_json(decisions_path)
    eligibility_14c = _load_json(eligibility_path) if eligibility_path.exists() else {}
    handoff_13y = _load_json(handoff_path)
    input_paths = {
        "mapping_report": str(mapping_path),
        "confidence_report": str(confidence_path),
        "gap_report": str(gap_path),
        "review_queue": str(review_path),
        "decisions_report": str(decisions_path),
        "handoff_report": str(handoff_path),
        "reference_report": str(reference_path) if reference_path else None,
        "baseline_14c_eligibility": str(eligibility_path) if eligibility_path.exists() else None,
        "template_file": "mpers_templates.json",
    }

    concepts, enrichment = build_enriched_concept_metadata_v2(
        reference_report_path=str(reference_path) if reference_path else None,
        run_id=run_id,
        input_paths=input_paths,
        decisions_report=decisions_14c,
        mapping_report=mapping_14a,
        review_queue=review_14b,
    )
    _retag(enrichment, report_type="azure_di_concept_metadata_enrichment_v2", output_path=paths.enrichment_json, run_id=run_id)

    candidates, confidence, gap = generate_mapping_candidate_reports(
        handoff_report=handoff_13y,
        concept_metadata=concepts,
        concept_metadata_limitations=enrichment.get("metadata_limitations") or [],
        input_paths=input_paths,
        run_id=run_id,
    )
    _retag(candidates, report_type="azure_di_mapping_candidates", output_path=paths.candidates_json, run_id=run_id)
    _retag(confidence, report_type="azure_di_mapping_confidence", output_path=paths.confidence_json, run_id=run_id)
    _retag(gap, report_type="azure_di_mapping_gap_analysis", output_path=paths.gap_json, run_id=run_id)
    candidates["concept_metadata"] = {
        "source": "14D enriched local metadata v2 plus optional offline reference concept inventory",
        "concept_count": enrichment.get("concept_count", 0),
        "alias_count": enrichment.get("alias_count", 0),
        "curated_alias_count": enrichment.get("curated_alias_count", 0),
        "unresolved_alias_count": enrichment.get("unresolved_alias_count", 0),
        "limitations": enrichment.get("metadata_limitations") or [],
    }
    candidates["limitations"] = [
        "Deterministic enriched local metadata suggestions only; no final mapping is approved.",
        "No semantic matcher, embeddings, LLM, Azure DI, Hugging Face, OpenAI, DB mutation, XBRL generation, or Arelle validation is used.",
        "Reference report, when provided, is used only as offline concept inventory/gap context and not as a direct answer key.",
    ]
    _retag_mapping_records(candidates)
    _augment_confidence(confidence, mapping_14a, candidates)
    _augment_gap(gap, candidates, enrichment)

    queue, policy, contract, summary = build_manual_mapping_review_reports(
        mapping_report=candidates,
        confidence_report=confidence,
        gap_report=gap,
        run_id=run_id,
        input_paths=input_paths,
    )
    _retag_review_queue(queue, run_id=run_id, output_path=paths.review_queue_json)
    _retag(policy, report_type="azure_di_mapping_review_policy_in_memory_for_14d_simulation", output_path=paths.review_queue_json, run_id=run_id)
    _retag(contract, report_type="azure_di_mapping_review_handoff_contract_in_memory_for_14d_simulation", output_path=paths.review_queue_json, run_id=run_id)
    _retag(summary, report_type="azure_di_mapping_review_summary_in_memory_for_14d_simulation", output_path=paths.review_queue_json, run_id=run_id)

    decisions, handoff, eligibility, simulation_policy = build_reviewed_mapping_simulation_reports(
        review_queue=queue,
        review_policy=policy,
        handoff_contract=contract,
        run_id=run_id,
        input_paths=input_paths,
        simulation_policy=SimulationPolicy(),
    )
    _retag_simulation_reports(decisions, handoff, eligibility, simulation_policy, run_id=run_id, paths=paths)

    comparison = build_refinement_comparison_14d(
        baseline_14a_candidates=mapping_14a,
        baseline_14c_decisions=decisions_14c,
        baseline_14c_eligibility=eligibility_14c,
        refined_14d_candidates=candidates,
        refined_14d_queue=queue,
        refined_14d_decisions=decisions,
        refined_14d_eligibility=eligibility,
        enrichment_report=enrichment,
        input_paths=input_paths,
        run_id=run_id,
    )
    _retag(comparison, report_type="azure_di_refinement_comparison", output_path=paths.comparison_json, run_id=run_id)

    _write_json(paths.enrichment_json, enrichment)
    _write_text(paths.enrichment_md, render_enrichment_v2_markdown(enrichment))
    _write_json(paths.candidates_json, candidates)
    _write_text(paths.candidates_md, render_candidates_markdown(candidates))
    _write_json(paths.confidence_json, confidence)
    _write_text(paths.confidence_md, render_confidence_markdown(confidence))
    _write_json(paths.gap_json, gap)
    _write_text(paths.gap_md, render_gap_analysis_markdown(gap))
    _write_json(paths.review_queue_json, queue)
    _write_text(paths.review_queue_md, _feature_markdown(render_queue_markdown(queue)))
    _write_json(paths.decisions_json, decisions)
    _write_text(paths.decisions_md, _feature_markdown(render_decisions_markdown(decisions)))
    _write_json(paths.handoff_json, handoff)
    _write_text(paths.handoff_md, _feature_markdown(render_handoff_markdown(handoff)))
    _write_json(paths.eligibility_json, eligibility)
    _write_text(paths.eligibility_md, _feature_markdown(render_eligibility_markdown(eligibility)))
    _write_json(paths.comparison_json, comparison)
    _write_text(paths.comparison_md, render_refinement_comparison_14d_markdown(comparison))

    return {
        "paths": paths,
        "enrichment_report": enrichment,
        "candidates_report": candidates,
        "confidence_report": confidence,
        "gap_report": gap,
        "review_queue_report": queue,
        "review_summary_report": summary,
        "decisions_report": decisions,
        "handoff_report": handoff,
        "eligibility_report": eligibility,
        "comparison_report": comparison,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run #14D targeted concept metadata enrichment v2 and report-only mapping refinement."
    )
    parser.add_argument("--mapping-report", type=Path, default=PROJECT_ROOT / DEFAULT_MAPPING_REPORT)
    parser.add_argument("--confidence-report", type=Path, default=PROJECT_ROOT / DEFAULT_CONFIDENCE_REPORT)
    parser.add_argument("--gap-report", type=Path, default=PROJECT_ROOT / DEFAULT_GAP_REPORT)
    parser.add_argument("--review-queue", type=Path, default=PROJECT_ROOT / DEFAULT_REVIEW_QUEUE)
    parser.add_argument("--decisions-report", type=Path, default=PROJECT_ROOT / DEFAULT_DECISIONS_REPORT)
    parser.add_argument("--handoff-report", type=Path, default=PROJECT_ROOT / DEFAULT_HANDOFF_REPORT)
    parser.add_argument("--reference-report", type=Path, default=PROJECT_ROOT / DEFAULT_REFERENCE_REPORT)
    parser.add_argument("--run-id", default="azure_di_metadata_enrichment_v2_14d")
    parser.add_argument("--output-prefix", type=Path)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_refinement_14d(
        mapping_report_path=args.mapping_report,
        confidence_report_path=args.confidence_report,
        gap_report_path=args.gap_report,
        review_queue_path=args.review_queue,
        decisions_report_path=args.decisions_report,
        handoff_report_path=args.handoff_report,
        reference_report_path=args.reference_report,
        run_id=args.run_id,
        output_prefix=args.output_prefix,
    )
    paths = result["paths"]
    candidates = result["candidates_report"]
    enrichment = result["enrichment_report"]
    eligibility = result["eligibility_report"]
    comparison = result["comparison_report"]
    print(f"Azure DI concept metadata enrichment v2 report: {paths.enrichment_json}")
    print(f"Azure DI mapping candidates #14D report: {paths.candidates_json}")
    print(f"Azure DI mapping confidence #14D report: {paths.confidence_json}")
    print(f"Azure DI mapping gap analysis #14D report: {paths.gap_json}")
    print(f"Azure DI manual mapping review queue #14D report: {paths.review_queue_json}")
    print(f"Azure DI simulated decisions #14D report: {paths.decisions_json}")
    print(f"Azure DI simulated handoff #14D report: {paths.handoff_json}")
    print(f"Azure DI XBRL eligibility #14D report: {paths.eligibility_json}")
    print(f"Azure DI refinement comparison #14D report: {paths.comparison_json}")
    print(f"Mapping records: {candidates.get('mapping_record_count', 0)}")
    print(f"Status counts: {candidates.get('status_counts', {})}")
    print(f"Curated v2 aliases attached: {enrichment.get('curated_alias_count', 0)}")
    print(f"#14D simulated XBRL eligible: {eligibility.get('xbrl_eligible_count', 0)}")
    print(f"Recommended next feature: {comparison.get('recommended_next_feature')}")
    if args.verbose:
        print(render_refinement_comparison_14d_markdown(comparison).split("## Cautionary Notes", 1)[0].strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
