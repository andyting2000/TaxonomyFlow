from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from schemas import (
    DocumentContentEvidence,
    DocumentSection,
    DocumentStructureResult,
)
from services.toc_aware_document_structure import FEATURE_VERSION


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "template_classification"
    / "fixtures_19b.json"
)


def fixtures():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["fixtures"]


def section(
    *,
    section_id: str = "section-1",
    canonical_section_type: str,
    title: str,
    page_start: int = 1,
    page_end: int = 1,
    references=(),
    candidate_note_heading_ids=(),
):
    return DocumentSection(
        section_id=section_id,
        job_id=101,
        raw_title=title,
        normalized_title=" ".join(title.lower().split()),
        canonical_section_type=canonical_section_type,
        toc_entry_id=f"toc-{section_id}",
        section_order=int(section_id.rsplit("-", 1)[-1]) - 1,
        pdf_page_start=page_start,
        pdf_page_end=page_end,
        azure_page_start=page_start + 1,
        azure_page_end=page_end + 1,
        confidence=0.95,
        grouping_method="fixture",
        heading_ids=list(references),
        text_block_ids=[],
        table_ids=[],
        table_cell_ids=[],
        extracted_row_ids=[],
        candidate_note_heading_ids=list(candidate_note_heading_ids),
    )


def evidence(
    content_id: str,
    text: str,
    *,
    page: int,
    top: float,
    content_type: str = "heading",
    pages=None,
    provenance=None,
):
    pdf_pages = list(pages if pages is not None else [page])
    return DocumentContentEvidence(
        content_id=content_id,
        content_type=content_type,
        text_evidence=text,
        pdf_page_indexes=pdf_pages,
        azure_page_numbers=[value + 1 for value in pdf_pages],
        bounding_evidence=[
            {
                "page_number": page + 1,
                "polygon": [
                    {"x": 0, "y": top},
                    {"x": 1, "y": top},
                ],
            }
        ],
        provenance=dict(provenance or {}),
    )


def structure(*, sections, content_evidence=(), job_id: int = 101):
    resolved_sections = list(sections)
    for item in resolved_sections:
        item.job_id = job_id
    return DocumentStructureResult(
        job_id=job_id,
        document_id=f"filing-job-{job_id}",
        feature_version=FEATURE_VERSION,
        toc_detected=True,
        toc_confidence=1.0,
        page_mapping_confidence=1.0,
        section_count=len(resolved_sections),
        sections=resolved_sections,
        content_evidence=list(content_evidence),
        safety_summary={
            "content_conservation_passed": True,
            "dropped_content_count": 0,
        },
        generated_at=datetime(2026, 7, 31, tzinfo=timezone.utc),
    )
