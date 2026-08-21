"""Deterministic TOC/INDEX page detection for Azure DI layout output."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata
from typing import Any, Iterable, Mapping

from services.section_title_normalization import is_known_section_title


TOC_HEADING_RE = re.compile(r"^\s*(?:table\s+of\s+contents|contents|index)\s*$", re.I)
PAGE_COLUMN_RE = re.compile(r"\bpages?(?:\s+no\.?)?\b", re.I)
PAGE_REFERENCE_RE = re.compile(
    r"(?:^|\s+|\.{2,})(?:pages?(?:\s+no\.?)?\s*)?(?:\d{1,4}|[ivxlcdm]{1,12})"
    r"(?:\s*[-\u2010-\u2015\u2212]\s*(?:\d{1,4}|[ivxlcdm]{1,12}))?\s*$",
    re.I,
)
PAGE_REFERENCE_START_RE = re.compile(
    r"(?:^|\s+|\.{2,})(?:pages?(?:\s+no\.?)?\s*)?(?P<start>\d{1,4}|[ivxlcdm]{1,12})"
    r"(?:\s*[-\u2010-\u2015\u2212]\s*(?:\d{1,4}|[ivxlcdm]{1,12}))?\s*$",
    re.I,
)
MAX_TOC_DETECTION_PAGES = 1000
MAX_TOC_DETECTION_LINES = 50000
MAX_TOC_CONTINUATION_DISTANCE = 3


@dataclass(frozen=True)
class TocPageDetection:
    pdf_page_index: int
    azure_page_number: int
    confidence: float
    matched_signals: tuple[str, ...]
    reasons: tuple[str, ...]
    entry_pattern_count: int
    known_section_count: int
    nonempty_line_count: int
    page_reference_starts: tuple[int, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "pdf_page_index": self.pdf_page_index,
            "azure_page_number": self.azure_page_number,
            "confidence": self.confidence,
            "matched_signals": list(self.matched_signals),
            "reasons": list(self.reasons),
            "entry_pattern_count": self.entry_pattern_count,
            "known_section_count": self.known_section_count,
            "nonempty_line_count": self.nonempty_line_count,
            "page_reference_starts": list(self.page_reference_starts),
        }


@dataclass(frozen=True)
class TocDetectionResult:
    detected: bool
    candidate_page_indexes: tuple[int, ...]
    confidence: float
    matched_signals: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    page_evidence: tuple[TocPageDetection, ...] = field(default_factory=tuple)
    block_start_pdf_page_index: int | None = None
    block_end_pdf_page_index: int | None = None
    termination_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "detected": self.detected,
            "candidate_page_indexes": list(self.candidate_page_indexes),
            "confidence": self.confidence,
            "matched_signals": list(self.matched_signals),
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
            "page_evidence": [item.to_dict() for item in self.page_evidence],
            "block_start_pdf_page_index": self.block_start_pdf_page_index,
            "block_end_pdf_page_index": self.block_end_pdf_page_index,
            "termination_reason": self.termination_reason,
        }


def _clean_line(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"(?<=[A-Za-z])0|0(?=[A-Za-z])", "O", text)
    return " ".join(text.split())


def _looks_like_entry(line: str) -> bool:
    if not PAGE_REFERENCE_RE.search(line):
        return False
    prefix = PAGE_REFERENCE_RE.sub("", line).strip(" .:\t")
    return len(prefix) >= 3 and bool(re.search(r"[A-Za-z]", prefix))


def _page_reference_start(line: str) -> int | None:
    match = PAGE_REFERENCE_START_RE.search(line)
    if not match:
        return None
    token = match.group("start")
    if token.isdigit():
        value = int(token)
        return value if value > 0 else None
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    result = 0
    previous = 0
    for character in reversed(token.upper()):
        current = values[character]
        if current < previous:
            result -= current
        else:
            result += current
            previous = current
    return result if result > 0 else None


def _page_detection(page: Mapping[str, Any]) -> TocPageDetection:
    lines = [
        _clean_line(item.get("text") if isinstance(item, Mapping) else item)
        for item in page.get("lines") or []
    ]
    lines = [line for line in lines if line]
    heading_count = sum(1 for line in lines if TOC_HEADING_RE.fullmatch(line))
    entry_lines = [line for line in lines if _looks_like_entry(line)]
    page_reference_starts = tuple(
        value
        for value in (
            _page_reference_start(line)
            for line in entry_lines
        )
        if value is not None
    )
    page_column_count = sum(1 for line in lines if PAGE_COLUMN_RE.search(line))
    known_section_count = sum(1 for line in entry_lines if is_known_section_title(PAGE_REFERENCE_RE.sub("", line)))
    short_line_count = sum(1 for line in lines if len(line) <= 140)
    density = len(entry_lines) / max(1, len(lines))
    short_density = short_line_count / max(1, len(lines))

    score = 0.0
    signals: list[str] = []
    reasons: list[str] = []
    if heading_count:
        score += 0.42
        signals.append("toc_heading")
        reasons.append("Page contains an INDEX/CONTENTS heading.")
    if len(entry_lines) >= 5:
        score += 0.38
        signals.append("many_title_page_rows")
        reasons.append("At least five title/page-reference rows were detected.")
    elif len(entry_lines) >= 3:
        score += 0.30
        signals.append("multiple_title_page_rows")
        reasons.append("At least three title/page-reference rows were detected.")
    elif len(entry_lines) >= 1:
        score += 0.10
        signals.append("title_page_row")
    if page_column_count:
        score += 0.08
        signals.append("page_column_heading")
    if known_section_count >= 2:
        score += 0.16
        signals.append("known_financial_sections")
        reasons.append("Multiple known financial-report section titles were detected.")
    elif known_section_count == 1:
        score += 0.06
        signals.append("known_financial_section")
    if density >= 0.45 and short_density >= 0.70:
        score += 0.12
        signals.append("high_short_row_density")
    qualifies = (
        (heading_count > 0 and (len(entry_lines) >= 2 or known_section_count >= 1))
        or (
            page_column_count > 0
            and len(entry_lines) >= 3
            and known_section_count >= 1
        )
        or (
            len(entry_lines) >= 4
            and known_section_count >= 2
            and density >= 0.45
        )
    )
    if not qualifies:
        score = min(score, 0.49)
    score = round(min(1.0, score), 4)

    return TocPageDetection(
        pdf_page_index=int(page["pdf_page_index"]),
        azure_page_number=int(page["azure_page_number"]),
        confidence=score,
        matched_signals=tuple(signals),
        reasons=tuple(reasons),
        entry_pattern_count=len(entry_lines),
        known_section_count=known_section_count,
        nonempty_line_count=len(lines),
        page_reference_starts=page_reference_starts,
    )


def _plausibly_continues(
    seed: TocPageDetection,
    candidate: TocPageDetection,
    *,
    direction: int,
) -> bool:
    seed_values = list(seed.page_reference_starts)
    candidate_values = list(candidate.page_reference_starts)
    if len(seed_values) < 2 or len(candidate_values) < 3:
        return False
    if any(
        later < earlier or later - earlier > 50
        for earlier, later in zip(candidate_values, candidate_values[1:])
    ):
        return False
    if direction > 0:
        return (
            candidate_values[0] >= seed_values[-1]
            and candidate_values[0] - seed_values[-1] <= 50
        )
    return (
        candidate_values[-1] <= seed_values[0]
        and seed_values[0] - candidate_values[-1] <= 50
    )


def detect_toc_pages(pages: Iterable[Mapping[str, Any]]) -> TocDetectionResult:
    page_rows = list(pages)
    if len(page_rows) > MAX_TOC_DETECTION_PAGES:
        raise ValueError("TOC detection page limit exceeded")
    if sum(len(page.get("lines") or []) for page in page_rows) > MAX_TOC_DETECTION_LINES:
        raise ValueError("TOC detection line limit exceeded")
    evidence = sorted((_page_detection(page) for page in page_rows), key=lambda item: item.pdf_page_index)
    qualified = [item for item in evidence if item.confidence >= 0.55]
    heading_seeds = [
        item for item in qualified if "toc_heading" in item.matched_signals
    ]
    seed_candidates = heading_seeds or qualified
    primary_seed = (
        max(
            seed_candidates,
            key=lambda item: (
                item.confidence,
                item.known_section_count,
                item.entry_pattern_count,
                -item.pdf_page_index,
            ),
        )
        if seed_candidates
        else None
    )
    selected = {primary_seed.pdf_page_index} if primary_seed else set()
    continuation_seed_pages = set(selected)

    # A continuation page may omit the repeated heading. Expansion is bounded
    # around explicit heading seeds and does not recursively create new seeds.
    # The first adjacent page may use ordinary row evidence; further pages need
    # stronger TOC-specific density/known-title evidence.
    evidence_by_index = {item.pdf_page_index: item for item in evidence}
    for seed_page in continuation_seed_pages:
        for direction in (-1, 1):
            for distance in range(1, MAX_TOC_CONTINUATION_DISTANCE + 1):
                item = evidence_by_index.get(seed_page + (direction * distance))
                if item is None:
                    break
                previous = evidence_by_index.get(
                    seed_page + (direction * (distance - 1))
                )
                reference_continuity = (
                    previous is not None
                    and _plausibly_continues(
                        previous,
                        item,
                        direction=direction,
                    )
                )
                weak_continuation = (
                    item.entry_pattern_count >= 3
                    and item.confidence >= 0.30
                    and (
                        "page_column_heading" in item.matched_signals
                        or "toc_heading" in item.matched_signals
                        or reference_continuity
                    )
                )
                strong_continuation = (
                    item.entry_pattern_count >= 4
                    and item.confidence >= 0.38
                    and (
                        "page_column_heading" in item.matched_signals
                        or "toc_heading" in item.matched_signals
                        or (
                            item.known_section_count >= 1
                            and reference_continuity
                        )
                    )
                )
                if not (
                    weak_continuation
                    if distance == 1
                    else strong_continuation
                ):
                    break
                selected.add(item.pdf_page_index)

    selected_evidence = [item for item in evidence if item.pdf_page_index in selected]
    if not selected_evidence:
        return TocDetectionResult(
            detected=False,
            candidate_page_indexes=(),
            confidence=0.0,
            warnings=("toc_not_detected",),
            reasons=("No page met the deterministic TOC evidence threshold.",),
            page_evidence=tuple(evidence),
        )

    signals = sorted({signal for item in selected_evidence for signal in item.matched_signals})
    reasons = [reason for item in selected_evidence for reason in item.reasons]
    confidence = round(sum(item.confidence for item in selected_evidence) / len(selected_evidence), 4)
    warnings: list[str] = []
    if confidence < 0.65:
        warnings.append("toc_detection_low_confidence")
    excluded_qualified = [
        item.pdf_page_index
        for item in qualified
        if item.pdf_page_index not in selected
    ]
    if excluded_qualified:
        warnings.append("toc_candidates_outside_bounded_block")
    return TocDetectionResult(
        detected=True,
        candidate_page_indexes=tuple(sorted(selected)),
        confidence=confidence,
        matched_signals=tuple(signals),
        reasons=tuple(dict.fromkeys(reasons)),
        warnings=tuple(warnings),
        page_evidence=tuple(evidence),
        block_start_pdf_page_index=min(selected),
        block_end_pdf_page_index=max(selected),
        termination_reason=(
            "bounded_continuation_window_exhausted"
            if len(selected) > 1
            else "no_adjacent_credible_toc_continuation"
        ),
    )
