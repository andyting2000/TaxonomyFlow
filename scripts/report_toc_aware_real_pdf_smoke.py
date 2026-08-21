#!/usr/bin/env python3
"""Read-only #19A/#19B/#19C artifact report for a processed real PDF job."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.document_heading_quality import toc_title_rejection_reason  # noqa: E402
from services.section_aware_initial_mapping import load_initial_mapping  # noqa: E402
from services.section_title_normalization import UNKNOWN_SECTION  # noqa: E402
from services.toc_aware_document_structure import load_document_structure  # noqa: E402
from services.toc_aware_template_classification import (  # noqa: E402
    load_template_classification,
)


EVALUATOR_UNASSIGNED_WARNING_RATE = 0.50
PRIMARY_FINANCIAL_SECTIONS = {
    "statement_of_financial_position",
    "statement_of_comprehensive_income",
    "income_statement",
    "statement_of_changes_in_equity",
    "statement_of_cash_flows",
}
ANCHOR_TIER_PRIORITY = {"A": 4, "B": 3, "C": 2, "D": 1, "legacy": 0}


def _section_reference_count(section) -> int:
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


def build_structure_metrics(structure) -> dict[str, Any]:
    suspicious_entries = [
        {
            "entry_id": entry.entry_id,
            "title": entry.raw_title,
            "reason": (
                toc_title_rejection_reason(entry.raw_title)
                or "unknown_canonical_section"
            ),
        }
        for entry in structure.toc_entries
        if toc_title_rejection_reason(entry.raw_title)
        or entry.canonical_section_hint == UNKNOWN_SECTION
    ]
    trusted = [anchor for anchor in structure.heading_anchors if anchor.trusted]
    rejected = [anchor for anchor in structure.heading_anchors if not anchor.trusted]
    rejected_candidates = [
        candidate
        for anchor in structure.heading_anchors
        for candidate in anchor.rejected_candidates
    ]
    notes_sections = [
        section
        for section in structure.sections
        if section.canonical_section_type == "notes_to_financial_statements"
    ]
    primary_ranges = [
        section
        for section in structure.sections
        if section.canonical_section_type in PRIMARY_FINANCIAL_SECTIONS
        and section.pdf_page_start is not None
        and section.pdf_page_end is not None
    ]
    safety = dict(structure.safety_summary)
    selected_methods = Counter(anchor.match_method for anchor in trusted)
    weaker_selected_count = sum(
        any(
            candidate.get("trusted")
            and ANCHOR_TIER_PRIORITY.get(str(candidate.get("match_tier")), 0)
            > ANCHOR_TIER_PRIORITY.get(anchor.match_tier, 0)
            for candidate in anchor.alternative_candidates
        )
        for anchor in trusted
    )
    entries_by_id = {entry.entry_id: entry for entry in structure.toc_entries}
    dominant_offsets = {
        int(value)
        for value in structure.page_alignment_summary.get("dominant_offsets") or []
    }
    off_regime_anchors = [
        anchor
        for anchor in trusted
        if anchor.toc_entry_id in entries_by_id
        and entries_by_id[anchor.toc_entry_id].printed_page_start is not None
        and dominant_offsets
        and (
            anchor.pdf_page_index
            - entries_by_id[anchor.toc_entry_id].printed_page_start
        )
        not in dominant_offsets
    ]
    quality_warnings: list[str] = []
    if (
        structure.toc_detected
        and structure.page_mapping_confidence >= 0.80
        and primary_ranges
        and float(
            safety.get("unassigned_rate_excluding_toc")
            if safety.get("unassigned_rate_excluding_toc") is not None
            else safety.get("unassigned_rate")
            or 0.0
        )
        > EVALUATOR_UNASSIGNED_WARNING_RATE
    ):
        quality_warnings.append("excessive_unassigned_content")
    return {
        "feature_version": structure.feature_version,
        "toc_entry_count": len(structure.toc_entries),
        "canonical_expected_entry_count": sum(
            entry.canonical_section_hint != UNKNOWN_SECTION
            for entry in structure.toc_entries
        ),
        "suspicious_toc_entry_count": len(suspicious_entries),
        "suspicious_toc_entries": suspicious_entries,
        "trusted_anchor_count": len(trusted),
        "rejected_anchor_count": len(rejected),
        "rejected_candidate_count": len(rejected_candidates),
        "selected_anchor_match_counts": {
            "exact": selected_methods["exact_normalized_title"],
            "prefix": selected_methods["canonical_title_prefix"],
            "canonical_alias_or_equivalent": (
                selected_methods["canonical_alias_exact"]
                + selected_methods["canonical_title_equivalent"]
            ),
            "fuzzy": selected_methods["strong_fuzzy_title"],
            "partial": selected_methods["substantial_title_containment"],
        },
        "weaker_selected_while_stronger_alternative_count": weaker_selected_count,
        "off_regime_selected_anchor_count": len(off_regime_anchors),
        "trusted_anchors": [
            {
                "expected_title": anchor.toc_title,
                "observed_heading": anchor.matched_heading,
                "page_index": anchor.pdf_page_index,
                "match_method": anchor.match_method,
                "match_tier": anchor.match_tier,
                "confidence": anchor.confidence,
                "token_coverage": anchor.token_coverage,
                "expected_core_token_coverage": anchor.expected_core_token_coverage,
                "missing_expected_core_tokens": list(anchor.missing_expected_core_tokens),
                "length_ratio": anchor.length_ratio,
            }
            for anchor in trusted
        ],
        "rejected_anchors": [
            {
                "expected_title": anchor.toc_title,
                "observed_heading": anchor.matched_heading,
                "page_index": anchor.pdf_page_index,
                "rejection_reason": anchor.rejection_reason,
            }
            for anchor in rejected
        ],
        "dominant_offsets": list(
            structure.page_alignment_summary.get("dominant_offsets") or []
        ),
        "weighted_offset_support": dict(
            structure.page_alignment_summary.get("weighted_offset_support") or {}
        ),
        "alignment_confidence": structure.page_mapping_confidence,
        "requires_human_review": bool(
            structure.page_alignment_summary.get("requires_human_review")
        ),
        "inconsistent_trusted_anchor_count": int(
            structure.page_alignment_summary.get("inconsistent_anchor_count") or 0
        ),
        "section_count": len(structure.sections),
        "assigned_evidence": int(safety.get("assigned_content_count") or 0),
        "ambiguous_evidence": int(safety.get("ambiguous_content_count") or 0),
        "unassigned_evidence": int(safety.get("unassigned_content_count") or 0),
        "dropped_evidence": int(safety.get("dropped_content_count") or 0),
        "assignment_rate": float(safety.get("assignment_rate") or 0.0),
        "ambiguity_rate": float(safety.get("ambiguity_rate") or 0.0),
        "unassigned_rate": float(safety.get("unassigned_rate") or 0.0),
        "dropped_rate": float(safety.get("dropped_rate") or 0.0),
        "assignment_rate_excluding_toc": float(
            safety.get("assignment_rate_excluding_toc") or 0.0
        ),
        "unassigned_rate_excluding_toc": float(
            safety.get("unassigned_rate_excluding_toc") or 0.0
        ),
        "section_page_mapping_conflict_count": int(
            safety.get("section_page_mapping_conflict_count") or 0
        ),
        "explicit_range_projection_success_count": int(
            safety.get("explicit_range_projection_success_count") or 0
        ),
        "resolved_range_projection_success_count": int(
            safety.get("resolved_range_projection_success_count") or 0
        ),
        "notes_evidence_count": sum(
            _section_reference_count(section) for section in notes_sections
        ),
        "notes_ranges": [
            {
                "printed_page_start": section.printed_page_start,
                "printed_page_end": section.printed_page_end,
                "pdf_page_start": section.pdf_page_start,
                "pdf_page_end": section.pdf_page_end,
            }
            for section in notes_sections
        ],
        "quality_warnings": quality_warnings,
        "safety_summary": safety,
    }


def build_classification_metrics(classification, *, structure=None) -> dict[str, Any]:
    outcome_counts = Counter(str(outcome.outcome.value) for outcome in classification.outcomes)
    notes_parent = next(
        (
            section
            for section in (structure.sections if structure is not None else [])
            if section.canonical_section_type == "notes_to_financial_statements"
        ),
        None,
    )
    child_page_distribution = Counter()
    children_outside_parent = []
    for subsection in classification.note_subsections:
        if subsection.pdf_page_start is not None and subsection.pdf_page_end is not None:
            child_page_distribution.update(
                range(subsection.pdf_page_start, subsection.pdf_page_end + 1)
            )
        outside = (
            notes_parent is not None
            and notes_parent.pdf_page_start is not None
            and notes_parent.pdf_page_end is not None
            and (
                subsection.pdf_page_start is None
                or subsection.pdf_page_end is None
                or subsection.pdf_page_start < notes_parent.pdf_page_start
                or subsection.pdf_page_end > notes_parent.pdf_page_end
            )
        )
        if outside:
            children_outside_parent.append(subsection.child_section_id)
    return {
        "classification_version": classification.classification_version,
        "primary_classification_summary": dict(sorted(outcome_counts.items())),
        "notes_container_present": any(
            outcome.canonical_section_type == "notes_to_financial_statements"
            and outcome.outcome.value == "container_only"
            for outcome in classification.outcomes
        ),
        "note_subsection_count": classification.total_note_subsections,
        "notes_child_page_distribution": {
            str(page): count for page, count in sorted(child_page_distribution.items())
        },
        "notes_children_outside_parent_range": children_outside_parent,
        "notes_children_outside_parent_range_count": len(children_outside_parent),
        "notes_conservation": classification.notes_conservation.model_dump(mode="json"),
        "notes_segmentation_metrics": (
            classification.notes_conservation.segmentation_metrics.model_dump(mode="json")
        ),
        "warnings": list(classification.warnings),
    }


def build_mapping_metrics(mapping) -> dict[str, Any]:
    selected_candidates = []
    for item in mapping.mappings:
        if not item.selected_concept_id:
            continue
        selected_candidates.extend(
            candidate
            for candidate in item.candidate_set.candidates
            if candidate.concept_id == item.selected_concept_id
        )
    safety = dict(mapping.safety_summary)
    return {
        "mapping_version": mapping.mapping_version,
        "rows_with_section_id": sum(bool(item.section_id) for item in mapping.mappings),
        "rows_without_section_id": sum(not item.section_id for item in mapping.mappings),
        "eligible_rows": mapping.eligible_rows,
        "mapped_rows": mapping.mapped_rows,
        "ambiguous_rows": mapping.ambiguous_rows,
        "abstain_rows": mapping.abstained_rows,
        "candidate_leakage": int(
            safety.get("template_group_leakage_count")
            or safety.get("candidate_leakage_count")
            or 0
        ),
        "abstract_selection_count": sum(
            candidate.concept_card.abstract for candidate in selected_candidates
        ),
        "mutation_counts": {
            key: int(safety.get(key) or 0)
            for key in (
                "existing_mapping_suggestion_mutations",
                "template_field_mutations",
                "confirmed_tag_id_mutations",
                "final_mapping_mutations",
            )
        },
        "warnings": list(mapping.warnings),
    }


def build_job_report(job_id: int) -> dict[str, Any]:
    structure = load_document_structure(job_id)
    report: dict[str, Any] = {
        "job_id": int(job_id),
        "read_only": True,
        "provider_calls_made": 0,
        "structure": build_structure_metrics(structure),
    }
    try:
        classification = load_template_classification(job_id, structure=structure)
    except (FileNotFoundError, ValueError) as exc:
        report["classification"] = {
            "available": False,
            "reason": type(exc).__name__,
        }
    else:
        report["classification"] = {
            "available": True,
            **build_classification_metrics(classification, structure=structure),
        }
    try:
        mapping = load_initial_mapping(job_id)
    except (FileNotFoundError, ValueError) as exc:
        report["initial_mapping"] = {
            "available": False,
            "reason": type(exc).__name__,
        }
    else:
        report["initial_mapping"] = {
            "available": True,
            **build_mapping_metrics(mapping),
        }
    structure_metrics = report["structure"]
    classification_metrics = report["classification"]
    hard_gates = {
        "weaker_selected_while_stronger_alternative": (
            structure_metrics["weaker_selected_while_stronger_alternative_count"] == 0
        ),
        "section_page_mapping_conflicts": (
            structure_metrics["section_page_mapping_conflict_count"] == 0
        ),
        "notes_children_outside_parent_range": (
            classification_metrics.get("available") is True
            and classification_metrics.get(
                "notes_children_outside_parent_range_count"
            )
            == 0
        ),
        "dropped_evidence": structure_metrics["dropped_evidence"] == 0,
    }
    report["quality_gate"] = {
        "warnings": list(structure_metrics["quality_warnings"]),
        "hard_gates": hard_gates,
        "pass": (
            all(hard_gates.values())
            and structure_metrics["suspicious_toc_entry_count"] == 0
            and structure_metrics["off_regime_selected_anchor_count"] == 0
            and structure_metrics["notes_evidence_count"] > 0
            and not structure_metrics["requires_human_review"]
            and not structure_metrics["quality_warnings"]
        ),
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id", type=int)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    try:
        report = build_job_report(args.job_id)
    except (FileNotFoundError, ValueError) as exc:
        report = {
            "job_id": int(args.job_id),
            "read_only": True,
            "provider_calls_made": 0,
            "quality_gate": {
                "pass": False,
                "warnings": ["current_structure_artifact_unavailable"],
            },
            "error": {
                "code": "current_structure_artifact_unavailable",
                "reason": type(exc).__name__,
                "message": str(exc),
            },
        }
        exit_code = 2
    else:
        exit_code = 0
    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=None if args.compact else 2,
            sort_keys=True,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
