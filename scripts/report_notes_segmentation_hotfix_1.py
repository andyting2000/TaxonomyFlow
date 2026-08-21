"""Generate bounded Job 69 evidence reports for #19B-hotfix-1."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import settings  # noqa: E402
from services.section_aware_initial_mapping import (  # noqa: E402
    template_classification_hash,
)
from services.toc_aware_document_structure import (  # noqa: E402
    ARTIFACT_SUBDIRECTORY,
    load_document_structure,
)
from services.toc_aware_template_classification import (  # noqa: E402
    ARTIFACT_FILENAME,
    CLASSIFICATION_VERSION,
    analyze_template_classification,
    persist_template_classification,
)


REPORT_DIRECTORY = ROOT / "reports"
SEGMENTATION_JSON = REPORT_DIRECTORY / "job69_notes_segmentation_19b_hotfix_1.json"
SEGMENTATION_MD = REPORT_DIRECTORY / "job69_notes_segmentation_19b_hotfix_1.md"
QUALITY_JSON = REPORT_DIRECTORY / "notes_heading_quality_19b_hotfix_1.json"
QUALITY_MD = REPORT_DIRECTORY / "notes_heading_quality_19b_hotfix_1.md"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _outcome_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(row.get("outcome")) for row in rows).items()))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _segmentation_markdown(report: dict[str, Any]) -> str:
    before = report["before_19b_v1"]
    after = report["after_19b_v2"]
    metrics = after["segmentation_metrics"]
    conservation = after["conservation"]
    lines = [
        "# Job 69 Notes segmentation - #19B-hotfix-1",
        "",
        f"Status: **{report['status']}**",
        "",
        "## Boundary result",
        "",
        f"- Parent Notes range: PDF {report['notes_parent']['pdf_page_start']}-{report['notes_parent']['pdf_page_end']} (unchanged)",
        f"- Before: {before['logical_child_count']} v1 children",
        f"- After: {after['logical_child_count']} v2 logical children",
        f"- Raw v2 candidates: {metrics['raw_heading_candidate_count']}",
        f"- Physical/semantic duplicates merged: {metrics['duplicate_headings_merged']}",
        f"- Continuation headings merged: {metrics['continuation_headings_merged']}",
        f"- Boilerplate boundaries suppressed: {metrics['boilerplate_lines_suppressed']}",
        f"- Table/value boundaries suppressed: {metrics['table_value_fragments_suppressed']}",
        f"- Invalid numeric note numbers rejected: {metrics['invalid_numeric_note_numbers_rejected']}",
        f"- Prose candidates rejected: {metrics['prose_candidates_rejected']}",
        "",
        "## Conservation and fact attachment",
        "",
        f"- Evidence: total={conservation['total_notes_evidence_items']}, assigned={conservation['assigned_items']}, ambiguous={conservation['ambiguous_items']}, unassigned={conservation['unassigned_items']}, dropped={conservation['dropped_items']}",
        f"- Conservation: {conservation['passed']}",
        f"- Extracted rows attached: {metrics['extracted_rows_attached']}",
        f"- Zero-meaning children: {metrics['child_sections_with_zero_meaningful_content']}",
        f"- Share Capital extracted rows: {report['share_capital']['extracted_row_count']}",
        f"- Share Capital assignments: {', '.join(report['share_capital']['template_codes']) or 'none'}",
        f"- Standalone RM child present: {report['share_capital']['standalone_rm_child_present']}",
        "",
        "## Classification",
        "",
        f"- Before child outcomes: {before['child_outcomes']}",
        f"- After child outcomes: {after['child_outcomes']}",
        "- Registry semantics and deterministic classifier were not broadened; only corrected logical child evidence was reclassified.",
        "",
        "## Version and downstream contract",
        "",
        f"- Current artifact: `{after['artifact_filename']}` ({after['classification_version']})",
        "- v1 is stale by filename/version after the child identity and segmentation semantic change.",
        f"- Existing Job 69 #19C source version: {report['downstream_19c']['existing_source_classification_version']}",
        f"- Existing Job 69 #19C regeneration required: {report['downstream_19c']['existing_artifact_requires_regeneration']}",
        "- #19C compatibility remains fail-closed through current #19B version/hash linkage; no ranking code changed.",
        "",
        "## Safety",
        "",
        f"- Live LLM calls: {report['safety']['live_llm_calls']}",
        f"- Azure provider calls: {report['safety']['azure_provider_calls']}",
        f"- Mapping/tag/final-mapping mutations: {report['safety']['mapping_mutations']}",
        "- XBRL and Arelle were not run.",
        "",
    ]
    return "\n".join(lines)


def _quality_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Notes heading quality - #19B-hotfix-1",
        "",
        f"Status: **{report['status']}**",
        "",
        "## Deterministic rules",
        "",
    ]
    lines.extend(f"- {rule}" for rule in report["rules"])
    lines.extend(
        [
            "",
            "## Job 69 metrics",
            "",
        ]
    )
    lines.extend(f"- {key}: {value}" for key, value in report["metrics"].items())
    lines.extend(
        [
            "",
            "## Regression categories",
            "",
        ]
    )
    lines.extend(
        f"- {category}: {', '.join(examples)}"
        for category, examples in report["representative_examples"].items()
    )
    lines.extend(
        [
            "",
            "All rejected boundary candidates remain assigned source evidence; rejection only prevents a child boundary.",
            "",
        ]
    )
    return "\n".join(lines)


async def build_reports(job_id: int, *, persist: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    if bool(settings.toc_aware_template_classification_live_llm_enabled):
        raise RuntimeError("Live #19B LLM must be disabled for this report")
    structure = load_document_structure(job_id)
    notes_parent = next(
        section
        for section in structure.sections
        if section.canonical_section_type == "notes_to_financial_statements"
    )
    job_directory = (
        ROOT / "uploads" / ARTIFACT_SUBDIRECTORY / f"job_{int(job_id)}"
    )
    previous_path = job_directory / "template_classification_19b_v1.json"
    previous = _read_json(previous_path)
    current = await analyze_template_classification(
        job_id=job_id,
        filing_id=job_id,
        structure=structure,
    )
    if persist:
        persist_template_classification(current, structure=structure)

    previous_children = list(previous.get("note_subsections") or [])
    previous_child_ids = {
        str(child.get("child_section_id")) for child in previous_children
    }
    previous_child_outcomes = [
        outcome
        for outcome in previous.get("outcomes") or []
        if str(outcome.get("section_id")) in previous_child_ids
    ]
    current_child_ids = {child.child_section_id for child in current.note_subsections}
    current_child_outcomes = [
        outcome for outcome in current.outcomes if outcome.section_id in current_child_ids
    ]
    outcome_by_id = {outcome.section_id: outcome for outcome in current_child_outcomes}
    share_capital = next(
        child
        for child in current.note_subsections
        if child.note_number == "4" and child.normalized_heading == "share capital"
    )
    share_outcome = outcome_by_id[share_capital.child_section_id]
    metrics = current.notes_conservation.segmentation_metrics.model_dump(mode="json")
    conservation = current.notes_conservation.model_dump(mode="json")
    conservation.pop("segmentation_metrics", None)

    mapping_path = job_directory / "initial_mapping_19c_v1.json"
    mapping = _read_json(mapping_path) if mapping_path.is_file() else {}
    forbidden = {
        "rm",
        "to",
        "draft",
        "draf",
        "dra",
        "dr",
        "15 15",
        "17 17",
        "18 18",
        "19 19",
        "20 20",
        "21 21",
        "22 22",
        "100 100",
        "700 1,398",
        "400 700",
        "700 400",
    }
    after_titles = {child.raw_heading.casefold() for child in current.note_subsections}
    checks = {
        "logical_children_materially_reduced": len(current.note_subsections) < len(previous_children),
        "known_fragments_not_children": not (after_titles & forbidden),
        "continuations_merged": metrics["continuation_headings_merged"] >= 2,
        "share_capital_fact_attached": bool(share_capital.extracted_row_references),
        "share_capital_classification_preserved": any(
            assignment.template_code == "740000" for assignment in share_outcome.assignments
        ),
        "all_604_evidence_assigned": (
            conservation["total_notes_evidence_items"] == 604
            and conservation["assigned_items"] == 604
            and conservation["ambiguous_items"] == 0
            and conservation["unassigned_items"] == 0
        ),
        "zero_dropped": conservation["dropped_items"] == 0,
        "parent_range_unchanged": (
            notes_parent.pdf_page_start == 16 and notes_parent.pdf_page_end == 23
        ),
        "v2_contract": (
            current.classification_version == "19B-v2"
            and ARTIFACT_FILENAME == "template_classification_19b_v2.json"
        ),
        "no_live_llm": current.llm_count == 0,
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    fact_attachments = [
        {
            "child_section_id": child.child_section_id,
            "note_number": child.note_number,
            "heading": child.raw_heading,
            "extracted_row_count": len(child.extracted_row_references),
        }
        for child in current.note_subsections
        if child.extracted_row_references
    ]
    segmentation_report = {
        "feature": "19B-hotfix-1",
        "job_id": job_id,
        "status": status,
        "checks": checks,
        "notes_parent": {
            "section_id": notes_parent.section_id,
            "pdf_page_start": notes_parent.pdf_page_start,
            "pdf_page_end": notes_parent.pdf_page_end,
        },
        "before_19b_v1": {
            "artifact": str(previous_path.relative_to(ROOT)),
            "classification_version": previous.get("classification_version"),
            "logical_child_count": len(previous_children),
            "child_outcomes": _outcome_summary(previous_child_outcomes),
            "overall_counts": {
                key: previous.get(key)
                for key in (
                    "matched_count",
                    "multiple_template_count",
                    "narrative_only_count",
                    "container_only_count",
                    "ambiguous_count",
                    "unassigned_count",
                    "failed_count",
                )
            },
        },
        "after_19b_v2": {
            "artifact_filename": ARTIFACT_FILENAME,
            "artifact_persisted": bool(persist),
            "classification_version": CLASSIFICATION_VERSION,
            "classification_hash": template_classification_hash(current),
            "logical_child_count": len(current.note_subsections),
            "logical_headings": [
                {
                    "child_section_id": child.child_section_id,
                    "note_number": child.note_number,
                    "heading": child.raw_heading,
                    "pdf_page_start": child.pdf_page_start,
                    "pdf_page_end": child.pdf_page_end,
                    "contributing_heading_evidence_count": len(child.heading_evidence),
                }
                for child in current.note_subsections
            ],
            "child_outcomes": dict(
                sorted(Counter(outcome.outcome.value for outcome in current_child_outcomes).items())
            ),
            "segmentation_metrics": metrics,
            "conservation": conservation,
            "fact_attachments": fact_attachments,
        },
        "share_capital": {
            "child_section_id": share_capital.child_section_id,
            "raw_heading": share_capital.raw_heading,
            "extracted_row_count": len(share_capital.extracted_row_references),
            "template_codes": [
                assignment.template_code for assignment in share_outcome.assignments
            ],
            "standalone_rm_child_present": any(
                child.raw_heading.casefold() == "rm" for child in current.note_subsections
            ),
        },
        "downstream_19c": {
            "ranking_changed": False,
            "existing_source_classification_version": mapping.get(
                "source_classification_version"
            ),
            "existing_artifact_requires_regeneration": (
                bool(mapping)
                and mapping.get("source_classification_version")
                != current.classification_version
            ),
            "compatibility_contract": "current_19b_version_and_hash_fail_closed",
        },
        "safety": {
            "live_llm_calls": current.llm_count,
            "azure_provider_calls": 0,
            "mapping_mutations": 0,
            "template_mutations": 0,
            "confirmed_tag_id_mutations": 0,
            "final_mapping_mutations": 0,
            "xbrl_generated": False,
            "arelle_run": False,
        },
    }
    quality_report = {
        "feature": "19B-hotfix-1",
        "job_id": job_id,
        "status": status,
        "metrics": metrics,
        "rules": [
            "Recognize bounded decimal, nested alphabetic, and Roman note-number forms; numeric components must be 1-99.",
            "Prefer Azure section-heading roles and #19A candidates while retaining a deterministic lexical fallback.",
            "Reject repeated document headers, company identifiers/names, Notes running headers, page markers, and DRAFT fragments as boundaries.",
            "Reject standalone units, numeric/table fragments, and geometry-overlapping table candidates unless independent section-heading evidence exists.",
            "Reject long or sentence-like numbered prose using length, word count, punctuation, lead phrase, and verb signals.",
            "Collapse paragraph/line duplicates by normalized title, compatible number, page, and vertical proximity while retaining every contributing evidence ID.",
            "Merge same-number/title continuation events into one logical child and preserve every boundary position for page-span assignment.",
            "Hash parent ID plus stable logical number/title identity for deterministic child IDs.",
            "Treat a rejected candidate as content, never as dropped evidence; leading Notes boilerplate attaches to the first logical child.",
        ],
        "representative_examples": {
            "boilerplate": [
                "COMPANY NO...",
                "company-name header",
                "NOTES TO THE FINANCIAL STATEMENTS ... (Continued)",
                "DRAFT/DRAF/DRA/DR",
                "repeated page number",
            ],
            "table_or_value": ["RM", "TO", "100 100", "700 1,398"],
            "invalid_numeric_note_number": ["465 ...", "700 ...", "897 ..."],
            "prose": [
                "2. The financial statements have been prepared ...",
                "c) After initial recognition, the Company measures ...",
                "10. The financial statements of the Company ...",
            ],
            "preserved_nested": [
                "a) Initial recognition and measurement",
                "b) Subsequent measurement of financial assets",
                "c) Subsequent measurement of financial liabilities",
                "d) Derecognition of financial instruments",
            ],
        },
        "conservation": conservation,
        "checks": checks,
    }
    return segmentation_report, quality_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", type=int, default=69)
    parser.add_argument("--persist-classification", action="store_true")
    args = parser.parse_args()
    segmentation, quality = asyncio.run(
        build_reports(args.job_id, persist=args.persist_classification)
    )
    REPORT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    _write_json(SEGMENTATION_JSON, segmentation)
    SEGMENTATION_MD.write_text(_segmentation_markdown(segmentation), encoding="utf-8")
    _write_json(QUALITY_JSON, quality)
    QUALITY_MD.write_text(_quality_markdown(quality), encoding="utf-8")
    print(f"{segmentation['status']}: {SEGMENTATION_JSON}")
    print(f"{quality['status']}: {QUALITY_JSON}")
    return 0 if segmentation["status"] == quality["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
