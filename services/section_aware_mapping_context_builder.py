"""Bounded, section-aware row context for the #19C Mapping LLM."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping, Sequence

from schemas import SectionAwareCandidateSet


CONTEXT_VERSION = "19C-row-context-v1"


@dataclass(frozen=True)
class MappingContextLimits:
    max_characters: int = 12000
    max_siblings: int = 4
    max_ancestors: int = 3
    max_descendants: int = 3
    max_candidate_cards: int = 8
    max_nearby_paragraphs: int = 2


def _text(value: Any, limit: int = 1000) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    return cleaned[:limit] if cleaned else None


def _label(row: Mapping[str, Any]) -> str | None:
    return _text(row.get("label") or row.get("extracted_label"), 500)


def _safe_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _candidate_payload(candidate) -> dict[str, Any]:
    card = candidate.concept_card
    return {
        "concept_id": card.concept_id,
        "qname": card.qname,
        "standard_label": card.standard_label,
        "terse_label": card.terse_label,
        "verbose_label": card.verbose_label,
        "documentation": _text(card.documentation, 600),
        "datatype": card.datatype,
        "period_type": card.period_type,
        "balance": card.balance,
        "abstract": card.abstract,
        "template_group_ids": card.template_group_ids,
        "statement_family": card.statement_family,
        "parent_concepts": card.parent_concepts[:4],
        "aliases": card.aliases[:12],
        "positive_indicators": card.positive_indicators[:8],
        "exclusion_indicators": card.exclusion_indicators[:8],
        "do_not_confuse": card.do_not_confuse[:8],
        "local_candidate_score": candidate.score.model_dump(mode="json"),
    }


def _serialized_size(payload: Mapping[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")))


def _trim_to_character_limit(payload: dict[str, Any], max_characters: int) -> None:
    removable_lists = [
        "nearby_explanatory_text",
        "child_labels",
        "sibling_labels",
        "ancestor_labels",
        "table_headers",
        "column_headers",
    ]
    while _serialized_size(payload) > max_characters:
        changed = False
        for key in removable_lists:
            values = payload.get(key)
            if isinstance(values, list) and values:
                values.pop()
                payload["omitted_counts"][key] = payload["omitted_counts"].get(key, 0) + 1
                payload["truncated"] = True
                changed = True
                break
        if changed:
            continue
        for candidate in payload.get("candidate_concepts") or []:
            score = candidate.get("local_candidate_score")
            score_reasons = score.get("reasons") if isinstance(score, dict) else None
            if isinstance(score_reasons, list) and score_reasons:
                score_reasons.pop()
                payload["omitted_counts"]["candidate_score_reasons"] = (
                    payload["omitted_counts"].get("candidate_score_reasons", 0) + 1
                )
                payload["truncated"] = True
                changed = True
                break
            for key in ("documentation", "positive_indicators", "exclusion_indicators", "aliases"):
                value = candidate.get(key)
                if isinstance(value, list) and value:
                    value.pop()
                    payload["truncated"] = True
                    changed = True
                    break
                if isinstance(value, str) and len(value) > 120:
                    candidate[key] = value[:120]
                    payload["truncated"] = True
                    changed = True
                    break
            if changed:
                break
        if changed:
            continue
        # Candidate identity, source identity, and source values are permanent.
        # A too-small configured boundary therefore fails closed.
        raise ValueError("Row mapping context cannot fit the configured character limit")


def build_section_aware_mapping_context(
    *,
    row: Mapping[str, Any],
    section: Mapping[str, Any],
    rows_in_section: Sequence[Mapping[str, Any]],
    candidate_set: SectionAwareCandidateSet,
    limits: MappingContextLimits = MappingContextLimits(),
    nearby_paragraphs: Sequence[str] = (),
) -> dict[str, Any]:
    source_row_id = str(row.get("source_row_id") or row.get("row_id") or "")
    ordered_rows = list(rows_in_section)
    index = next(
        (position for position, item in enumerate(ordered_rows) if str(item.get("source_row_id") or item.get("row_id")) == source_row_id),
        0,
    )
    sibling_pool = [
        item
        for position, item in enumerate(ordered_rows)
        if position != index
        and item.get("table_id") == row.get("table_id")
        and _label(item)
    ]
    sibling_pool.sort(
        key=lambda item: (
            abs(ordered_rows.index(item) - index),
            ordered_rows.index(item),
            str(item.get("source_row_id") or ""),
        )
    )
    siblings = [_label(item) for item in sibling_pool[: max(0, limits.max_siblings)]]

    by_id = {str(item.get("source_row_id") or item.get("row_id") or ""): item for item in ordered_rows}
    ancestors: list[str] = []
    parent_id = row.get("parent_row_id") or (row.get("provenance") or {}).get("parent_row_id")
    seen = set()
    while parent_id and len(ancestors) < max(0, limits.max_ancestors):
        key = str(parent_id)
        if key in seen or key not in by_id:
            break
        seen.add(key)
        parent = by_id[key]
        if _label(parent):
            ancestors.append(_label(parent))
        parent_id = parent.get("parent_row_id") or (parent.get("provenance") or {}).get("parent_row_id")

    children = [
        _label(item)
        for item in ordered_rows
        if str(item.get("parent_row_id") or (item.get("provenance") or {}).get("parent_row_id") or "") == source_row_id
        and _label(item)
    ][: max(0, limits.max_descendants)]
    candidate_limit = min(20, max(1, limits.max_candidate_cards))
    candidates = [_candidate_payload(candidate) for candidate in candidate_set.candidates[:candidate_limit]]
    paragraphs = [_text(value, 1000) for value in nearby_paragraphs if _text(value, 1000)]
    paragraphs = paragraphs[: max(0, limits.max_nearby_paragraphs)]
    raw_headers = _safe_list(row.get("table_headers") or (row.get("provenance") or {}).get("table_headers"))
    raw_columns = _safe_list(row.get("column_headers") or (row.get("provenance") or {}).get("column_headers"))

    payload = {
        "context_version": CONTEXT_VERSION,
        "source_row_id": source_row_id,
        "source_page": row.get("page_number"),
        "source_table_id": row.get("table_id"),
        "section_id": section.get("section_id"),
        "subsection_id": section.get("subsection_id"),
        "section_title": _text(section.get("section_title"), 500),
        "subsection_title": _text(section.get("subsection_title"), 500),
        "canonical_section_type": section.get("canonical_section_type"),
        "template_group_ids": list(candidate_set.template_group_ids),
        "row_label": _label(row),
        "normalized_row_label": _text(row.get("normalized_label"), 500),
        "parent_row_label": ancestors[0] if ancestors else None,
        "ancestor_labels": ancestors,
        "sibling_labels": siblings,
        "child_labels": children,
        "table_title": _text(row.get("table_title") or (row.get("provenance") or {}).get("table_title"), 500),
        "table_headers": [_text(value, 300) for value in raw_headers[:12] if _text(value, 300)],
        "column_headers": [_text(value, 300) for value in raw_columns[:12] if _text(value, 300)],
        "current_year_value": row.get("current_value", row.get("value")),
        "prior_year_value": row.get("prior_value", row.get("previous_value")),
        "current_year": row.get("current_year"),
        "prior_year": row.get("prior_year"),
        "currency": row.get("currency") or (row.get("provenance") or {}).get("currency"),
        "unit": row.get("unit") or (row.get("provenance") or {}).get("unit"),
        "sign": row.get("sign"),
        "indentation": row.get("indentation") or (row.get("provenance") or {}).get("indentation"),
        "total_or_subtotal": candidate_set.row_eligibility.outcome,
        "nearby_explanatory_text": paragraphs,
        "candidate_concepts": candidates,
        "truncated": False,
        "omitted_counts": {
            "sibling_labels": max(0, len(sibling_pool) - len(siblings)),
            "ancestor_labels": 0,
            "child_labels": max(0, sum(1 for item in ordered_rows if str(item.get("parent_row_id") or "") == source_row_id) - len(children)),
            "candidate_concepts": max(0, len(candidate_set.candidates) - len(candidates)),
            "candidate_score_reasons": 0,
            "nearby_explanatory_text": max(0, len(nearby_paragraphs) - len(paragraphs)),
        },
    }
    if any(payload["omitted_counts"].values()):
        payload["truncated"] = True
    _trim_to_character_limit(payload, max(500, int(limits.max_characters)))
    return payload
