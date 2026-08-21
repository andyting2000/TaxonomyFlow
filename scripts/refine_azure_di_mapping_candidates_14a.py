"""Refine Azure DI mapping suggestions with local concept metadata enrichment."""

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

from services.azure_di_concept_metadata_enricher import (  # noqa: E402
    DEFAULT_REFERENCE_REPORT,
    build_enriched_concept_metadata,
    build_refinement_comparison_report,
    no_side_effect_metadata,
    recommend_next_feature,
    render_enrichment_markdown,
    render_refinement_comparison_markdown,
)
from services.azure_di_mapping_candidate_generator import (  # noqa: E402
    DEFAULT_HANDOFF_REPORT,
    generate_mapping_candidate_reports,
    render_candidates_markdown,
    render_confidence_markdown,
    render_gap_analysis_markdown,
)


DEFAULT_BASELINE_MAPPING = Path("reports/azure_di_mapping_candidates_13z.json")
DEFAULT_BASELINE_CONFIDENCE = Path("reports/azure_di_mapping_confidence_13z.json")
DEFAULT_OUTPUT_DIR = Path("reports")


@dataclass(frozen=True)
class RefinementOutputPaths:
    candidates_json: Path
    candidates_md: Path
    confidence_json: Path
    confidence_md: Path
    gap_json: Path
    gap_md: Path
    comparison_json: Path
    comparison_md: Path
    enrichment_json: Path
    enrichment_md: Path


def output_paths_from_prefix(output_prefix: str | Path | None = None) -> RefinementOutputPaths:
    if output_prefix is None:
        root = DEFAULT_OUTPUT_DIR
        return RefinementOutputPaths(
            candidates_json=root / "azure_di_mapping_candidates_14a.json",
            candidates_md=root / "azure_di_mapping_candidates_14a.md",
            confidence_json=root / "azure_di_mapping_confidence_14a.json",
            confidence_md=root / "azure_di_mapping_confidence_14a.md",
            gap_json=root / "azure_di_mapping_gap_analysis_14a.json",
            gap_md=root / "azure_di_mapping_gap_analysis_14a.md",
            comparison_json=root / "azure_di_mapping_refinement_comparison_14a.json",
            comparison_md=root / "azure_di_mapping_refinement_comparison_14a.md",
            enrichment_json=root / "azure_di_concept_metadata_enrichment_14a.json",
            enrichment_md=root / "azure_di_concept_metadata_enrichment_14a.md",
        )
    prefix = Path(output_prefix)
    return RefinementOutputPaths(
        candidates_json=Path(f"{prefix}_mapping_candidates_14a.json"),
        candidates_md=Path(f"{prefix}_mapping_candidates_14a.md"),
        confidence_json=Path(f"{prefix}_mapping_confidence_14a.json"),
        confidence_md=Path(f"{prefix}_mapping_confidence_14a.md"),
        gap_json=Path(f"{prefix}_mapping_gap_analysis_14a.json"),
        gap_md=Path(f"{prefix}_mapping_gap_analysis_14a.md"),
        comparison_json=Path(f"{prefix}_mapping_refinement_comparison_14a.json"),
        comparison_md=Path(f"{prefix}_mapping_refinement_comparison_14a.md"),
        enrichment_json=Path(f"{prefix}_concept_metadata_enrichment_14a.json"),
        enrichment_md=Path(f"{prefix}_concept_metadata_enrichment_14a.md"),
    )


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _retag(report: dict[str, Any], *, report_type: str, output_path: Path, run_id: str | None) -> None:
    metadata = {
        **no_side_effect_metadata(),
        **dict(report.get("run_metadata") or {}),
        **no_side_effect_metadata(),
        "run_id": run_id,
        "report_type": report_type,
        "script": "scripts/refine_azure_di_mapping_candidates_14a.py",
        "output_path": str(output_path),
    }
    report["run_metadata"] = metadata
    report["source_feature_chain"] = ["13X", "13Y", "13Z", "14A"]


def _augment_confidence_report(
    confidence: dict[str, Any],
    *,
    baseline_candidates: Mapping[str, Any],
    baseline_confidence: Mapping[str, Any],
    refined_candidates: Mapping[str, Any],
) -> None:
    baseline_status = dict(baseline_candidates.get("status_counts") or baseline_confidence.get("status_counts") or {})
    refined_status = dict(refined_candidates.get("status_counts") or {})
    confidence["baseline_13z_status_counts"] = baseline_status
    confidence["after_14a_status_counts"] = refined_status
    confidence["before_after_confidence_comparison"] = {
        key: {
            "before": int(baseline_status.get(key) or 0),
            "after": int(refined_status.get(key) or 0),
            "delta": int(refined_status.get(key) or 0) - int(baseline_status.get(key) or 0),
        }
        for key in sorted(set(baseline_status) | set(refined_status))
    }


def _augment_gap_report(gap: dict[str, Any], *, candidates: Mapping[str, Any], enrichment: Mapping[str, Any]) -> None:
    records = list(candidates.get("mapping_records") or [])
    gap["labels_still_ambiguous"] = [
        {
            "mapping_input_id": record.get("mapping_input_id"),
            "label": record.get("label"),
            "row_type": record.get("row_type"),
            "suggestions": record.get("suggestions"),
        }
        for record in records
        if record.get("mapping_status") == "ambiguous_multiple_suggestions"
    ]
    gap["alias_gaps"] = enrichment.get("unresolved_aliases") or []
    gap["concept_metadata_gaps"] = {
        "unresolved_alias_count": enrichment.get("unresolved_alias_count", 0),
        "metadata_limitations": enrichment.get("metadata_limitations") or [],
    }
    gap["recommended_next_feature"] = recommend_next_feature(candidates)


def run_refinement(
    *,
    handoff_report_path: str | Path = DEFAULT_HANDOFF_REPORT,
    baseline_mapping_report_path: str | Path = DEFAULT_BASELINE_MAPPING,
    baseline_confidence_report_path: str | Path = DEFAULT_BASELINE_CONFIDENCE,
    reference_report_path: str | Path | None = DEFAULT_REFERENCE_REPORT,
    run_id: str | None = "azure_di_mapping_refinement_14a",
    output_prefix: str | Path | None = None,
) -> dict[str, Any]:
    handoff_path = Path(handoff_report_path)
    baseline_mapping_path = Path(baseline_mapping_report_path)
    baseline_confidence_path = Path(baseline_confidence_report_path)
    reference_path = Path(reference_report_path) if reference_report_path else None
    paths = output_paths_from_prefix(output_prefix)

    handoff_report = _load_json(handoff_path)
    baseline_mapping = _load_json(baseline_mapping_path)
    baseline_confidence = _load_json(baseline_confidence_path)
    input_paths = {
        "handoff_report": str(handoff_path),
        "baseline_mapping_report": str(baseline_mapping_path),
        "baseline_confidence_report": str(baseline_confidence_path),
        "reference_report": str(reference_path) if reference_path else None,
        "template_file": "mpers_templates.json",
    }
    concepts, enrichment = build_enriched_concept_metadata(
        reference_report_path=reference_path,
        run_id=run_id,
        input_paths=input_paths,
    )
    _retag(enrichment, report_type="azure_di_concept_metadata_enrichment", output_path=paths.enrichment_json, run_id=run_id)

    candidates, confidence, gap = generate_mapping_candidate_reports(
        handoff_report=handoff_report,
        concept_metadata=concepts,
        concept_metadata_limitations=enrichment.get("metadata_limitations") or [],
        input_paths=input_paths,
        run_id=run_id,
    )
    _retag(candidates, report_type="azure_di_mapping_candidates", output_path=paths.candidates_json, run_id=run_id)
    _retag(confidence, report_type="azure_di_mapping_confidence", output_path=paths.confidence_json, run_id=run_id)
    _retag(gap, report_type="azure_di_mapping_gap_analysis", output_path=paths.gap_json, run_id=run_id)
    candidates["concept_metadata"] = {
        "source": "local enriched mpers_templates.json metadata plus optional reference concept inventory",
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
    for record in candidates.get("mapping_records") or []:
        audit = dict(record.get("audit_trail") or {})
        audit["source"] = "14A_enriched_deterministic_report_based_mapping_suggestion"
        audit["baseline_source_feature"] = "13Z"
        audit["mapping_decision_status"] = "suggested_only"
        audit["final_mapping_approved"] = False
        record["audit_trail"] = audit
    _augment_confidence_report(
        confidence,
        baseline_candidates=baseline_mapping,
        baseline_confidence=baseline_confidence,
        refined_candidates=candidates,
    )
    _augment_gap_report(gap, candidates=candidates, enrichment=enrichment)
    comparison = build_refinement_comparison_report(
        baseline_candidates_report=baseline_mapping,
        baseline_confidence_report=baseline_confidence,
        refined_candidates_report=candidates,
        enrichment_report=enrichment,
        input_paths=input_paths,
        run_id=run_id,
    )
    _retag(comparison, report_type="azure_di_mapping_refinement_comparison", output_path=paths.comparison_json, run_id=run_id)

    _write_json(paths.candidates_json, candidates)
    _write_text(paths.candidates_md, render_candidates_markdown(candidates))
    _write_json(paths.confidence_json, confidence)
    _write_text(paths.confidence_md, render_confidence_markdown(confidence))
    _write_json(paths.gap_json, gap)
    _write_text(paths.gap_md, render_gap_analysis_markdown(gap))
    _write_json(paths.comparison_json, comparison)
    _write_text(paths.comparison_md, render_refinement_comparison_markdown(comparison))
    _write_json(paths.enrichment_json, enrichment)
    _write_text(paths.enrichment_md, render_enrichment_markdown(enrichment))

    return {
        "paths": paths,
        "candidates_report": candidates,
        "confidence_report": confidence,
        "gap_report": gap,
        "comparison_report": comparison,
        "enrichment_report": enrichment,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refine Azure DI #13Y handoff mapping suggestions with local concept metadata enrichment."
    )
    parser.add_argument("--handoff-report", type=Path, default=PROJECT_ROOT / DEFAULT_HANDOFF_REPORT)
    parser.add_argument("--baseline-mapping-report", type=Path, default=PROJECT_ROOT / DEFAULT_BASELINE_MAPPING)
    parser.add_argument("--baseline-confidence-report", type=Path, default=PROJECT_ROOT / DEFAULT_BASELINE_CONFIDENCE)
    parser.add_argument("--reference-report", type=Path, default=PROJECT_ROOT / DEFAULT_REFERENCE_REPORT)
    parser.add_argument("--run-id", default="azure_di_mapping_refinement_14a")
    parser.add_argument("--output-prefix", type=Path)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_refinement(
        handoff_report_path=args.handoff_report,
        baseline_mapping_report_path=args.baseline_mapping_report,
        baseline_confidence_report_path=args.baseline_confidence_report,
        reference_report_path=args.reference_report,
        run_id=args.run_id,
        output_prefix=args.output_prefix,
    )
    paths = result["paths"]
    candidates = result["candidates_report"]
    comparison = result["comparison_report"]
    enrichment = result["enrichment_report"]
    print(f"Azure DI refined mapping candidates report: {paths.candidates_json}")
    print(f"Azure DI refined mapping confidence report: {paths.confidence_json}")
    print(f"Azure DI refined mapping gap analysis report: {paths.gap_json}")
    print(f"Azure DI refinement comparison report: {paths.comparison_json}")
    print(f"Azure DI concept metadata enrichment report: {paths.enrichment_json}")
    print(f"Mapping records: {candidates.get('mapping_record_count', 0)}")
    print(f"High confidence: {candidates.get('high_confidence_count', 0)}")
    print(f"Medium confidence: {candidates.get('medium_confidence_count', 0)}")
    print(f"Low confidence: {candidates.get('low_confidence_count', 0)}")
    print(f"Ambiguous: {candidates.get('ambiguous_multiple_suggestions_count', 0)}")
    print(f"No safe suggestion: {candidates.get('no_safe_suggestion_count', 0)}")
    print(f"Curated aliases attached: {enrichment.get('curated_alias_count', 0)}")
    print(f"Recommended next feature: {comparison.get('recommended_next_feature')}")
    if args.verbose:
        print(render_refinement_comparison_markdown(comparison).split("## Cautionary Notes", 1)[0].strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
