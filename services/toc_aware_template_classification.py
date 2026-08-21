"""#19B orchestration, versioned artifact persistence, and capability state."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Sequence
from uuid import uuid4

from config import settings
from file_safety import assert_upload_child, uploads_root
from schemas import (
    DocumentContentEvidence,
    DocumentStructureResult,
    DocumentTemplateClassificationResult,
    NotesContentConservation,
    SectionClassificationOutcome,
    SectionClassificationOutcomeType,
    TemplateClassificationCapabilitiesRead,
    TemplateGroupCard,
)
from services.document_section_template_classifier import (
    classify_note_subsection,
    classify_primary_section,
    load_template_group_cards,
)
from services.note_subsection_segmenter import segment_note_subsections
from services.template_classification_context_builder import (
    build_template_classification_context,
)
from services.template_group_llm_classifier import (
    PROMPT_VERSION,
    TemplateGroupLLMClient,
    TemplateGroupLLMError,
    classify_with_bounded_llm,
)
from services.template_group_registry import TemplateGroupRegistryError
from services.toc_aware_document_structure import (
    ARTIFACT_SUBDIRECTORY,
    FEATURE_VERSION as STRUCTURE_VERSION,
    load_document_structure,
)


CLASSIFICATION_VERSION = "19B-v2"
ARTIFACT_FILENAME = "template_classification_19b_v2.json"
MAX_ARTIFACT_BYTES = 25 * 1024 * 1024


class TemplateClassificationArtifactIdentityError(ValueError):
    def __init__(self, reason_code: str):
        super().__init__("Template classification artifact identity is stale or invalid")
        self.reason_code = reason_code


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def document_structure_hash(structure: DocumentStructureResult) -> str:
    payload = json.dumps(
        structure.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _outcome_page_range(outcome: SectionClassificationOutcome) -> dict:
    return dict(outcome.page_range)


def _evidence_by_id(
    evidence: Iterable[DocumentContentEvidence],
) -> dict[str, DocumentContentEvidence]:
    return {item.content_id: item for item in evidence}


def _subsection_evidence(subsection, by_id) -> list[DocumentContentEvidence]:
    references = {
        *subsection.heading_evidence,
        *subsection.paragraph_references,
        *subsection.table_references,
        *subsection.table_cell_references,
        *subsection.extracted_row_references,
        *subsection.other_evidence_references,
    }
    return [by_id[value] for value in references if value in by_id]


def _section_evidence(section, by_id) -> list[DocumentContentEvidence]:
    references = {
        *section.text_block_ids,
        *section.heading_ids,
        *section.table_ids,
        *section.table_cell_ids,
        *section.extracted_row_ids,
    }
    return [by_id[value] for value in references if value in by_id]


def _fallback_cards(
    outcome: SectionClassificationOutcome,
    cards: Sequence[TemplateGroupCard],
    *,
    note_subsection: bool,
    context_text: str,
) -> list[TemplateGroupCard]:
    by_id = {card.template_group_id: card for card in cards}
    if outcome.alternative_template_group_ids:
        return [
            by_id[value]
            for value in outcome.alternative_template_group_ids
            if value in by_id
        ]
    candidates = [
        card
        for card in cards
        if card.classification_enabled
        and (
            card.note_subsection_classification_allowed
            if note_subsection
            else card.primary_deterministic_classification_allowed
        )
    ]
    normalized = context_text.lower()
    candidates.sort(
        key=lambda card: (
            -sum(
                1
                for indicator in card.positive_indicators
                if indicator.lower() in normalized
            ),
            0 if card.template_kind in {"note_disclosure", "note_list"} else 1,
            card.template_group_id,
        )
    )
    return candidates


def _failed_fallback_outcome(
    outcome: SectionClassificationOutcome,
    warning: str,
) -> SectionClassificationOutcome:
    failed = outcome.model_copy(deep=True)
    failed.outcome = SectionClassificationOutcomeType.CLASSIFICATION_FAILED
    failed.assignments = []
    failed.confidence = 0.0
    failed.requires_human_review = True
    failed.llm_called = True
    failed.provider = "huggingface"
    failed.model = str(
        getattr(settings, "toc_aware_template_classification_model_id", "") or ""
    )
    failed.prompt_version = PROMPT_VERSION
    failed.warnings = list(dict.fromkeys([*failed.warnings, warning]))
    return failed


async def _maybe_fallback(
    outcome: SectionClassificationOutcome,
    *,
    cards: Sequence[TemplateGroupCard],
    evidence: Sequence[DocumentContentEvidence],
    parent_title: str | None,
    nearby_headings: Iterable[str],
    note_subsection: bool,
    llm_client: TemplateGroupLLMClient | None,
) -> SectionClassificationOutcome:
    if outcome.outcome not in {
        SectionClassificationOutcomeType.AMBIGUOUS,
        SectionClassificationOutcomeType.UNASSIGNED,
    }:
        return outcome
    if not bool(
        getattr(
            settings,
            "toc_aware_template_classification_live_llm_enabled",
            False,
        )
    ):
        return outcome
    context_text = " ".join(
        [
            outcome.raw_title,
            *(item.text_evidence or "" for item in evidence),
        ]
    )
    candidate_cards = _fallback_cards(
        outcome,
        cards,
        note_subsection=note_subsection,
        context_text=context_text,
    )
    context = build_template_classification_context(
        source_section_id=outcome.section_id,
        source_title=outcome.raw_title,
        normalized_title=outcome.normalized_title,
        parent_title=parent_title,
        page_range=outcome.page_range,
        nearby_headings=nearby_headings,
        evidence=evidence,
        template_cards=candidate_cards,
    )
    try:
        return await classify_with_bounded_llm(
            context=context,
            cards=candidate_cards,
            source_section_id=outcome.section_id,
            raw_title=outcome.raw_title,
            normalized_title=outcome.normalized_title,
            canonical_section_type=outcome.canonical_section_type,
            parent_section_id=outcome.parent_section_id,
            section_level=outcome.section_level,
            page_range=_outcome_page_range(outcome),
            client=llm_client,
        )
    except TemplateGroupLLMError:
        return _failed_fallback_outcome(outcome, "bounded_llm_response_rejected")


async def analyze_template_classification(
    *,
    job_id: int,
    structure: DocumentStructureResult,
    filing_id: int | None = None,
    llm_client: TemplateGroupLLMClient | None = None,
    generated_at: datetime | None = None,
) -> DocumentTemplateClassificationResult:
    """Classify one validated #19A result without changing extraction or mapping."""
    if structure.job_id != int(job_id) or structure.feature_version != STRUCTURE_VERSION:
        raise ValueError("Source structure artifact identity mismatch")
    cards, registry_metadata = load_template_group_cards()
    by_id = _evidence_by_id(structure.content_evidence)
    outcomes: list[SectionClassificationOutcome] = []
    for section in structure.sections:
        outcome = classify_primary_section(
            section,
            cards=cards,
            content_evidence=structure.content_evidence,
        )
        section_evidence = _section_evidence(section, by_id)
        outcome = await _maybe_fallback(
            outcome,
            cards=cards,
            evidence=section_evidence,
            parent_title=None,
            nearby_headings=[
                candidate.raw_title
                for candidate in structure.sections
                if candidate.section_id != section.section_id
            ][:6],
            note_subsection=False,
            llm_client=llm_client,
        )
        outcomes.append(outcome)

    subsections, conservation, segmentation_warnings = segment_note_subsections(
        structure
    )
    for subsection in subsections:
        child_evidence = _subsection_evidence(subsection, by_id)
        child = classify_note_subsection(
            subsection,
            cards=cards,
            context_fragments=[
                item.text_evidence or ""
                for item in child_evidence
            ],
        )
        child = await _maybe_fallback(
            child,
            cards=cards,
            evidence=child_evidence,
            parent_title="Notes to Financial Statements",
            nearby_headings=[
                candidate.raw_heading
                for candidate in subsections
                if candidate.child_section_id != subsection.child_section_id
            ][:6],
            note_subsection=True,
            llm_client=llm_client,
        )
        outcomes.append(child)

    count = lambda value: sum(1 for item in outcomes if item.outcome == value)
    deterministic_count = sum(
        1
        for item in outcomes
        if not item.llm_called
        and item.outcome
        in {
            SectionClassificationOutcomeType.MATCHED,
            SectionClassificationOutcomeType.MULTIPLE_TEMPLATES,
            SectionClassificationOutcomeType.NARRATIVE_ONLY,
            SectionClassificationOutcomeType.CONTAINER_ONLY,
        }
    )
    llm_count = sum(1 for item in outcomes if item.llm_called)
    warnings = list(
        dict.fromkeys(
            [
                *segmentation_warnings,
                *(
                    ["classification_contains_failed_outcomes"]
                    if count(SectionClassificationOutcomeType.CLASSIFICATION_FAILED)
                    else []
                ),
                *(
                    ["classification_contains_ambiguous_outcomes"]
                    if count(SectionClassificationOutcomeType.AMBIGUOUS)
                    else []
                ),
                *(
                    ["classification_contains_unassigned_outcomes"]
                    if count(SectionClassificationOutcomeType.UNASSIGNED)
                    else []
                ),
            ]
        )
    )
    safety_summary = {
        "canonical_registry_only": True,
        "registry_validated_before_classification": True,
        "deterministic_first": True,
        "live_llm_enabled": bool(
            getattr(
                settings,
                "toc_aware_template_classification_live_llm_enabled",
                False,
            )
        ),
        "llm_calls_made": llm_count,
        "maximum_llm_calls_per_outcome": 1,
        "notes_content_conservation_passed": conservation.passed,
        "dropped_notes_content_count": conservation.dropped_items,
        "notes_segmentation_metrics": conservation.segmentation_metrics.model_dump(
            mode="json"
        ),
        "taxonomy_qname_selection_performed": False,
        "template_values_mutated": False,
        "template_tags_mutated": False,
        "mapping_suggestions_mutated": False,
        "confirmed_tag_id_mutations": 0,
        "final_mapping_mutations": 0,
        "database_writes": 0,
        "azure_provider_calls_made": 0,
        "auditor_xml_sent_externally": False,
        "parsed_auditor_xbrl_sent_externally": False,
        "expected_classifications_sent_externally": False,
        "xbrl_generated": False,
        "arelle_run": False,
    }
    return DocumentTemplateClassificationResult(
        job_id=int(job_id),
        filing_id=int(filing_id if filing_id is not None else job_id),
        source_structure_artifact_version=structure.feature_version,
        source_structure_hash=document_structure_hash(structure),
        classification_version=CLASSIFICATION_VERSION,
        canonical_registry_version=registry_metadata["registry_version"],
        canonical_registry_hash=registry_metadata["registry_hash"],
        total_primary_sections=len(structure.sections),
        total_note_subsections=len(subsections),
        matched_count=count(SectionClassificationOutcomeType.MATCHED),
        multiple_template_count=count(
            SectionClassificationOutcomeType.MULTIPLE_TEMPLATES
        ),
        narrative_only_count=count(
            SectionClassificationOutcomeType.NARRATIVE_ONLY
        ),
        container_only_count=count(
            SectionClassificationOutcomeType.CONTAINER_ONLY
        ),
        ambiguous_count=count(SectionClassificationOutcomeType.AMBIGUOUS),
        unassigned_count=count(SectionClassificationOutcomeType.UNASSIGNED),
        failed_count=count(
            SectionClassificationOutcomeType.CLASSIFICATION_FAILED
        ),
        deterministic_count=deterministic_count,
        llm_count=llm_count,
        outcomes=outcomes,
        note_subsections=subsections,
        notes_conservation=conservation,
        warnings=warnings,
        safety_summary=safety_summary,
        generated_at=generated_at or _utc_now(),
    )


def template_classification_artifact_path(job_id: int) -> Path:
    resolved_job_id = int(job_id)
    if resolved_job_id <= 0:
        raise ValueError("job_id must be positive")
    path = (
        uploads_root()
        / ARTIFACT_SUBDIRECTORY
        / f"job_{resolved_job_id}"
        / ARTIFACT_FILENAME
    )
    return assert_upload_child(str(path), ARTIFACT_SUBDIRECTORY)


def _validate_artifact_identity(
    result: DocumentTemplateClassificationResult,
    *,
    job_id: int,
    structure: DocumentStructureResult,
) -> None:
    try:
        _cards, registry = load_template_group_cards()
    except Exception as exc:
        raise TemplateClassificationArtifactIdentityError(
            "registry_hash_mismatch"
        ) from exc
    if (
        result.job_id != int(job_id)
        or result.filing_id != int(job_id)
        or result.classification_version != CLASSIFICATION_VERSION
    ):
        raise TemplateClassificationArtifactIdentityError(
            "upstream_classification_invalid"
        )
    if (
        result.source_structure_artifact_version != structure.feature_version
        or result.source_structure_hash != document_structure_hash(structure)
    ):
        raise TemplateClassificationArtifactIdentityError("upstream_hash_mismatch")
    if (
        result.canonical_registry_version != registry["registry_version"]
        or result.canonical_registry_hash != registry["registry_hash"]
    ):
        raise TemplateClassificationArtifactIdentityError("registry_hash_mismatch")


def persist_template_classification(
    result: DocumentTemplateClassificationResult,
    *,
    structure: DocumentStructureResult | None = None,
) -> Path:
    source = structure or load_document_structure(result.job_id)
    _validate_artifact_identity(result, job_id=result.job_id, structure=source)
    path = template_classification_artifact_path(result.job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = assert_upload_child(
        str(path.with_name(f".{path.name}.{uuid4().hex}.tmp")),
        ARTIFACT_SUBDIRECTORY,
    )
    payload = result.model_dump_json(indent=2)
    if len(payload.encode("utf-8")) > MAX_ARTIFACT_BYTES:
        raise ValueError("Template classification artifact exceeds size limit")
    try:
        temporary.write_text(payload + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def load_template_classification(
    job_id: int,
    *,
    structure: DocumentStructureResult | None = None,
) -> DocumentTemplateClassificationResult:
    path = template_classification_artifact_path(job_id)
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ValueError("Template classification artifact exceeds size limit")
    result = DocumentTemplateClassificationResult.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    source = structure or load_document_structure(job_id)
    _validate_artifact_identity(result, job_id=job_id, structure=source)
    return result


def discard_template_classification_artifact(job_id: int) -> bool:
    path = template_classification_artifact_path(job_id)
    if not path.exists():
        return False
    if not path.is_file():
        raise ValueError("Template classification artifact path is not a file")
    path.unlink()
    return True


def template_classification_capabilities(
    job_id: int,
    *,
    job_status: str | None = None,
) -> TemplateClassificationCapabilitiesRead:
    enabled = bool(
        getattr(settings, "toc_aware_template_classification_enabled", False)
    )
    persistence_enabled = bool(
        getattr(
            settings,
            "toc_aware_template_classification_persistence_enabled",
            False,
        )
    )
    live_llm_enabled = bool(
        getattr(
            settings,
            "toc_aware_template_classification_live_llm_enabled",
            False,
        )
    )
    warnings: list[str] = []
    try:
        _cards, registry = load_template_group_cards()
        registry_version = registry["registry_version"]
        registry_hash = registry["registry_hash"]
    except TemplateGroupRegistryError:
        registry_version = "invalid"
        registry_hash = ""
        warnings.append("canonical_template_registry_invalid")

    path = template_classification_artifact_path(job_id)
    persisted = path.is_file()
    structure = None
    source_hash = None
    try:
        structure = load_document_structure(job_id)
        source_hash = document_structure_hash(structure)
    except (FileNotFoundError, ValueError, TypeError):
        warnings.append("source_document_structure_unavailable")
    artifact_valid = False
    if persisted and structure is not None and registry_hash:
        try:
            load_template_classification(job_id, structure=structure)
            artifact_valid = True
        except (ValueError, TypeError, TemplateGroupRegistryError):
            warnings.append("template_classification_artifact_stale_or_invalid")

    resolved_job_status = getattr(job_status, "value", job_status)
    status_allows_result = (
        job_status is None
        or str(resolved_job_status).upper() in {"REVIEW", "COMPLETED"}
    )
    if persistence_enabled and not enabled:
        warnings.append("classification_persistence_inactive_without_classification")
    if enabled and not bool(getattr(settings, "toc_aware_pipeline_enabled", False)):
        warnings.append("classification_inactive_without_toc_aware_pipeline")
    if (
        persistence_enabled
        and not bool(
            getattr(settings, "toc_aware_structure_persistence_enabled", False)
        )
    ):
        warnings.append("classification_persistence_requires_structure_persistence")
    if live_llm_enabled and not enabled:
        warnings.append("classification_live_llm_inactive_without_classification")
    if enabled and persistence_enabled and not persisted:
        warnings.append("template_classification_not_generated")
    if persisted and not status_allows_result:
        warnings.append("template_classification_unavailable_for_job_status")
    available = (
        enabled
        and persistence_enabled
        and artifact_valid
        and status_allows_result
        and bool(registry_hash)
    )
    return TemplateClassificationCapabilitiesRead(
        classification_version=CLASSIFICATION_VERSION,
        enabled=enabled,
        persistence_enabled=persistence_enabled,
        live_llm_enabled=live_llm_enabled,
        available=available,
        result_persisted=persisted,
        registry_version=registry_version,
        registry_hash=registry_hash,
        source_structure_version=structure.feature_version if structure else None,
        source_structure_hash=source_hash,
        warnings=list(dict.fromkeys(warnings)),
    )


def classification_artifact_cleanup_candidate(job_id: int) -> tuple[str, str]:
    return str(template_classification_artifact_path(job_id)), ARTIFACT_SUBDIRECTORY
