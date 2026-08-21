"""Heading-anchor detection and printed/PDF page reconciliation for #19A."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from typing import Any, Iterable, Mapping

from schemas import DocumentPageMapping, HeadingAnchor, TocEntry
from services.document_heading_quality import (
    controlled_title_tokens,
    core_title_tokens,
    evaluate_heading_quality,
    meaningful_title_tokens,
)
from services.section_title_normalization import (
    SECTION_ALIASES,
    UNKNOWN_SECTION,
    normalize_section_title,
    normalize_title_text,
)


MIN_ANCHOR_SCORE = 0.68
MAX_HEADING_CANDIDATES = 25000
MAX_HEADING_COMPARISONS = 2_000_000
ANCHOR_AMBIGUITY_MARGIN = 0.12
MAX_RECORDED_ANCHOR_ALTERNATIVES = 5
MAX_RECORDED_REJECTED_CANDIDATES = 5
ROMAN_PAGE_LABEL_RE = re.compile(r"^[ivxlcdm]+$", re.I)
PAGE_LABEL_ONLY_RE = re.compile(
    r"^\s*(?:pages?(?:\s+no\.?)?\s*)?(?P<label>\d{1,4}|[ivxlcdm]{1,12})\s*$",
    re.I,
)
TIER_PRIORITY = {"A": 4, "B": 3, "C": 2, "D": 1, "rejected": 0}
CANONICAL_PREFIX_QUALIFIERS = frozenset(
    {"as", "at", "dated", "for", "in", "of", "pursuant", "to", "under"}
)


def _numbering_scheme(entry: TocEntry) -> str:
    label = str(entry.printed_page_start_label or "").strip()
    return "roman" if ROMAN_PAGE_LABEL_RE.fullmatch(label) else "arabic"


def _to_roman(value: int) -> str:
    if value <= 0 or value > 3999:
        return str(value)
    numerals = (
        (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
        (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
        (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    )
    remaining = value
    encoded: list[str] = []
    for amount, token in numerals:
        while remaining >= amount:
            encoded.append(token)
            remaining -= amount
    return "".join(encoded).lower()


def _printed_label(value: int, scheme: str) -> str:
    return _to_roman(value) if scheme == "roman" else str(value)


def _first_polygon_y(value: Any) -> float | None:
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, Mapping):
            try:
                return float(first.get("y"))
            except (TypeError, ValueError):
                return None
        if len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
            return float(value[1])
    return None


def _bounding_top(regions: Iterable[Mapping[str, Any]]) -> float | None:
    values = [
        _first_polygon_y(region.get("polygon"))
        for region in regions
        if isinstance(region, Mapping)
    ]
    values = [value for value in values if value is not None]
    return min(values) if values else None


def _heading_candidates(
    azure_result: Mapping[str, Any],
    *,
    toc_page_indexes: set[int],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    candidates_by_title_page: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    page_heights = {
        int(page.get("page_number") or 0): float(page.get("height") or 0)
        for page in azure_result.get("pages") or []
        if page.get("page_number")
    }
    pages_by_number = {
        int(page.get("page_number") or 0): page
        for page in azure_result.get("pages") or []
        if page.get("page_number")
    }
    line_groups: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for page_number, page in pages_by_number.items():
        line_groups[page_number].extend(page.get("lines") or [])
    for line in azure_result.get("lines") or []:
        page_number = int(line.get("page_number") or 0)
        if page_number and line not in line_groups[page_number]:
            line_groups[page_number].append(line)

    page_labels: dict[int, set[str]] = defaultdict(set)
    for page_number, lines in line_groups.items():
        height = page_heights.get(page_number)
        for line in lines:
            text = " ".join(str(line.get("content") or "").split())
            match = PAGE_LABEL_ONLY_RE.fullmatch(text)
            if not match:
                continue
            top = _first_polygon_y(line.get("polygon") or [])
            if (
                isinstance(top, (int, float))
                and isinstance(height, (int, float))
                and height > 0
                and top / height < 0.55
            ):
                continue
            page_labels[page_number].add(match.group("label").lower())

    table_tops: dict[int, list[float]] = defaultdict(list)
    for table in azure_result.get("tables") or []:
        regions = list(table.get("bounding_regions") or [])
        if not regions:
            regions = [
                region
                for cell in table.get("cells") or []
                for region in cell.get("bounding_regions") or []
                if isinstance(region, Mapping)
            ]
        for region in regions:
            if not isinstance(region, Mapping):
                continue
            page_number = int(region.get("page_number") or 0)
            top = _first_polygon_y(region.get("polygon"))
            if page_number > 0 and top is not None:
                table_tops[page_number].append(top)

    def context(page_number: int, top: float | None) -> dict[str, Any]:
        precedes_table = (
            isinstance(top, (int, float))
            and any(top <= table_top for table_top in table_tops.get(page_number, []))
        )
        return {
            "nearby_page_labels": sorted(page_labels.get(page_number, set())),
            "precedes_table_boundary": precedes_table,
        }

    def register(candidate: dict[str, Any]) -> None:
        key = (
            int(candidate["page_number"]),
            normalize_title_text(candidate["text"]),
        )
        top = candidate.get("top")
        height = candidate.get("page_height")
        for existing in candidates_by_title_page[key]:
            existing_top = existing.get("top")
            existing_height = existing.get("page_height")
            if not (
                isinstance(top, (int, float))
                and isinstance(existing_top, (int, float))
            ):
                continue
            reference_height = max(
                float(height or 0),
                float(existing_height or 0),
                1.0,
            )
            if abs(float(top) - float(existing_top)) <= reference_height * 0.015:
                # Same visible occurrence emitted through two Azure shapes.
                # Paragraphs are registered first and retain heading roles.
                return
        if len(candidates) >= MAX_HEADING_CANDIDATES:
            raise ValueError("Heading anchor candidate limit exceeded")
        candidates.append(candidate)
        candidates_by_title_page[key].append(candidate)

    for fallback_paragraph_index, paragraph in enumerate(
        azure_result.get("paragraphs") or []
    ):
        page_number = int(paragraph.get("page_number") or 0)
        if page_number <= 0 or page_number - 1 in toc_page_indexes:
            continue
        text = " ".join(str(paragraph.get("content") or "").split())
        if not text or len(text) > 220:
            continue
        paragraph_index = int(
            paragraph.get("paragraph_index")
            if paragraph.get("paragraph_index") is not None
            else fallback_paragraph_index
        )
        content_id = f"paragraph:{paragraph_index}"
        regions = list(paragraph.get("bounding_regions") or [])
        top = _bounding_top(regions)
        register(
            {
                "content_id": content_id,
                "text": text,
                "page_number": page_number,
                "role": str(paragraph.get("role") or ""),
                "bounding_evidence": regions,
                "top": top,
                "page_height": page_heights.get(page_number),
                "source_type": "paragraph",
                **context(page_number, top),
            }
        )

    for page_number, lines in line_groups.items():
        if page_number <= 0 or page_number - 1 in toc_page_indexes:
            continue
        for index, line in enumerate(lines):
            text = " ".join(str(line.get("content") or "").split())
            if not text or len(text) > 180:
                continue
            polygon = list(line.get("polygon") or [])
            top = _first_polygon_y(polygon)
            register(
                {
                    "content_id": f"page:{page_number}:line:{index}",
                    "text": text,
                    "page_number": page_number,
                    "role": "",
                    "bounding_evidence": [{"page_number": page_number, "polygon": polygon}],
                    "top": top,
                    "page_height": page_heights.get(page_number),
                    "source_type": "line",
                    **context(page_number, top),
                }
            )
    return candidates


@dataclass(frozen=True)
class HeadingMatchEvaluation:
    match_score: float
    match_method: str
    match_tier: str
    lexical_score: float
    token_coverage: float
    expected_token_coverage: float
    candidate_token_coverage: float
    expected_core_token_coverage: float
    candidate_core_token_coverage: float
    missing_expected_core_tokens: tuple[str, ...]
    length_ratio: float
    heading_quality_score: float
    trusted: bool
    rejection_reason: str | None


def evaluate_heading_anchor_match(
    entry: TocEntry,
    observed_heading: Any,
) -> HeadingMatchEvaluation:
    toc_normalized = entry.normalized_title
    heading_normalized = normalize_title_text(observed_heading)
    expected_quality = evaluate_heading_quality(entry.raw_title)
    heading_quality = evaluate_heading_quality(observed_heading)
    lexical_score = (
        SequenceMatcher(None, toc_normalized, heading_normalized).ratio()
        if toc_normalized and heading_normalized
        else 0.0
    )
    expected_tokens = set(meaningful_title_tokens(entry.raw_title))
    candidate_tokens = set(meaningful_title_tokens(observed_heading))
    overlap = expected_tokens & candidate_tokens
    expected_coverage = len(overlap) / max(1, len(expected_tokens))
    candidate_coverage = len(overlap) / max(1, len(candidate_tokens))
    token_coverage = min(expected_coverage, candidate_coverage)
    expected_core_tokens = set(core_title_tokens(entry.raw_title))
    candidate_core_tokens = set(core_title_tokens(observed_heading))
    core_overlap = expected_core_tokens & candidate_core_tokens
    expected_core_coverage = len(core_overlap) / max(1, len(expected_core_tokens))
    candidate_core_coverage = len(core_overlap) / max(1, len(candidate_core_tokens))
    missing_expected_core_tokens = tuple(sorted(expected_core_tokens - candidate_core_tokens))
    toc_length = len(toc_normalized.replace(" ", ""))
    heading_length = len(heading_normalized.replace(" ", ""))
    length_ratio = min(toc_length, heading_length) / max(1, toc_length, heading_length)

    def rejected(reason: str) -> HeadingMatchEvaluation:
        return HeadingMatchEvaluation(
            match_score=round(lexical_score, 4),
            match_method="rejected",
            match_tier="rejected",
            lexical_score=round(lexical_score, 4),
            token_coverage=round(token_coverage, 4),
            expected_token_coverage=round(expected_coverage, 4),
            candidate_token_coverage=round(candidate_coverage, 4),
            expected_core_token_coverage=round(expected_core_coverage, 4),
            candidate_core_token_coverage=round(candidate_core_coverage, 4),
            missing_expected_core_tokens=missing_expected_core_tokens,
            length_ratio=round(length_ratio, 4),
            heading_quality_score=heading_quality.score,
            trusted=False,
            rejection_reason=reason,
        )

    if not toc_normalized or not heading_normalized:
        return rejected("empty_expected_or_candidate_heading")
    if not expected_quality.accepted:
        return rejected(f"expected_{expected_quality.rejection_reason}")
    if not heading_quality.accepted:
        return rejected(f"candidate_{heading_quality.rejection_reason}")

    expected_controlled = controlled_title_tokens(entry.raw_title)
    candidate_controlled = controlled_title_tokens(observed_heading)
    canonical_sequences = [expected_controlled]
    if entry.canonical_section_hint != UNKNOWN_SECTION:
        canonical_sequences.extend(
            controlled_title_tokens(alias)
            for alias in SECTION_ALIASES.get(entry.canonical_section_hint, ())
        )
    canonical_sequences = list(dict.fromkeys(canonical_sequences))
    canonical_equivalent = any(
        candidate_controlled == sequence
        for sequence in canonical_sequences
        if sequence
    )
    canonical_prefix = any(
        len(candidate_controlled) > len(sequence)
        and candidate_controlled[: len(sequence)] == sequence
        and (
            candidate_controlled[len(sequence)] in CANONICAL_PREFIX_QUALIFIERS
            or candidate_controlled[len(sequence)].isdigit()
        )
        for sequence in canonical_sequences
        if sequence
    )
    required_core_coverage = 1.0 if len(expected_core_tokens) <= 3 else 0.80

    method = "rejected"
    tier = "rejected"
    score = lexical_score
    trusted = False
    rejection_reason = "insufficient_lexical_match"
    if toc_normalized == heading_normalized:
        score, method, tier, trusted = 0.90, "exact_normalized_title", "A", True
    else:
        heading_section = normalize_section_title(observed_heading)
        if (
            entry.canonical_section_hint != UNKNOWN_SECTION
            and heading_section.canonical_section_type == entry.canonical_section_hint
            and heading_section.match_method == "exact_alias"
        ):
            score, method, tier, trusted = 0.88, "canonical_alias_exact", "B", True
        elif canonical_equivalent and expected_core_coverage >= required_core_coverage:
            score, method, tier, trusted = 0.89, "canonical_title_equivalent", "B", True
        elif canonical_prefix and expected_core_coverage >= required_core_coverage:
            score = 0.87 + min(0.08, lexical_score * 0.08)
            method, tier, trusted = "canonical_title_prefix", "B", True
        elif (
            lexical_score >= 0.84
            and expected_coverage >= 0.60
            and candidate_coverage >= 0.60
            and length_ratio >= 0.60
        ):
            score = 0.78 + (lexical_score * 0.16) + (token_coverage * 0.04)
            method, tier, trusted = "strong_fuzzy_title", "C", True
        elif toc_normalized in heading_normalized or heading_normalized in toc_normalized:
            substantial = min(toc_length, heading_length) >= 8
            if (
                substantial
                and expected_core_coverage >= required_core_coverage
                and candidate_coverage >= 0.80
                and length_ratio >= 0.45
            ):
                score = 0.74 + (token_coverage * 0.12) + (length_ratio * 0.06)
                method, tier, trusted = "substantial_title_containment", "D", True
            else:
                rejection_reason = "insufficient_containment_coverage"
        elif lexical_score >= 0.68:
            rejection_reason = (
                "missing_expected_core_tokens"
                if expected_core_coverage < required_core_coverage
                else "fuzzy_match_below_trust_safeguards"
            )

    return HeadingMatchEvaluation(
        match_score=round(min(1.0, score), 4),
        match_method=method,
        match_tier=tier,
        lexical_score=round(lexical_score, 4),
        token_coverage=round(token_coverage, 4),
        expected_token_coverage=round(expected_coverage, 4),
        candidate_token_coverage=round(candidate_coverage, 4),
        expected_core_token_coverage=round(expected_core_coverage, 4),
        candidate_core_token_coverage=round(candidate_core_coverage, 4),
        missing_expected_core_tokens=missing_expected_core_tokens,
        length_ratio=round(length_ratio, 4),
        heading_quality_score=heading_quality.score,
        trusted=trusted,
        rejection_reason=None if trusted else rejection_reason,
    )


def _anchor_score(
    entry: TocEntry,
    candidate: Mapping[str, Any],
) -> tuple[HeadingMatchEvaluation, list[str]]:
    evaluation = evaluate_heading_anchor_match(entry, candidate.get("text"))
    score = evaluation.match_score
    signals: list[str] = [evaluation.match_method]
    if not evaluation.trusted:
        return evaluation, signals

    role = str(candidate.get("role") or "").lower()
    if role in {"title", "sectionheading", "section_heading", "heading"}:
        score += 0.07
        signals.append("azure_heading_role")
    text = str(candidate.get("text") or "")
    letters = [char for char in text if char.isalpha()]
    if letters and sum(char.isupper() for char in letters) / len(letters) >= 0.8:
        score += 0.03
        signals.append("uppercase_heading")
    top = candidate.get("top")
    height = candidate.get("page_height")
    if isinstance(top, (int, float)) and isinstance(height, (int, float)) and height > 0:
        if top / height <= 0.35:
            score += 0.05
            signals.append("top_of_page")
    expected_label = str(
        entry.printed_page_start_label
        or entry.printed_page_start
        or ""
    ).lower()
    if expected_label and expected_label in set(candidate.get("nearby_page_labels") or []):
        score += 0.03
        signals.append("matching_nearby_page_label")
    if candidate.get("precedes_table_boundary"):
        score += 0.02
        signals.append("precedes_table_boundary")
    return HeadingMatchEvaluation(
        match_score=round(min(1.0, score), 4),
        match_method=evaluation.match_method,
        match_tier=evaluation.match_tier,
        lexical_score=evaluation.lexical_score,
        token_coverage=evaluation.token_coverage,
        expected_token_coverage=evaluation.expected_token_coverage,
        candidate_token_coverage=evaluation.candidate_token_coverage,
        expected_core_token_coverage=evaluation.expected_core_token_coverage,
        candidate_core_token_coverage=evaluation.candidate_core_token_coverage,
        missing_expected_core_tokens=evaluation.missing_expected_core_tokens,
        length_ratio=evaluation.length_ratio,
        heading_quality_score=evaluation.heading_quality_score,
        trusted=True,
        rejection_reason=None,
    ), signals


def _preliminary_anchor_key(row) -> tuple[Any, ...]:
    evaluation, candidate, _signals = row
    return (
        -TIER_PRIORITY.get(evaluation.match_tier, 0),
        -evaluation.lexical_score,
        -evaluation.expected_core_token_coverage,
        -evaluation.heading_quality_score,
        -evaluation.match_score,
        int(candidate["page_number"]),
        str(candidate["content_id"]),
    )


def _provisional_numbering_offsets(
    entries: Iterable[TocEntry],
    trusted_by_entry: Mapping[str, list[tuple[HeadingMatchEvaluation, Mapping[str, Any], list[str]]]],
) -> dict[str, int]:
    support: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    counts: dict[str, Counter] = defaultdict(Counter)
    for entry in entries:
        high_trust = [
            row
            for row in trusted_by_entry.get(entry.entry_id, [])
            if row[0].match_tier in {"A", "B"}
        ]
        if not high_trust or entry.printed_page_start is None:
            continue
        evaluation, candidate, _signals = min(high_trust, key=_preliminary_anchor_key)
        scheme = _numbering_scheme(entry)
        offset = int(candidate["page_number"]) - 1 - entry.printed_page_start
        weight = {"A": 1.0, "B": 0.90}[evaluation.match_tier]
        weight *= 0.65 + (0.35 * evaluation.lexical_score)
        support[scheme][offset] += weight
        counts[scheme][offset] += 1

    provisional: dict[str, int] = {}
    for scheme, offsets in support.items():
        if not offsets:
            continue
        dominant = max(
            offsets,
            key=lambda offset: (offsets[offset], counts[scheme][offset], -abs(offset)),
        )
        total = sum(offsets.values())
        if counts[scheme][dominant] >= 2 and offsets[dominant] / max(total, 0.000001) >= 0.72:
            provisional[scheme] = dominant
    return provisional


def _final_anchor_key(row, entry: TocEntry, provisional_offset: int | None) -> tuple[Any, ...]:
    evaluation, candidate, _signals = row
    actual_offset = (
        int(candidate["page_number"]) - 1 - entry.printed_page_start
        if entry.printed_page_start is not None
        else None
    )
    offset_distance = (
        abs(actual_offset - provisional_offset)
        if actual_offset is not None and provisional_offset is not None
        else 0
    )
    return (
        -TIER_PRIORITY.get(evaluation.match_tier, 0),
        -evaluation.lexical_score,
        -evaluation.expected_core_token_coverage,
        -evaluation.heading_quality_score,
        offset_distance,
        -evaluation.match_score,
        int(candidate["page_number"]),
        str(candidate["content_id"]),
    )


def detect_heading_anchors(
    entries: Iterable[TocEntry],
    azure_result: Mapping[str, Any],
    *,
    toc_page_indexes: Iterable[int],
) -> list[HeadingAnchor]:
    candidates = _heading_candidates(
        azure_result,
        toc_page_indexes=set(int(value) for value in toc_page_indexes),
    )
    entry_rows = list(entries)
    if len(entry_rows) * len(candidates) > MAX_HEADING_COMPARISONS:
        raise ValueError("Heading anchor comparison limit exceeded")

    trusted_by_entry = {}
    rejected_by_entry = {}
    for entry in entry_rows:
        trusted_rows = []
        rejected_rows = []
        for candidate in candidates:
            evaluation, signals = _anchor_score(entry, candidate)
            row = (evaluation, candidate, signals)
            if evaluation.trusted and evaluation.match_score >= MIN_ANCHOR_SCORE:
                trusted_rows.append(row)
            else:
                rejected_rows.append(row)
        trusted_by_entry[entry.entry_id] = trusted_rows
        rejected_rows.sort(
            key=lambda row: (
                -row[0].lexical_score,
                -row[0].expected_core_token_coverage,
                int(row[1]["page_number"]),
                str(row[1]["content_id"]),
            )
        )
        rejected_by_entry[entry.entry_id] = rejected_rows

    provisional_offsets = _provisional_numbering_offsets(
        entry_rows,
        trusted_by_entry,
    )
    anchors: list[HeadingAnchor] = []
    used_content_ids: set[str] = set()
    used_rejected_content_ids: set[str] = set()
    for entry in entry_rows:
        scheme = _numbering_scheme(entry)
        provisional_offset = provisional_offsets.get(scheme)
        scored = [
            row
            for row in trusted_by_entry.get(entry.entry_id, [])
            if str(row[1]["content_id"]) not in used_content_ids
        ]
        rejected = rejected_by_entry.get(entry.entry_id, [])
        scored.sort(key=lambda row: _final_anchor_key(row, entry, provisional_offset))
        if not scored:
            if not rejected:
                continue
            evaluation, candidate, scoring_signals = next(
                (
                    row
                    for row in rejected
                    if str(row[1]["content_id"]) not in used_rejected_content_ids
                ),
                rejected[0],
            )
            used_rejected_content_ids.add(str(candidate["content_id"]))
            page_number = int(candidate["page_number"])
            anchors.append(
                HeadingAnchor(
                    anchor_id=f"heading-anchor-{len(anchors) + 1}",
                    toc_entry_id=entry.entry_id,
                    source_content_id=str(candidate["content_id"]),
                    toc_title=entry.raw_title,
                    matched_heading=str(candidate["text"]),
                    pdf_page_index=page_number - 1,
                    azure_page_number=page_number,
                    match_score=evaluation.match_score,
                    match_method=evaluation.match_method,
                    match_tier=evaluation.match_tier,
                    lexical_score=evaluation.lexical_score,
                    token_coverage=evaluation.token_coverage,
                    expected_token_coverage=evaluation.expected_token_coverage,
                    candidate_token_coverage=evaluation.candidate_token_coverage,
                    expected_core_token_coverage=evaluation.expected_core_token_coverage,
                    candidate_core_token_coverage=evaluation.candidate_core_token_coverage,
                    missing_expected_core_tokens=list(evaluation.missing_expected_core_tokens),
                    length_ratio=evaluation.length_ratio,
                    heading_quality_score=evaluation.heading_quality_score,
                    trusted=False,
                    rejection_reason=evaluation.rejection_reason,
                    confidence=evaluation.match_score,
                    scoring_signals=scoring_signals,
                    text_evidence=str(candidate["text"]),
                    bounding_evidence=list(candidate.get("bounding_evidence") or []),
                    warnings=list(
                        dict.fromkeys(
                            [
                                "heading_anchor_rejected",
                                str(evaluation.rejection_reason or "untrusted_heading_anchor"),
                            ]
                        )
                    ),
                )
            )
            continue

        evaluation, candidate, scoring_signals = scored[0]
        score = evaluation.match_score
        actual_offset = (
            int(candidate["page_number"]) - 1 - entry.printed_page_start
            if entry.printed_page_start is not None
            else None
        )
        if provisional_offset is not None and actual_offset is not None:
            if actual_offset == provisional_offset:
                scoring_signals = [*scoring_signals, "provisional_offset_match"]
            else:
                scoring_signals = [
                    *scoring_signals,
                    f"provisional_offset_distance:{abs(actual_offset - provisional_offset)}",
                ]
        same_tier_near_ties = [
            row
            for row in scored[1:]
            if row[0].match_tier == evaluation.match_tier
            and score - row[0].match_score <= ANCHOR_AMBIGUITY_MARGIN
        ][:MAX_RECORDED_ANCHOR_ALTERNATIVES]
        recorded_alternatives = scored[1 : 1 + MAX_RECORDED_ANCHOR_ALTERNATIVES]
        warnings: list[str] = []
        if any(
            int(row[1]["page_number"]) != int(candidate["page_number"])
            for row in same_tier_near_ties
        ):
            warnings.append("heading_anchor_near_tie")
        if any(
            int(row[1]["page_number"]) == int(candidate["page_number"])
            for row in same_tier_near_ties
        ):
            warnings.append("heading_anchor_same_page_near_tie")
        used_content_ids.add(str(candidate["content_id"]))
        page_number = int(candidate["page_number"])
        anchors.append(
            HeadingAnchor(
                anchor_id=f"heading-anchor-{len(anchors) + 1}",
                toc_entry_id=entry.entry_id,
                source_content_id=str(candidate["content_id"]),
                toc_title=entry.raw_title,
                matched_heading=str(candidate["text"]),
                pdf_page_index=page_number - 1,
                azure_page_number=page_number,
                match_score=round(score, 4),
                match_method=evaluation.match_method,
                match_tier=evaluation.match_tier,
                lexical_score=evaluation.lexical_score,
                token_coverage=evaluation.token_coverage,
                expected_token_coverage=evaluation.expected_token_coverage,
                candidate_token_coverage=evaluation.candidate_token_coverage,
                expected_core_token_coverage=evaluation.expected_core_token_coverage,
                candidate_core_token_coverage=evaluation.candidate_core_token_coverage,
                missing_expected_core_tokens=list(evaluation.missing_expected_core_tokens),
                length_ratio=evaluation.length_ratio,
                heading_quality_score=evaluation.heading_quality_score,
                trusted=True,
                rejection_reason=None,
                confidence=round(score, 4),
                scoring_signals=scoring_signals,
                text_evidence=str(candidate["text"]),
                bounding_evidence=list(candidate.get("bounding_evidence") or []),
                alternative_candidates=[
                    {
                        "source_content_id": str(alternative["content_id"]),
                        "matched_heading": str(alternative["text"]),
                        "pdf_page_index": int(alternative["page_number"]) - 1,
                        "azure_page_number": int(alternative["page_number"]),
                        "match_score": round(float(alternative_evaluation.match_score), 4),
                        "match_method": alternative_evaluation.match_method,
                        "match_tier": alternative_evaluation.match_tier,
                        "lexical_score": alternative_evaluation.lexical_score,
                        "expected_core_token_coverage": alternative_evaluation.expected_core_token_coverage,
                        "trusted": True,
                        "scoring_signals": alternative_signals,
                        "bounding_evidence": list(alternative.get("bounding_evidence") or []),
                    }
                    for alternative_evaluation, alternative, alternative_signals in recorded_alternatives
                ],
                rejected_candidates=[
                    {
                        "source_content_id": str(rejected_candidate["content_id"]),
                        "matched_heading": str(rejected_candidate["text"]),
                        "pdf_page_index": int(rejected_candidate["page_number"]) - 1,
                        "azure_page_number": int(rejected_candidate["page_number"]),
                        "lexical_score": rejected_evaluation.lexical_score,
                        "token_coverage": rejected_evaluation.token_coverage,
                        "expected_core_token_coverage": rejected_evaluation.expected_core_token_coverage,
                        "missing_expected_core_tokens": list(rejected_evaluation.missing_expected_core_tokens),
                        "length_ratio": rejected_evaluation.length_ratio,
                        "heading_quality_score": rejected_evaluation.heading_quality_score,
                        "trusted": False,
                        "rejection_reason": rejected_evaluation.rejection_reason,
                    }
                    for rejected_evaluation, rejected_candidate, _signals in rejected[:MAX_RECORDED_REJECTED_CANDIDATES]
                ],
                warnings=warnings,
            )
        )
    return anchors


@dataclass(frozen=True)
class PageAlignmentResult:
    page_mappings: tuple[DocumentPageMapping, ...]
    confidence: float
    offset_candidates: dict[int, int]
    anchor_count: int
    trusted_anchor_count: int
    rejected_anchor_count: int
    inconsistent_anchor_count: int
    mapping_method: str
    requires_human_review: bool
    warnings: tuple[str, ...]
    regimes: tuple[dict[str, Any], ...]
    weighted_offset_support: dict[int, float]
    dominant_offsets: tuple[int, ...]
    competing_high_quality_offset_count: int

    @property
    def final_printed_page(self) -> int | None:
        mapped = [
            item
            for item in self.page_mappings
            if item.printed_page_number is not None
        ]
        if not mapped:
            return None
        return max(mapped, key=lambda item: item.pdf_page_index).printed_page_number

    @property
    def final_numbering_scheme(self) -> str | None:
        mapped = [
            item
            for item in self.page_mappings
            if item.printed_page_number is not None
        ]
        if not mapped:
            return None
        return max(mapped, key=lambda item: item.pdf_page_index).numbering_scheme

    def to_dict(self) -> dict[str, Any]:
        return {
            "confidence": self.confidence,
            "offset_candidates": {str(key): value for key, value in sorted(self.offset_candidates.items())},
            "anchor_count": self.anchor_count,
            "trusted_anchor_count": self.trusted_anchor_count,
            "rejected_anchor_count": self.rejected_anchor_count,
            "inconsistent_anchor_count": self.inconsistent_anchor_count,
            "mapping_method": self.mapping_method,
            "requires_human_review": self.requires_human_review,
            "warnings": list(self.warnings),
            "regimes": list(self.regimes),
            "weighted_offset_support": {
                str(key): value
                for key, value in sorted(self.weighted_offset_support.items())
            },
            "dominant_offsets": list(self.dominant_offsets),
            "competing_high_quality_offset_count": self.competing_high_quality_offset_count,
        }


def _unmapped_pages(
    azure_page_numbers: Iterable[int],
    *,
    warning: str,
) -> tuple[DocumentPageMapping, ...]:
    return tuple(
        DocumentPageMapping(
            pdf_page_index=page_number - 1,
            azure_page_number=page_number,
            mapping_method="unmapped",
            confidence=0.0,
            requires_human_review=True,
            warnings=[warning],
        )
        for page_number in sorted(set(int(value) for value in azure_page_numbers if int(value) > 0))
    )


def _anchor_consensus_weight(anchor: HeadingAnchor) -> float:
    tier_weight = {
        "A": 1.0,
        "B": 0.90,
        "C": 0.72,
        "D": 0.55,
        "legacy": 0.70,
    }.get(anchor.match_tier, 0.45)
    confidence = float(anchor.confidence if anchor.confidence is not None else anchor.match_score)
    return round(tier_weight * (0.60 + (0.40 * confidence)), 6)


def _weighted_average_score(items: Iterable[Mapping[str, Any]]) -> float:
    rows = list(items)
    total_weight = sum(float(item["weight"]) for item in rows)
    if total_weight <= 0:
        return 0.0
    return sum(
        float(item["anchor"].match_score) * float(item["weight"])
        for item in rows
    ) / total_weight


def align_document_pages(
    entries: Iterable[TocEntry],
    anchors: Iterable[HeadingAnchor],
    *,
    azure_page_numbers: Iterable[int],
) -> PageAlignmentResult:
    entries_by_id = {entry.entry_id: entry for entry in entries}
    anchor_candidates = []
    for anchor in anchors:
        entry = entries_by_id.get(anchor.toc_entry_id)
        if entry and entry.printed_page_start is not None:
            anchor_candidates.append(
                {
                    "anchor": anchor,
                    "entry": entry,
                    "offset": anchor.pdf_page_index - entry.printed_page_start,
                    "scheme": _numbering_scheme(entry),
                    "weight": _anchor_consensus_weight(anchor),
                }
            )
    rejected = [item for item in anchor_candidates if not item["anchor"].trusted]
    trusted = [item for item in anchor_candidates if item["anchor"].trusted]
    ambiguous_items = [
        item
        for item in trusted
        if "heading_anchor_near_tie" in item["anchor"].warnings
    ]
    ambiguous_anchor_count = len(ambiguous_items)
    usable = [
        item
        for item in trusted
        if "heading_anchor_near_tie" not in item["anchor"].warnings
    ]
    base_warnings: list[str] = []
    if rejected:
        base_warnings.append("heading_anchor_rejections_present")
    if not usable:
        warning = (
            "heading_anchor_ambiguous"
            if trusted
            else "heading_anchor_missing"
        )
        return PageAlignmentResult(
            page_mappings=_unmapped_pages(azure_page_numbers, warning=warning),
            confidence=0.0,
            offset_candidates={},
            anchor_count=len(anchor_candidates),
            trusted_anchor_count=len(trusted),
            rejected_anchor_count=len(rejected),
            inconsistent_anchor_count=ambiguous_anchor_count,
            mapping_method="unmapped",
            requires_human_review=True,
            warnings=tuple(dict.fromkeys([*base_warnings, warning, "page_alignment_ambiguous"])),
            regimes=(),
            weighted_offset_support={},
            dominant_offsets=(),
            competing_high_quality_offset_count=0,
        )

    counts = Counter(int(item["offset"]) for item in usable)
    weighted_offsets: dict[int, float] = defaultdict(float)
    for item in usable:
        weighted_offsets[int(item["offset"])] += float(item["weight"])
    weighted_offsets = {
        key: round(value, 4) for key, value in weighted_offsets.items()
    }
    regime_counts = Counter(
        (int(item["offset"]), str(item["scheme"]))
        for item in usable
    )
    average_score = _weighted_average_score(usable)
    page_numbers = sorted(set(int(value) for value in azure_page_numbers if int(value) > 0))
    warnings: list[str] = list(base_warnings)
    if ambiguous_anchor_count:
        warnings.append("heading_anchor_near_tie")
    regimes: list[dict[str, Any]] = []

    schemes = {str(item["scheme"]) for item in usable}
    dominant_offset = max(
        weighted_offsets,
        key=lambda value: (weighted_offsets[value], counts[value], -abs(value)),
    )
    dominant_items = [item for item in usable if int(item["offset"]) == dominant_offset]
    competing_items = [item for item in usable if int(item["offset"]) != dominant_offset]
    ambiguous_off_regime_items = [
        item
        for item in ambiguous_items
        if int(item["offset"]) != dominant_offset
    ]
    if ambiguous_off_regime_items:
        warnings.append("page_alignment_ambiguous")
    elif ambiguous_items:
        warnings.append("heading_anchor_near_tie_resolved_by_dominant_regime")
    total_weight = sum(weighted_offsets.values())
    dominant_weight_ratio = weighted_offsets[dominant_offset] / max(total_weight, 0.000001)
    competing_high_quality_offsets = {
        int(item["offset"])
        for item in competing_items
        if item["anchor"].match_tier in {"A", "B"}
        and sum(
            1
            for peer in competing_items
            if int(peer["offset"]) == int(item["offset"])
            and peer["anchor"].match_tier in {"A", "B"}
        )
        >= 2
    }
    dominant_consensus = (
        len(schemes) == 1
        and len(dominant_items) >= 2
        and dominant_weight_ratio >= 0.72
        and not competing_high_quality_offsets
    )

    if len(regime_counts) == 1 or dominant_consensus:
        offset = dominant_offset
        scheme = str(dominant_items[0]["scheme"])
        selected_score = _weighted_average_score(dominant_items)
        count_factor = (
            0.72
            if len(dominant_items) == 1
            else min(1.0, 0.80 + (0.05 * len(dominant_items)))
        )
        confidence = selected_score * count_factor * dominant_weight_ratio
        if len(dominant_items) == 1:
            warnings.append("single_heading_anchor")
        if competing_items:
            warnings.append("low_weight_anchor_offsets_excluded")
        requires_review = (
            len(dominant_items) == 1
            or bool(ambiguous_off_regime_items)
            or bool(competing_high_quality_offsets)
            or confidence < 0.80
        )
        mappings = []
        for page_number in page_numbers:
            pdf_index = page_number - 1
            printed = pdf_index - offset
            mapped = printed >= 1
            mappings.append(
                DocumentPageMapping(
                    pdf_page_index=pdf_index,
                    azure_page_number=page_number,
                    printed_page_number=printed if mapped else None,
                    printed_page_label=_printed_label(printed, scheme) if mapped else None,
                    numbering_scheme=scheme if mapped else None,
                    offset=offset if mapped else None,
                    mapping_method="weighted_heading_anchor_consensus" if mapped else "unmapped_prefatory_page",
                    confidence=round(confidence if mapped else 0.0, 4),
                    anchor_title=dominant_items[0]["entry"].raw_title if mapped else None,
                    requires_human_review=requires_review,
                    warnings=list(warnings) if mapped else ["printed_page_label_unavailable"],
                )
            )
        regimes.append(
            {
                "offset": offset,
                "numbering_scheme": scheme,
                "supporting_anchor_count": len(dominant_items),
                "weighted_support": weighted_offsets[offset],
                "weighted_support_ratio": round(dominant_weight_ratio, 4),
                "pdf_page_start": min(item["anchor"].pdf_page_index for item in dominant_items),
                "pdf_page_end": max(item["anchor"].pdf_page_index for item in dominant_items),
            }
        )
        return PageAlignmentResult(
            page_mappings=tuple(mappings),
            confidence=round(max(0.0, min(1.0, confidence)), 4),
            offset_candidates=dict(counts),
            anchor_count=len(anchor_candidates),
            trusted_anchor_count=len(trusted),
            rejected_anchor_count=len(rejected),
            inconsistent_anchor_count=(
                len(ambiguous_off_regime_items) + len(competing_items)
            ),
            mapping_method="weighted_heading_anchor_consensus",
            requires_human_review=requires_review,
            warnings=tuple(dict.fromkeys(warnings)),
            regimes=tuple(regimes),
            weighted_offset_support=weighted_offsets,
            dominant_offsets=(offset,),
            competing_high_quality_offset_count=len(competing_high_quality_offsets),
        )

    sorted_usable = sorted(
        usable,
        key=lambda item: (
            item["anchor"].pdf_page_index,
            item["entry"].printed_page_start or 0,
        ),
    )
    regime_sequence = [
        (int(item["offset"]), str(item["scheme"]))
        for item in sorted_usable
    ]
    compressed_regimes = [
        regime
        for index, regime in enumerate(regime_sequence)
        if index == 0 or regime != regime_sequence[index - 1]
    ]
    contiguous = len(compressed_regimes) == len(set(compressed_regimes))
    piecewise_supported = contiguous and all(
        count >= 2 for count in regime_counts.values()
    )

    if piecewise_supported:
        piecewise_warnings = list(
            dict.fromkeys([*warnings, "multiple_page_numbering_regimes"])
        )
        grouped: list[list[dict[str, Any]]] = []
        for item in sorted_usable:
            item_regime = (item["offset"], item["scheme"])
            existing_regime = (
                (grouped[-1][0]["offset"], grouped[-1][0]["scheme"])
                if grouped
                else None
            )
            if not grouped or existing_regime != item_regime:
                grouped.append([item])
            else:
                grouped[-1].append(item)
        boundaries = []
        for index in range(len(grouped) - 1):
            left = max(item["anchor"].pdf_page_index for item in grouped[index])
            right = min(item["anchor"].pdf_page_index for item in grouped[index + 1])
            boundaries.append((left + right) // 2)

        mappings = []
        for page_number in page_numbers:
            pdf_index = page_number - 1
            group_index = 0
            while group_index < len(boundaries) and pdf_index > boundaries[group_index]:
                group_index += 1
            group = grouped[group_index]
            offset = int(group[0]["offset"])
            scheme = str(group[0]["scheme"])
            printed = pdf_index - offset
            mapped = printed >= 1
            confidence = average_score * 0.82
            mappings.append(
                DocumentPageMapping(
                    pdf_page_index=pdf_index,
                    azure_page_number=page_number,
                    printed_page_number=printed if mapped else None,
                    printed_page_label=_printed_label(printed, scheme) if mapped else None,
                    numbering_scheme=scheme if mapped else None,
                    offset=offset if mapped else None,
                    mapping_method="heading_anchor_piecewise" if mapped else "unmapped_prefatory_page",
                    confidence=round(confidence if mapped else 0.0, 4),
                    anchor_title=group[0]["entry"].raw_title if mapped else None,
                    requires_human_review=True,
                    warnings=piecewise_warnings if mapped else ["printed_page_label_unavailable"],
                )
            )
        for group in grouped:
            regimes.append(
                {
                    "offset": int(group[0]["offset"]),
                    "numbering_scheme": str(group[0]["scheme"]),
                    "supporting_anchor_count": len(group),
                    "weighted_support": round(
                        sum(float(item["weight"]) for item in group),
                        4,
                    ),
                    "pdf_page_start": min(item["anchor"].pdf_page_index for item in group),
                    "pdf_page_end": max(item["anchor"].pdf_page_index for item in group),
                }
            )
        return PageAlignmentResult(
            page_mappings=tuple(mappings),
            confidence=round(average_score * 0.82, 4),
            offset_candidates=dict(counts),
            anchor_count=len(anchor_candidates),
            trusted_anchor_count=len(trusted),
            rejected_anchor_count=len(rejected),
            inconsistent_anchor_count=ambiguous_anchor_count,
            mapping_method="heading_anchor_piecewise",
            requires_human_review=True,
            warnings=tuple(piecewise_warnings),
            regimes=tuple(regimes),
            weighted_offset_support=weighted_offsets,
            dominant_offsets=tuple(dict.fromkeys(int(group[0]["offset"]) for group in grouped)),
            competing_high_quality_offset_count=len(competing_high_quality_offsets),
        )

    warnings.extend(["page_alignment_ambiguous", "inconsistent_heading_anchors"])
    warnings = list(dict.fromkeys(warnings))
    anchors_by_pdf: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in usable:
        anchors_by_pdf[item["anchor"].pdf_page_index].append(item)
    mappings = []
    for page_number in page_numbers:
        pdf_index = page_number - 1
        exact = anchors_by_pdf.get(pdf_index, [])
        if len(exact) == 1:
            item = exact[0]
            printed = item["entry"].printed_page_start
            scheme = str(item["scheme"])
            mappings.append(
                DocumentPageMapping(
                    pdf_page_index=pdf_index,
                    azure_page_number=page_number,
                    printed_page_number=printed,
                    printed_page_label=_printed_label(printed, scheme),
                    numbering_scheme=scheme,
                    offset=int(item["offset"]),
                    mapping_method="exact_heading_anchor_only",
                    confidence=round(float(item["anchor"].match_score) * 0.6, 4),
                    anchor_title=item["entry"].raw_title,
                    requires_human_review=True,
                    warnings=list(warnings),
                )
            )
        else:
            mappings.append(
                DocumentPageMapping(
                    pdf_page_index=pdf_index,
                    azure_page_number=page_number,
                    mapping_method="unmapped_ambiguous_alignment",
                    confidence=0.0,
                    requires_human_review=True,
                    warnings=list(warnings),
                )
            )
    return PageAlignmentResult(
        page_mappings=tuple(mappings),
        confidence=round(average_score * 0.45, 4),
        offset_candidates=dict(counts),
        anchor_count=len(anchor_candidates),
        trusted_anchor_count=len(trusted),
        rejected_anchor_count=len(rejected),
        inconsistent_anchor_count=len(usable) + ambiguous_anchor_count,
        mapping_method="exact_heading_anchor_only",
        requires_human_review=True,
        warnings=tuple(warnings),
        regimes=(),
        weighted_offset_support=weighted_offsets,
        dominant_offsets=(dominant_offset,),
        competing_high_quality_offset_count=len(competing_high_quality_offsets),
    )
