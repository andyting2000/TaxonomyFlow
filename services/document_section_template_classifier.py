"""Deterministic-first section classification against the canonical registry."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from schemas import (
    DocumentContentEvidence,
    DocumentSection,
    NoteSubsection,
    SectionClassificationOutcome,
    SectionClassificationOutcomeType,
    TemplateGroupAssignment,
    TemplateGroupAssignmentMethod,
    TemplateGroupCard,
)
from services.section_title_normalization import normalize_title_text
from services.template_group_registry import (
    TemplateGroupRegistryError,
    load_template_group_registry,
    semantic_inventory_sha256,
)


EXPECTED_REGISTRY_SEMANTIC_HASH = (
    "16de7eaeafcdf760c7f4869072a6b0a3925088f6bc260672389b5c502015b7d4"
)
NARRATIVE_SECTION_TYPES = {
    "directors_report",
    "statement_by_directors",
    "statutory_declaration",
    "independent_auditors_report",
    "company_information",
    "director_business_review",
}
SOURCE_TYPE_EQUIVALENTS = {
    "income_statement": "statement_of_profit_or_loss",
}


def _normalized(value: Any) -> str:
    return normalize_title_text(value)


def load_template_group_cards() -> tuple[list[TemplateGroupCard], dict[str, str]]:
    """Load and validate all 24 classification cards without legacy fallback."""
    registry = load_template_group_registry(validate_sources=True)
    semantic_hash = semantic_inventory_sha256(registry)
    if semantic_hash != EXPECTED_REGISTRY_SEMANTIC_HASH:
        raise TemplateGroupRegistryError(
            "Canonical template registry semantic hash is not approved for #19B"
        )
    records = registry.get("template_groups") or []
    if len(records) != 24:
        raise TemplateGroupRegistryError("Canonical template registry must contain 24 records")

    cards: list[TemplateGroupCard] = []
    durable_ids: set[str] = set()
    role_uris: set[str] = set()
    for record in records:
        metadata = record.get("classification_metadata") or {}
        compatibility = record.get("compatibility") or {}
        template_group_id = str(record.get("template_group_id") or "")
        role_uri = str(record.get("role_uri") or "")
        if not template_group_id or template_group_id in durable_ids:
            raise TemplateGroupRegistryError("Template-group durable IDs must be unique")
        if not role_uri.startswith("http") or role_uri in role_uris:
            raise TemplateGroupRegistryError("Template-group role URIs must be valid and unique")
        durable_ids.add(template_group_id)
        role_uris.add(role_uri)
        cards.append(
            TemplateGroupCard(
                template_group_id=template_group_id,
                code=str(record["code"]),
                role_uri=role_uri,
                official_role_definition=str(record["official_role_definition"]),
                canonical_name=str(record["canonical_name"]),
                user_display_name=str(record["user_display_name"]),
                normalized_name=str(record["normalized_name"]),
                template_kind=str(record["template_kind"]),
                structural_role=str(record["structural_role"]),
                statement_family=str(record["statement_family"]),
                aliases=[str(value) for value in record.get("aliases") or []],
                classification_enabled=bool(record["classification_enabled"]),
                mapping_enabled=bool(record["mapping_enabled"]),
                allows_multiple_source_sections=bool(
                    record["allows_multiple_source_sections"]
                ),
                expected_source_section_types=[
                    str(value)
                    for value in metadata.get("expected_source_section_types") or []
                ],
                positive_indicators=[
                    str(value)
                    for value in metadata.get("positive_title_indicators") or []
                ],
                exclusion_indicators=[
                    str(value)
                    for value in metadata.get("exclusion_indicators") or []
                ],
                source_taxonomy_version=str(record["source_taxonomy_version"]),
                semantic_hash=semantic_hash,
                primary_deterministic_classification_allowed=bool(
                    metadata.get("primary_deterministic_classification_allowed")
                ),
                note_subsection_classification_allowed=bool(
                    metadata.get("note_subsection_classification_allowed")
                ),
                multiple_assignments_allowed=bool(
                    metadata.get("multiple_assignments_allowed")
                ),
                legacy_aliases_not_for_classification=(
                    [
                        str(value)
                        for value in compatibility.get("legacy_name_aliases") or []
                    ]
                    if compatibility.get("legacy_alias_classification_eligible") is False
                    else []
                ),
            )
        )
    by_code = {card.code: card for card in cards}
    if by_code["730000"].canonical_name != "Notes - List of notes":
        raise TemplateGroupRegistryError("730000 must remain Notes - List of notes")
    return cards, {
        "registry_version": str(registry["semantic_inventory_version"]),
        "registry_hash": semantic_hash,
        "source_taxonomy_version": str(registry["source_taxonomy_version"]),
    }


def _page_range(section: DocumentSection) -> dict[str, int | None]:
    return {
        "pdf_page_start": section.pdf_page_start,
        "pdf_page_end": section.pdf_page_end,
        "azure_page_start": section.azure_page_start,
        "azure_page_end": section.azure_page_end,
    }


def _eligible_labels(card: TemplateGroupCard) -> list[tuple[str, str]]:
    blocked = {_normalized(value) for value in card.legacy_aliases_not_for_classification}
    values = [
        (card.canonical_name, "canonical"),
        (card.user_display_name, "display"),
        (card.official_role_definition.removeprefix(f"[{card.code}]").strip(), "official"),
        *((alias, "alias") for alias in card.aliases),
    ]
    return [
        (_normalized(value), kind)
        for value, kind in values
        if _normalized(value) and _normalized(value) not in blocked
    ]


def _assignment(
    *,
    card: TemplateGroupCard,
    source_section_id: str,
    parent_section_id: str | None,
    method: TemplateGroupAssignmentMethod,
    confidence: float,
    evidence: Iterable[str],
    alternatives: Iterable[str] = (),
    requires_human_review: bool = False,
    warnings: Iterable[str] = (),
) -> TemplateGroupAssignment:
    return TemplateGroupAssignment(
        assignment_id=f"{source_section_id}:{card.template_group_id}",
        source_section_id=source_section_id,
        parent_section_id=parent_section_id,
        template_group_id=card.template_group_id,
        template_code=card.code,
        canonical_template_name=card.canonical_name,
        assignment_method=method,
        confidence=round(confidence, 4),
        evidence=list(dict.fromkeys(str(value) for value in evidence if str(value))),
        alternative_template_group_ids=list(dict.fromkeys(alternatives)),
        requires_human_review=requires_human_review,
        warnings=list(dict.fromkeys(warnings)),
    )


def _context_text(
    section: DocumentSection,
    content_evidence: Iterable[DocumentContentEvidence],
) -> str:
    section_ids = {
        *section.text_block_ids,
        *section.heading_ids,
        *section.table_cell_ids,
        *section.extracted_row_ids,
    }
    values = [section.raw_title, section.normalized_title]
    values.extend(
        evidence.text_evidence or ""
        for evidence in content_evidence
        if evidence.content_id in section_ids
    )
    return _normalized(" ".join(values))


def _candidate_scores(
    cards: Iterable[TemplateGroupCard],
    context: str,
) -> list[tuple[TemplateGroupCard, int, list[str], list[str]]]:
    rows = []
    for card in cards:
        positives = [
            indicator
            for indicator in card.positive_indicators
            if _normalized(indicator) and _normalized(indicator) in context
        ]
        exclusions = [
            indicator
            for indicator in card.exclusion_indicators
            if _normalized(indicator) and _normalized(indicator) in context
        ]
        rows.append((card, len(positives), positives, exclusions))
    return rows


def _has_variant_qualifier(value: str) -> bool:
    return any(
        qualifier in value
        for qualifier in {
            "current non current",
            "order of liquidity",
            "by function",
            "by nature",
            "direct method",
            "indirect method",
            "before tax",
            "net of tax",
            "retained earnings",
        }
    )


def classify_primary_section(
    section: DocumentSection,
    *,
    cards: Sequence[TemplateGroupCard],
    content_evidence: Iterable[DocumentContentEvidence] = (),
) -> SectionClassificationOutcome:
    """Classify one #19A primary section or safely abstain."""
    canonical_type = section.canonical_section_type
    base = {
        "raw_title": section.raw_title,
        "normalized_title": section.normalized_title,
        "canonical_section_type": canonical_type,
        "page_range": _page_range(section),
    }
    if canonical_type in NARRATIVE_SECTION_TYPES:
        return SectionClassificationOutcome(
            section_id=section.section_id,
            section_level=section.section_level,
            parent_section_id=section.parent_section_id,
            outcome=SectionClassificationOutcomeType.NARRATIVE_ONLY,
            confidence=1.0,
            evidence=[f"canonical_section_type={canonical_type}"],
            **base,
        )
    if canonical_type == "notes_to_financial_statements":
        return SectionClassificationOutcome(
            section_id="notes_container",
            section_level=section.section_level + 1,
            parent_section_id=section.section_id,
            outcome=SectionClassificationOutcomeType.CONTAINER_ONLY,
            confidence=1.0,
            evidence=[
                "Canonical structural navigation node notes_container",
                "730000 is a taxonomy leaf and is not the Notes parent",
            ],
            **base,
        )

    expected_type = SOURCE_TYPE_EQUIVALENTS.get(canonical_type, canonical_type)
    candidates = [
        card
        for card in cards
        if card.classification_enabled
        and card.primary_deterministic_classification_allowed
        and expected_type in card.expected_source_section_types
    ]
    context = _context_text(section, content_evidence)
    title = _normalized(section.raw_title)

    exact_matches = [
        (card, label_kind)
        for card in candidates
        for label, label_kind in _eligible_labels(card)
        if title == label
    ]
    if len(exact_matches) == 1 and (
        len(candidates) == 1
        or exact_matches[0][1] in {"canonical", "official"}
        or _has_variant_qualifier(title)
    ):
        card, label_kind = exact_matches[0]
        method = (
            TemplateGroupAssignmentMethod.DETERMINISTIC_ALIAS
            if label_kind in {"alias", "display"}
            else TemplateGroupAssignmentMethod.DETERMINISTIC_EXACT
        )
        assignment = _assignment(
            card=card,
            source_section_id=section.section_id,
            parent_section_id=section.parent_section_id,
            method=method,
            confidence=0.99,
            evidence=[f"exact {label_kind} title match: {section.raw_title}"],
        )
        return SectionClassificationOutcome(
            section_id=section.section_id,
            section_level=section.section_level,
            parent_section_id=section.parent_section_id,
            outcome=SectionClassificationOutcomeType.MATCHED,
            assignments=[assignment],
            confidence=assignment.confidence,
            evidence=list(assignment.evidence),
            **base,
        )

    if len(candidates) == 1:
        card = candidates[0]
        assignment = _assignment(
            card=card,
            source_section_id=section.section_id,
            parent_section_id=section.parent_section_id,
            method=TemplateGroupAssignmentMethod.DETERMINISTIC_RULE,
            confidence=0.96,
            evidence=[f"unique canonical section route: {canonical_type}"],
        )
        return SectionClassificationOutcome(
            section_id=section.section_id,
            section_level=section.section_level,
            parent_section_id=section.parent_section_id,
            outcome=SectionClassificationOutcomeType.MATCHED,
            assignments=[assignment],
            confidence=assignment.confidence,
            evidence=list(assignment.evidence),
            **base,
        )

    scored = _candidate_scores(candidates, context)
    viable = [row for row in scored if row[1] > 0 and not row[3]]
    viable.sort(key=lambda row: (-row[1], row[0].template_group_id))
    if viable and (len(viable) == 1 or viable[0][1] > viable[1][1]):
        card, score, positives, _exclusions = viable[0]
        assignment = _assignment(
            card=card,
            source_section_id=section.section_id,
            parent_section_id=section.parent_section_id,
            method=TemplateGroupAssignmentMethod.DETERMINISTIC_RULE,
            confidence=min(0.97, 0.88 + (0.02 * score)),
            evidence=[f"qualifier indicator: {value}" for value in positives],
        )
        return SectionClassificationOutcome(
            section_id=section.section_id,
            section_level=section.section_level,
            parent_section_id=section.parent_section_id,
            outcome=SectionClassificationOutcomeType.MATCHED,
            assignments=[assignment],
            confidence=assignment.confidence,
            evidence=list(assignment.evidence),
            **base,
        )

    alternatives = [card.template_group_id for card in candidates]
    warnings = (
        ["presentation_variant_qualifier_insufficient"]
        if alternatives
        else ["no_canonical_primary_template_candidate"]
    )
    return SectionClassificationOutcome(
        section_id=section.section_id,
        section_level=section.section_level,
        parent_section_id=section.parent_section_id,
        outcome=(
            SectionClassificationOutcomeType.AMBIGUOUS
            if alternatives
            else SectionClassificationOutcomeType.UNASSIGNED
        ),
        alternative_template_group_ids=alternatives,
        confidence=0.35 if alternatives else 0.0,
        evidence=[f"canonical_section_type={canonical_type}"],
        warnings=warnings,
        requires_human_review=True,
        **base,
    )


def classify_note_subsection(
    subsection: NoteSubsection,
    *,
    cards: Sequence[TemplateGroupCard],
    context_fragments: Iterable[str] = (),
) -> SectionClassificationOutcome:
    """Classify one Notes child using only registry semantics and bounded context."""
    note_cards = [
        card
        for card in cards
        if card.classification_enabled and card.note_subsection_classification_allowed
    ]
    title = _normalized(subsection.note_label or subsection.raw_heading)
    context = _normalized(
        " ".join([subsection.raw_heading, subsection.note_label, *context_fragments])
    )
    base = {
        "section_id": subsection.child_section_id,
        "raw_title": subsection.raw_heading,
        "normalized_title": subsection.normalized_heading,
        "canonical_section_type": "note_subsection",
        "section_level": 3,
        "parent_section_id": subsection.parent_section_id,
        "page_range": {
            "pdf_page_start": subsection.pdf_page_start,
            "pdf_page_end": subsection.pdf_page_end,
            "azure_page_start": subsection.azure_page_start,
            "azure_page_end": subsection.azure_page_end,
        },
    }
    exact = [
        (card, kind)
        for card in note_cards
        for label, kind in _eligible_labels(card)
        if title == label
    ]
    if len(exact) == 1:
        card, kind = exact[0]
        method = (
            TemplateGroupAssignmentMethod.DETERMINISTIC_ALIAS
            if kind in {"alias", "display"}
            else TemplateGroupAssignmentMethod.DETERMINISTIC_EXACT
        )
        assignment = _assignment(
            card=card,
            source_section_id=subsection.child_section_id,
            parent_section_id=subsection.parent_section_id,
            method=method,
            confidence=0.99,
            evidence=[f"exact {kind} note-title match: {subsection.note_label}"],
        )
        return SectionClassificationOutcome(
            outcome=SectionClassificationOutcomeType.MATCHED,
            assignments=[assignment],
            confidence=assignment.confidence,
            evidence=list(assignment.evidence),
            **base,
        )

    scored = _candidate_scores(note_cards, context)
    positive_matches = [row for row in scored if row[1] > 0]
    matches = [
        row
        for row in positive_matches
        if not row[3]
        or (
            len(positive_matches) > 1
            and row[0].multiple_assignments_allowed
        )
    ]
    # Require an indicator beyond a generic "note" token. Registry indicators
    # are phrases, so every retained row has concrete semantic evidence.
    matches.sort(key=lambda row: (-row[1], row[0].template_group_id))
    if not matches:
        return SectionClassificationOutcome(
            outcome=SectionClassificationOutcomeType.UNASSIGNED,
            confidence=0.0,
            warnings=["no_canonical_note_template_match"],
            requires_human_review=True,
            **base,
        )

    top_score = matches[0][1]
    selected = [row for row in matches if row[1] == top_score]
    if len(selected) > 1 and all(row[0].multiple_assignments_allowed for row in selected):
        assignments = [
            _assignment(
                card=card,
                source_section_id=subsection.child_section_id,
                parent_section_id=subsection.parent_section_id,
                method=TemplateGroupAssignmentMethod.DETERMINISTIC_RULE,
                confidence=min(0.94, 0.84 + (0.03 * score)),
                evidence=[f"note indicator: {value}" for value in positives],
                requires_human_review=False,
            )
            for card, score, positives, _exclusions in selected
        ]
        return SectionClassificationOutcome(
            outcome=SectionClassificationOutcomeType.MULTIPLE_TEMPLATES,
            assignments=assignments,
            confidence=min(item.confidence for item in assignments),
            evidence=[
                evidence
                for assignment in assignments
                for evidence in assignment.evidence
            ],
            **base,
        )

    card, score, positives, _exclusions = selected[0]
    assignment = _assignment(
        card=card,
        source_section_id=subsection.child_section_id,
        parent_section_id=subsection.parent_section_id,
        method=TemplateGroupAssignmentMethod.DETERMINISTIC_RULE,
        confidence=min(0.96, 0.87 + (0.03 * score)),
        evidence=[f"note indicator: {value}" for value in positives],
    )
    return SectionClassificationOutcome(
        outcome=SectionClassificationOutcomeType.MATCHED,
        assignments=[assignment],
        confidence=assignment.confidence,
        evidence=list(assignment.evidence),
        **base,
    )
