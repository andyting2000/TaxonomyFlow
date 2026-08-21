"""Bounded, leakage-safe context construction for #19B fallback classification."""

from __future__ import annotations

import json
from typing import Iterable, Sequence

from config import settings
from schemas import DocumentContentEvidence, TemplateGroupCard


def _limit(name: str, fallback: int) -> int:
    return max(
        1,
        int(
            getattr(
                settings,
                f"toc_aware_template_classification_{name}",
                fallback,
            )
            or fallback
        ),
    )


def _text(value) -> str:
    return " ".join(str(value or "").split())


def _card_payload(card: TemplateGroupCard) -> dict:
    return {
        "template_group_id": card.template_group_id,
        "canonical_name": card.canonical_name,
        "official_role_definition": card.official_role_definition,
        "template_kind": card.template_kind,
        "statement_family": card.statement_family,
        "aliases": [
            alias
            for alias in card.aliases
            if alias not in card.legacy_aliases_not_for_classification
        ],
        "positive_indicators": card.positive_indicators,
        "exclusion_indicators": card.exclusion_indicators,
    }


def build_template_classification_context(
    *,
    source_section_id: str,
    source_title: str,
    normalized_title: str,
    parent_title: str | None,
    page_range: dict,
    nearby_headings: Iterable[str],
    evidence: Iterable[DocumentContentEvidence],
    template_cards: Sequence[TemplateGroupCard],
) -> dict:
    """Build a bounded JSON-ready payload and account for every omitted item."""
    max_characters = _limit("max_characters", 12000)
    limits = {
        "paragraphs": _limit("max_paragraphs", 12),
        "table_headers": _limit("max_table_headers", 12),
        "row_labels": _limit("max_row_labels", 20),
        "template_cards": _limit("max_template_cards", 8),
    }
    paragraphs: list[str] = []
    table_headers: list[str] = []
    row_labels: list[str] = []
    for item in evidence:
        text = _text(item.text_evidence)
        if not text:
            continue
        provenance = item.provenance or {}
        if item.content_type in {"paragraph", "text_block", "heading"}:
            paragraphs.append(text)
        elif item.content_type == "table_cell" and (
            int(provenance.get("row_index") or 0) == 0
            or str(provenance.get("kind") or "").lower()
            in {"columnheader", "rowheader"}
        ):
            table_headers.append(text)
        elif item.content_type == "extracted_row":
            row_labels.append(text)

    original_counts = {
        "paragraphs": len(paragraphs),
        "table_headers": len(table_headers),
        "row_labels": len(row_labels),
        "template_cards": len(template_cards),
    }
    payload = {
        "source_section_id": source_section_id,
        "source_title": _text(source_title),
        "normalized_title": _text(normalized_title),
        "parent_title": _text(parent_title) or None,
        "page_range": dict(page_range),
        "nearby_headings": [
            _text(value)
            for value in nearby_headings
            if _text(value)
        ][: limits["paragraphs"]],
        "paragraphs": paragraphs[: limits["paragraphs"]],
        "table_headers": table_headers[: limits["table_headers"]],
        "representative_row_labels": row_labels[: limits["row_labels"]],
        "template_group_cards": [
            _card_payload(card)
            for card in template_cards[: limits["template_cards"]]
        ],
        "do_not_confuse": [
            "notes_container is structural and has no taxonomy template code",
            "730000 is Notes - List of notes, not the Notes parent",
            "legacy display labels are not semantic authority",
        ],
    }
    omitted = {
        key: max(0, original_counts[key] - len(payload[
            "representative_row_labels" if key == "row_labels"
            else "template_group_cards" if key == "template_cards"
            else key
        ]))
        for key in original_counts
    }

    payload["limits"] = {
        **limits,
        "max_characters": max_characters,
    }
    payload["omitted_counts"] = omitted
    payload["truncated"] = any(omitted.values())
    payload["safety"] = {
        "source_is_bounded_19a_artifact": True,
        "auditor_xml_included": False,
        "parsed_auditor_xbrl_facts_included": False,
        "expected_template_ids_included": False,
        "evaluation_labels_included": False,
        "taxonomy_qname_answers_included": False,
        "final_mapping_results_included": False,
    }
    # Preserve valid structured JSON by removing complete low-priority items
    # until the configured character boundary is met. Account for the safety
    # and truncation metadata itself before enforcing the final byte shape.
    shrink_order = (
        "paragraphs",
        "representative_row_labels",
        "table_headers",
        "nearby_headings",
        "template_group_cards",
    )
    while len(json.dumps(payload, ensure_ascii=False)) > max_characters:
        removed = False
        for key in shrink_order:
            if payload[key]:
                payload[key].pop()
                omitted_key = (
                    "row_labels"
                    if key == "representative_row_labels"
                    else "template_cards"
                    if key == "template_group_cards"
                    else key
                )
                if omitted_key in omitted:
                    omitted[omitted_key] += 1
                payload["truncated"] = True
                removed = True
                break
        if not removed:
            raise ValueError("Classification context metadata exceeds character limit")
    return payload
