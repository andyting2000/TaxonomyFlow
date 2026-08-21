#!/usr/bin/env python3
"""Generate bounded read-only-source reports for the #19A-hotfix-3 projection."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings  # noqa: E402
from file_safety import uploads_root  # noqa: E402
from schemas import DocumentStructureResult  # noqa: E402
from services.document_page_alignment import align_document_pages  # noqa: E402
from services.document_section_grouper import (  # noqa: E402
    build_document_sections,
    group_document_content,
    summarize_section_range_topology,
    validate_section_page_mapping_consistency,
)
from services.toc_aware_document_structure import FEATURE_VERSION  # noqa: E402
from services.toc_aware_template_classification import (  # noqa: E402
    analyze_template_classification,
)


LEGACY_SOURCE_FILENAME = "structure_19a_v3.json"
REPORT_FILENAMES = (
    "section_range_conflicts_19a_hotfix_3",
    "multipage_range_preservation_19a_hotfix_3",
    "job67_structure_regression_19a_hotfix_3",
)
TARGET_TYPES = {
    "directors_report",
    "independent_auditors_report",
    "notes_to_financial_statements",
}
ROOT_CAUSES = {
    "directors_report": (
        "The document-wide page_alignment_ambiguous flag activated "
        "unsafe_range_projection after the exact Tier-A start anchor had "
        "resolved PDF page 2. That branch collapsed the already derivable "
        "2-5 range to 2-2; the fail-closed validator then cleared both endpoints."
    ),
    "independent_auditors_report": (
        "Repeated canonical-prefix report headers produced a cross-page near tie. "
        "The selected PDF-8 anchor agreed with the +1 regime, but the old grouper "
        "withheld it and the document-wide ambiguous flag discarded the uniquely "
        "mapped 8-11 endpoints; the validator then cleared both endpoints."
    ),
    "notes_to_financial_statements": (
        "Repeated Notes continuation headers produced a cross-page near tie. The "
        "selected PDF-16 anchor agreed with the +1 regime, but the old grouper "
        "withheld it and discarded the uniquely mapped 16-23 endpoints, leaving "
        "the long Notes container unresolved."
    ),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _polygon_top(regions: list[dict[str, Any]]) -> float | None:
    values: list[float] = []
    for region in regions:
        polygon = region.get("polygon")
        if not isinstance(polygon, list) or not polygon:
            continue
        first = polygon[0]
        try:
            if isinstance(first, dict):
                values.append(float(first.get("y")))
            elif len(polygon) >= 2:
                values.append(float(polygon[1]))
        except (TypeError, ValueError):
            continue
    return min(values) if values else None


def _inventory(structure: DocumentStructureResult) -> list[dict[str, Any]]:
    return [
        {
            "content_id": evidence.content_id,
            "content_type": evidence.content_type,
            "text": evidence.text_evidence or "",
            "pdf_page_indexes": list(evidence.pdf_page_indexes),
            "azure_page_numbers": list(evidence.azure_page_numbers),
            "top": _polygon_top(list(evidence.bounding_evidence)),
            "bounding_evidence": list(evidence.bounding_evidence),
            "provenance": dict(evidence.provenance),
        }
        for evidence in structure.content_evidence
    ]


def _reference_count(section) -> int:
    return sum(
        len(getattr(section, field))
        for field in (
            "text_block_ids",
            "heading_ids",
            "table_ids",
            "table_cell_ids",
            "extracted_row_ids",
        )
    )


def _old_conflict_details(structure: DocumentStructureResult) -> list[dict[str, Any]]:
    anchors = {anchor.toc_entry_id: anchor for anchor in structure.heading_anchors}
    mappings: dict[int, list[Any]] = {}
    for mapping in structure.page_mappings:
        if mapping.printed_page_number is not None:
            mappings.setdefault(mapping.printed_page_number, []).append(mapping)
    details = []
    for section in structure.sections:
        if section.canonical_section_type not in TARGET_TYPES:
            continue
        anchor = anchors.get(section.toc_entry_id)
        starts = mappings.get(section.printed_page_start or -1, [])
        ends = mappings.get(section.printed_page_end or -1, [])
        expected = (
            [starts[0].pdf_page_index, ends[0].pdf_page_index]
            if len(starts) == 1 and len(ends) == 1
            else None
        )
        expected_offset = starts[0].offset if len(starts) == 1 else None
        actual_offset = (
            anchor.pdf_page_index - section.printed_page_start
            if anchor is not None and section.printed_page_start is not None
            else None
        )
        details.append(
            {
                "section_id": section.section_id,
                "raw_toc_title": section.raw_title,
                "canonical_title": section.normalized_title,
                "canonical_section_type": section.canonical_section_type,
                "printed_range": [
                    section.printed_page_start,
                    section.printed_page_end,
                ],
                "mapped_pdf_range": expected,
                "stored_pdf_range": [section.pdf_page_start, section.pdf_page_end],
                "stored_azure_range": [
                    section.azure_page_start,
                    section.azure_page_end,
                ],
                "selected_anchor": anchor.matched_heading if anchor else None,
                "selected_anchor_page": anchor.pdf_page_index if anchor else None,
                "selected_anchor_azure_page": (
                    anchor.azure_page_number if anchor else None
                ),
                "anchor_tier": anchor.match_tier if anchor else None,
                "anchor_method": anchor.match_method if anchor else None,
                "anchor_confidence": anchor.confidence if anchor else None,
                "expected_offset": expected_offset,
                "actual_anchor_offset": actual_offset,
                "geometry_evidence": (
                    list(anchor.bounding_evidence) if anchor else []
                ),
                "old_consistency_validator": {
                    "status": "unresolved",
                    "expected_pdf_range": expected,
                    "observed_persisted_pdf_range": [
                        section.pdf_page_start,
                        section.pdf_page_end,
                    ],
                    "pre_clear_observed_range": "not persisted by 19A-v3",
                    "conflict_reason": "section_range_conflicts_with_page_mapping",
                    "reconciled": False,
                    "grouping_method": section.grouping_method,
                },
                "root_cause": ROOT_CAUSES[section.canonical_section_type],
            }
        )
    return details


async def build_reports(job_id: int) -> dict[str, dict[str, Any]]:
    if bool(
        getattr(
            settings,
            "toc_aware_template_classification_live_llm_enabled",
            False,
        )
    ):
        raise RuntimeError("Refusing report generation while #19B live LLM is enabled")
    source = (
        uploads_root()
        / "document-structures"
        / f"job_{int(job_id)}"
        / LEGACY_SOURCE_FILENAME
    )
    if not source.is_file():
        raise FileNotFoundError(source)
    raw = source.read_bytes()
    if len(raw) > 25 * 1024 * 1024:
        raise ValueError("Legacy structure artifact exceeds size limit")
    old = DocumentStructureResult.model_validate_json(raw)
    if old.job_id != int(job_id) or old.feature_version != "19A-v3":
        raise ValueError("Legacy structure artifact identity mismatch")

    azure_pages = sorted(
        {mapping.azure_page_number for mapping in old.page_mappings}
    )
    alignment = align_document_pages(
        old.toc_entries,
        old.heading_anchors,
        azure_page_numbers=azure_pages,
    )
    sections = build_document_sections(
        old.job_id,
        old.toc_entries,
        old.heading_anchors,
        alignment,
    )
    consistency = validate_section_page_mapping_consistency(sections, alignment)
    topology = summarize_section_range_topology(sections)
    inventory = _inventory(old)
    unassigned, ambiguous, conservation = group_document_content(
        sections,
        inventory,
        old.heading_anchors,
        toc_page_indexes=old.toc_page_indexes,
    )
    toc_excluded = sum(item.reason == "toc_page_excluded" for item in unassigned)
    eligible = max(0, len(inventory) - toc_excluded)
    non_toc_unassigned = sum(
        item.reason != "toc_page_excluded" for item in unassigned
    )
    safety = {
        **conservation,
        **consistency,
        **topology,
        "toc_excluded_content_count": toc_excluded,
        "content_inventory_excluding_toc_count": eligible,
        "unassigned_content_excluding_toc_count": non_toc_unassigned,
        "assignment_rate_excluding_toc": round(
            conservation["assigned_content_count"] / max(1, eligible), 6
        ),
        "unassigned_rate_excluding_toc": round(
            non_toc_unassigned / max(1, eligible), 6
        ),
        "dropped_content_count": conservation["dropped_content_count"],
        "structure_algorithm_version": FEATURE_VERSION,
        "azure_provider_calls_made": 0,
        "llm_calls_made": 0,
        "supervisor_calls_made": 0,
        "source_extraction_mutated": False,
        "mapping_suggestions_mutated": False,
        "confirmed_tag_id_mutations": 0,
        "final_mapping_mutations": 0,
        "xbrl_generated": False,
        "arelle_run": False,
    }
    projected = old.model_copy(
        update={
            "feature_version": FEATURE_VERSION,
            "page_mapping_confidence": alignment.confidence,
            "page_alignment_summary": alignment.to_dict(),
            "page_mappings": list(alignment.page_mappings),
            "sections": sections,
            "unassigned_content": unassigned,
            "ambiguous_content": ambiguous,
            "warnings": [
                warning
                for warning in old.warnings
                if warning
                not in {
                    "page_alignment_ambiguous",
                    "heading_anchor_missing",
                    "section_range_conflicts_with_page_mapping",
                    "unassigned_document_content",
                }
            ],
            "safety_summary": safety,
        },
        deep=True,
    )
    classification = await analyze_template_classification(
        job_id=old.job_id,
        filing_id=old.job_id,
        structure=projected,
    )
    old_conflicts = _old_conflict_details(old)
    new_by_type = {
        section.canonical_section_type: section for section in sections
    }
    corrected = []
    for old_detail in old_conflicts:
        section = new_by_type[old_detail["canonical_section_type"]]
        corrected.append(
            {
                "section_id": section.section_id,
                "raw_title": section.raw_title,
                "derived_pdf_range": [
                    section.pdf_page_start,
                    section.pdf_page_end,
                ],
                "derived_azure_range": [
                    section.azure_page_start,
                    section.azure_page_end,
                ],
                "page_count": (
                    section.pdf_page_end - section.pdf_page_start + 1
                    if section.pdf_page_start is not None
                    and section.pdf_page_end is not None
                    else 0
                ),
                "heading_anchor_page": section.heading_anchor_page,
                "start_heading_bbox": list(section.start_heading_bbox),
                "start_heading_offset": section.start_heading_offset,
                "end_heading_bbox": list(section.end_heading_bbox),
                "end_heading_offset": section.end_heading_offset,
                "range_consistency": dict(section.range_consistency),
                "grouping_method": section.grouping_method,
                "requires_human_review": section.requires_human_review,
                "assigned_evidence_count": _reference_count(section),
            }
        )

    notes = new_by_type["notes_to_financial_statements"]
    children_outside = [
        subsection.child_section_id
        for subsection in classification.note_subsections
        if subsection.pdf_page_start is None
        or subsection.pdf_page_end is None
        or subsection.pdf_page_start < notes.pdf_page_start
        or subsection.pdf_page_end > notes.pdf_page_end
    ]
    outcomes_by_title = {
        outcome.raw_title: outcome.outcome.value
        for outcome in classification.outcomes
        if outcome.parent_section_id is None
        or outcome.outcome.value == "container_only"
    }
    common = {
        "feature": "19A-hotfix-3",
        "generated_at": _utc_now(),
        "source_job_id": job_id,
        "source_artifact": str(source),
        "source_artifact_version": old.feature_version,
        "source_artifact_sha256": hashlib.sha256(raw).hexdigest(),
        "target_artifact_version": FEATURE_VERSION,
        "real_pdf_smoke_status": "NOT_RERUN",
        "analysis_status": "PASS",
        "old_conflicts": old_conflicts,
        "corrected_ranges": corrected,
        "range_authority": {
            "rule": (
                "Unique explicit TOC endpoints mapped by one sufficiently supported "
                "numbering regime own the full PDF page range; heading geometry is "
                "stored separately and cannot replace either endpoint."
            ),
            "page_range_and_geometry_conflated_before": True,
            "page_range_and_geometry_conflated_after": False,
            "dominant_offsets": list(alignment.dominant_offsets),
            "weighted_offset_support": dict(alignment.weighted_offset_support),
            "alignment_confidence": alignment.confidence,
            "alignment_requires_human_review": alignment.requires_human_review,
            "competing_high_quality_offset_count": (
                alignment.competing_high_quality_offset_count
            ),
        },
        "assignment_metrics": {
            "before": {
                key: old.safety_summary.get(key)
                for key in (
                    "content_inventory_count",
                    "toc_excluded_content_count",
                    "assigned_content_count",
                    "ambiguous_content_count",
                    "unassigned_content_count",
                    "dropped_content_count",
                    "assignment_rate",
                    "assignment_rate_excluding_toc",
                    "unassigned_rate_excluding_toc",
                )
            },
            "projected_after": {
                "content_inventory_count": conservation["content_inventory_count"],
                "toc_excluded_content_count": toc_excluded,
                "assigned_content_count": conservation["assigned_content_count"],
                "ambiguous_content_count": conservation["ambiguous_content_count"],
                "unassigned_content_count": conservation["unassigned_content_count"],
                "dropped_content_count": conservation["dropped_content_count"],
                "assignment_rate": conservation["assignment_rate"],
                "assignment_rate_excluding_toc": safety[
                    "assignment_rate_excluding_toc"
                ],
                "unassigned_rate_excluding_toc": safety[
                    "unassigned_rate_excluding_toc"
                ],
            },
        },
        "range_topology": topology,
        "notes_containment": {
            "parent_pdf_range": [notes.pdf_page_start, notes.pdf_page_end],
            "parent_evidence_count": _reference_count(notes),
            "child_count": len(classification.note_subsections),
            "children_outside_parent_count": len(children_outside),
            "children_outside_parent": children_outside,
            "cover_page_child_count": sum(
                subsection.pdf_page_start == 0
                for subsection in classification.note_subsections
            ),
            "conservation_passed": classification.notes_conservation.passed,
            "dropped_items": classification.notes_conservation.dropped_items,
        },
        "human_review": {
            "alignment_requires_human_review": alignment.requires_human_review,
            "section_ids_requiring_human_review": [
                section.section_id
                for section in sections
                if section.requires_human_review
            ],
            "requires_human_review": (
                alignment.requires_human_review
                or any(section.requires_human_review for section in sections)
            ),
        },
        "classification": {
            "primary_outcomes": outcomes_by_title,
            "notes_conservation_passed": classification.notes_conservation.passed,
            "children_outside_parent_count": len(children_outside),
            "live_llm_calls": classification.llm_count,
        },
        "versioning_decision": (
            "Incremented to 19A-v4 / structure_19a_v4.json because persisted "
            "page-range and geometry semantics changed. Existing 19B/19C "
            "version/hash validation rejects v3 linkages."
        ),
        "safety": {
            "fixture_or_projection_only": True,
            "source_artifact_read_only": True,
            "database_writes": 0,
            "provider_calls": 0,
            "llm_calls": classification.llm_count,
            "mapping_or_template_mutations": 0,
            "confirmed_or_final_mapping_mutations": 0,
            "xbrl_generated": False,
            "arelle_run": False,
        },
    }
    return {
        "section_range_conflicts_19a_hotfix_3": common,
        "multipage_range_preservation_19a_hotfix_3": {
            **common,
            "focus": "authoritative multi-page ownership and separate geometry",
        },
        "job67_structure_regression_19a_hotfix_3": {
            **common,
            "focus": "read-only projection of immutable Job 67 v3 evidence",
        },
    }


def _markdown(report: dict[str, Any], *, title: str) -> str:
    before = report["assignment_metrics"]["before"]
    after = report["assignment_metrics"]["projected_after"]
    lines = [
        f"# {title}",
        "",
        f"- Analysis status: `{report['analysis_status']}`",
        f"- Real-PDF smoke: `{report['real_pdf_smoke_status']}`",
        f"- Source: Job `{report['source_job_id']}` `{report['source_artifact_version']}` (read-only)",
        f"- Target contract: `{report['target_artifact_version']}`",
        "",
        "## Conflict root causes and corrected ranges",
        "",
    ]
    corrected = {row["section_id"]: row for row in report["corrected_ranges"]}
    for conflict in report["old_conflicts"]:
        new = corrected[conflict["section_id"]]
        lines.extend(
            [
                f"### {conflict['raw_toc_title']}",
                "",
                f"- Printed: `{conflict['printed_range']}`; mapped PDF: `{conflict['mapped_pdf_range']}`; persisted v3: `{conflict['stored_pdf_range']}`.",
                f"- Anchor: `{conflict['anchor_tier']}` / `{conflict['anchor_method']}` on PDF `{conflict['selected_anchor_page']}`; expected/actual offset `{conflict['expected_offset']}` / `{conflict['actual_anchor_offset']}`.",
                f"- Root cause: {conflict['root_cause']}",
                f"- Corrected derived PDF range: `{new['derived_pdf_range']}`; geometry remains start-only at `{new['start_heading_offset']}`.",
                f"- Consistency: `{new['range_consistency']['status']}`; review: `{new['requires_human_review']}`.",
                "",
            ]
        )
    lines.extend(
        [
            "## Assignment and containment",
            "",
            f"- Before: assigned `{before['assigned_content_count']}`, unassigned `{before['unassigned_content_count']}`, assignment excluding TOC `{before['assignment_rate_excluding_toc']}`, dropped `{before['dropped_content_count']}`.",
            f"- Projected after: assigned `{after['assigned_content_count']}`, unassigned `{after['unassigned_content_count']}`, assignment excluding TOC `{after['assignment_rate_excluding_toc']}`, unassigned excluding TOC `{after['unassigned_rate_excluding_toc']}`, dropped `{after['dropped_content_count']}`.",
            f"- Range topology: `{report['range_topology']}`.",
            f"- Notes containment: `{report['notes_containment']}`.",
            f"- Human review: `{report['human_review']}`.",
            "",
            "## Versioning and safety",
            "",
            f"- {report['versioning_decision']}",
            "- No provider, live LLM, database, mapping/template, confirmed/final mapping, XBRL, or Arelle action occurred.",
            "- Fixture/projection PASS is not a fresh real-PDF PASS.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", type=int, default=67)
    args = parser.parse_args(argv)
    if args.job_id <= 0:
        parser.error("--job-id must be positive")
    reports = asyncio.run(build_reports(args.job_id))
    output_dir = PROJECT_ROOT / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in REPORT_FILENAMES:
        report = reports[name]
        (output_dir / f"{name}.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (output_dir / f"{name}.md").write_text(
            _markdown(report, title=name.replace("_", " ").title()),
            encoding="utf-8",
        )
    print(json.dumps({name: reports[name]["analysis_status"] for name in REPORT_FILENAMES}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
