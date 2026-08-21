from __future__ import annotations

from datetime import datetime, timezone

from schemas import (
    DocumentContentEvidence,
    DocumentSection,
    DocumentStructureResult,
    DocumentTemplateClassificationResult,
    NotesContentConservation,
    SectionClassificationOutcome,
    SectionClassificationOutcomeType,
    TemplateGroupAssignment,
    TemplateGroupAssignmentMethod,
)
from services.section_aware_initial_mapping import source_rows_from_normalized_candidates
from services.template_group_registry import load_template_group_registry, semantic_inventory_sha256
from services.toc_aware_document_structure import FEATURE_VERSION, persist_document_structure
from services.toc_aware_template_classification import (
    CLASSIFICATION_VERSION,
    document_structure_hash,
    persist_template_classification,
)


FIXED_TIME = datetime(2026, 8, 5, tzinfo=timezone.utc)


def persist_mapping_sources(
    *,
    job_id: int = 101,
    group_ids=("210000",),
    candidates=None,
    outcome="matched",
):
    candidates = list(
        candidates
        or [
            {
                "original_candidate_id": "row-1",
                "row_type": "numeric_fact",
                "label": "Cash and cash equivalents",
                "value": "1,234",
                "previous_value": "1,000",
                "current_year": 2025,
                "prior_year": 2024,
                "page_number": 2,
                "statement_section": "Statement of Financial Position",
                "provenance": {"table_index": 0, "row_index": 1},
            }
        ]
    )
    item_ids = {
        str(candidate.get("original_candidate_id") or f"row-{index + 1}"): str(candidate.get("persisted_id") or f"persisted-row-{index + 1}")
        for index, candidate in enumerate(candidates)
        if candidate.get("row_type") not in {"heading", "text_block", "metadata"}
    }
    source_rows = source_rows_from_normalized_candidates(
        candidates,
        item_ids_by_original_candidate=item_ids,
    )
    persisted_row_ids = list(item_ids.values())
    section = DocumentSection(
        section_id="section-1",
        job_id=job_id,
        raw_title="Statement of Financial Position",
        normalized_title="statement of financial position",
        canonical_section_type="statement_of_financial_position",
        toc_entry_id="toc-1",
        section_order=0,
        pdf_page_start=1,
        pdf_page_end=3,
        azure_page_start=2,
        azure_page_end=4,
        confidence=0.99,
        grouping_method="fixture",
        extracted_row_ids=persisted_row_ids,
    )
    evidence = [
        DocumentContentEvidence(
            content_id=row_id,
            content_type="extracted_row",
            text_evidence=next((row["label"] for row in source_rows if row["source_row_id"] == row_id), None),
            pdf_page_indexes=[1],
            azure_page_numbers=[2],
            provenance={"original_candidate_id": original_id},
        )
        for original_id, row_id in item_ids.items()
    ]
    structure = DocumentStructureResult(
        job_id=job_id,
        document_id=f"filing-job-{job_id}",
        feature_version=FEATURE_VERSION,
        toc_detected=True,
        toc_confidence=1.0,
        page_mapping_confidence=1.0,
        section_count=1,
        sections=[section],
        content_evidence=evidence,
        safety_summary={"content_conservation_passed": True, "dropped_content_count": 0},
        generated_at=FIXED_TIME,
    )
    registry = load_template_group_registry()
    by_group = {str(item["template_group_id"]): item for item in registry["template_groups"]}
    assignments = [
        TemplateGroupAssignment(
            assignment_id=f"assignment-{group_id}",
            source_section_id="section-1",
            template_group_id=group_id,
            template_code=group_id,
            canonical_template_name=by_group[group_id]["canonical_name"],
            assignment_method=TemplateGroupAssignmentMethod.DETERMINISTIC_EXACT,
            confidence=1.0,
            evidence=["fixture classification"],
            requires_human_review=False,
        )
        for group_id in group_ids
    ]
    classification = DocumentTemplateClassificationResult(
        job_id=job_id,
        filing_id=job_id,
        source_structure_artifact_version=structure.feature_version,
        source_structure_hash=document_structure_hash(structure),
        classification_version=CLASSIFICATION_VERSION,
        canonical_registry_version=str(registry.get("semantic_inventory_version") or "mpers-2022-v1"),
        canonical_registry_hash=semantic_inventory_sha256(registry),
        total_primary_sections=1,
        matched_count=1 if outcome == "matched" else 0,
        narrative_only_count=1 if outcome == "narrative_only" else 0,
        outcomes=[
            SectionClassificationOutcome(
                section_id="section-1",
                raw_title=section.raw_title,
                normalized_title=section.normalized_title,
                canonical_section_type=section.canonical_section_type,
                section_level=1,
                outcome=SectionClassificationOutcomeType(outcome),
                assignments=assignments if outcome in {"matched", "multiple_templates"} else [],
                confidence=1.0,
                evidence=["fixture"],
                requires_human_review=False,
            )
        ],
        notes_conservation=NotesContentConservation(passed=True),
        safety_summary={"canonical_registry_only": True},
        generated_at=FIXED_TIME,
    )
    persist_document_structure(structure)
    persist_template_classification(classification, structure=structure)
    return structure, classification, source_rows
