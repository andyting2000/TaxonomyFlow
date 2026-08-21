"""Read-only Extraction v2 candidate quality and mapping readiness analysis."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


NUMERIC_ROW_TYPES = {"numeric_fact", "comparative_numeric_fact", "subtotal_or_total"}
NON_MAPPING_ROW_TYPES = {"heading", "metadata", "unknown"}

DATE_ONLY_RE = re.compile(
    r"^(?:as\s+(?:at|of)\s+)?(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})$",
    re.IGNORECASE,
)
YEAR_ONLY_RE = re.compile(r"^(?:19|20)\d{2}$")
ENUM_ONLY_RE = re.compile(r"^\(?[A-Za-z]\)$|^\(?[ivxlcdm]{1,6}\)$", re.IGNORECASE)
GENERIC_PERIOD_LABELS = {
    "this year",
    "current year",
    "current period",
    "previous year",
    "previous period",
    "prior year",
    "prior period",
    "current",
    "previous",
    "prior",
}
GENERIC_SECTIONS = {
    "notes",
    "statement",
    "assets",
    "liabilities",
    "equity",
    "costs",
    "expenses",
    "other",
    "financial statements",
}
HEADING_TERMS_RE = re.compile(
    r"\b(statement|directors'? report|auditors'? report|statutory declaration|financial position|"
    r"profit or loss|cash flows?|changes in equity|notes to|accounting polic|assets|liabilities|equity)\b",
    re.IGNORECASE,
)
NARRATIVE_SECTION_RE = re.compile(
    r"\b(directors'? report|auditors'? report|statutory declaration|accounting polic|basis of preparation|"
    r"going concern|significant accounting|financial risk|approval of financial statements)\b",
    re.IGNORECASE,
)
NUMERIC_STATEMENT_SECTION_RE = re.compile(
    r"\b(financial position|profit or loss|comprehensive income|cash flows?|changes in equity|assets|"
    r"liabilities|equity|expenses|revenue|turnover|costs)\b",
    re.IGNORECASE,
)
TOTAL_RE = re.compile(r"\b(total|subtotal|sub-total|net assets|net current|profit before|profit after|loss before|loss after)\b", re.IGNORECASE)
NEGATIVE_NATURE_RE = re.compile(
    r"\b(loss|expense|cost|tax|depreciation|amortisation|amortization|impairment|liabilit|payable|deficit|outflow)\b",
    re.IGNORECASE,
)
STRUCTURAL_CONCEPT_RE = re.compile(
    r"\b(disclosure|explanatory|numberof|numberofshares|impact|standards?|polic|context|entity|identifier|registration)\b",
    re.IGNORECASE,
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_label(value: Any) -> str:
    text = clean_text(value).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def compact_label(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_label(value))


def normalize_terms(value: Any) -> set[str]:
    text = str(value or "")
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    text = re.sub(r"[^A-Za-z0-9]+", " ", text).lower()
    return {term for term in text.split() if len(term) >= 3}


def overlap_score(left: Any, right: Any) -> float:
    left_terms = normalize_terms(left)
    right_terms = normalize_terms(right)
    if not left_terms or not right_terms:
        return 0.0
    return len(left_terms & right_terms) / len(left_terms | right_terms)


def is_date_only_label(value: Any) -> bool:
    return bool(DATE_ONLY_RE.fullmatch(clean_text(value)))


def is_year_only_label(value: Any) -> bool:
    return bool(YEAR_ONLY_RE.fullmatch(clean_text(value)))


def is_enumeration_only_label(value: Any) -> bool:
    return bool(ENUM_ONLY_RE.fullmatch(clean_text(value)))


def is_generic_period_label(value: Any) -> bool:
    return normalize_label(value) in GENERIC_PERIOD_LABELS


def is_weak_label(value: Any) -> bool:
    label = clean_text(value)
    return (
        not label
        or len(normalize_label(label)) < 3
        or is_date_only_label(label)
        or is_year_only_label(label)
        or is_enumeration_only_label(label)
        or is_generic_period_label(label)
    )


def is_heading_like_label(value: Any) -> bool:
    label = clean_text(value)
    if not label:
        return False
    if HEADING_TERMS_RE.search(label):
        return True
    words = label.split()
    alpha = [char for char in label if char.isalpha()]
    return len(words) <= 8 and len(alpha) >= 3 and (label.isupper() or label.istitle())


def is_year_like_value(value: Any) -> bool:
    return bool(YEAR_ONLY_RE.fullmatch(clean_text(value)))


def is_date_like_value(value: Any) -> bool:
    return is_date_only_label(value)


def parse_amount(value: Any) -> Decimal | None:
    text = clean_text(value)
    if not text:
        return None
    if is_year_like_value(text) or is_date_like_value(text):
        return None
    if text in {"-", "–", "—"}:
        return Decimal("0")
    text = re.sub(r"\b(?:RM|MYR|USD)\b|\$", "", text, flags=re.IGNORECASE).strip()
    negative = text.startswith("-") or (text.startswith("(") and text.endswith(")"))
    cleaned = text.replace(",", "").replace("(", "").replace(")", "").replace(" ", "")
    if cleaned.startswith("-"):
        cleaned = cleaned[1:]
    if not re.fullmatch(r"\d+(?:\.\d+)?", cleaned):
        return None
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None
    return -amount if negative and amount != 0 else amount


def is_numeric_candidate(candidate: dict[str, Any]) -> bool:
    return str(candidate.get("row_type") or "") in NUMERIC_ROW_TYPES


def source_bucket(candidate: dict[str, Any]) -> str:
    method = str(candidate.get("extraction_method") or "unknown")
    if method == "huggingface_vision_fallback":
        return "huggingface"
    if method == "openai_vision_fallback":
        return "openai"
    if method in {"native_text", "native_table_heuristic"}:
        return "native_only"
    return "unknown"


def issue(code: str, category: str, severity: str, message: str, field: str | None = None) -> dict[str, str]:
    payload = {"code": code, "category": category, "severity": severity, "message": message}
    if field:
        payload["field"] = field
    return payload


def detect_candidate_issues(candidate: dict[str, Any]) -> list[dict[str, str]]:
    row_type = str(candidate.get("row_type") or "unknown")
    label = clean_text(candidate.get("label"))
    value = clean_text(candidate.get("value"))
    previous_value = clean_text(candidate.get("previous_value"))
    text = clean_text(candidate.get("text"))
    section = clean_text(candidate.get("statement_section"))
    issues: list[dict[str, str]] = []

    if not label and row_type != "text_block":
        issues.append(issue("empty_label", "label_quality", "high", "Candidate has no usable label.", "label"))
    if label and len(normalize_label(label)) < 3:
        issues.append(issue("too_short_label", "label_quality", "medium", "Candidate label is too short.", "label"))
    if is_date_only_label(label):
        issues.append(issue("date_only_label", "label_pollution", "high", "Candidate label is only a date.", "label"))
    if is_year_only_label(label):
        issues.append(issue("year_only_label", "label_pollution", "high", "Candidate label is only a year.", "label"))
    if is_generic_period_label(label):
        issues.append(issue("generic_period_label", "label_pollution", "high", "Candidate label is a generic period header.", "label"))
    if is_enumeration_only_label(label):
        issues.append(issue("enumeration_only_label", "label_quality", "medium", "Candidate label is only an enumeration marker.", "label"))
    if row_type in NUMERIC_ROW_TYPES and is_heading_like_label(label) and not TOTAL_RE.search(label or ""):
        issues.append(issue("heading_like_numeric_fact", "label_quality", "medium", "Heading-like label was classified as a numeric fact.", "label"))

    if row_type in NUMERIC_ROW_TYPES:
        amount = parse_amount(value)
        previous_amount = parse_amount(previous_value)
        if not value:
            issues.append(issue("missing_numeric_value", "numeric_quality", "high", "Numeric candidate is missing a current value.", "value"))
        elif amount is None:
            if is_date_like_value(value) or is_year_like_value(value):
                issues.append(issue("date_or_year_value_as_amount", "numeric_quality", "high", "Date/year-like value is stored as an amount.", "value"))
            else:
                issues.append(issue("non_numeric_value", "numeric_quality", "high", "Numeric candidate value is not numeric.", "value"))
        if label and parse_amount(label) is not None:
            issues.append(issue("numeric_value_in_label", "numeric_quality", "high", "Numeric-looking value is stored in the label.", "label"))
        if previous_value and previous_amount is None:
            if is_date_like_value(previous_value) or is_year_like_value(previous_value):
                issues.append(issue("date_or_year_previous_value", "comparative_quality", "high", "Prior value is date/year-like, not an amount.", "previous_value"))
            else:
                issues.append(issue("non_numeric_previous_value", "comparative_quality", "high", "Prior value is not numeric.", "previous_value"))
        if previous_value and not value:
            issues.append(issue("previous_without_current", "comparative_quality", "high", "Prior value exists without a current value.", "previous_value"))
        if row_type == "comparative_numeric_fact" and not previous_value:
            issues.append(issue("missing_previous_value", "comparative_quality", "medium", "Comparative candidate is missing previous_value.", "previous_value"))
        if previous_value and not candidate.get("current_year") and not candidate.get("prior_year"):
            issues.append(issue("missing_year_context", "comparative_quality", "medium", "Comparative values have no current/prior year context."))
        if amount is not None and previous_amount is not None and amount == previous_amount:
            issues.append(issue("identical_current_previous_values", "comparative_quality", "low", "Current and previous values are identical."))
        if "(" in value or "(" in previous_value:
            issues.append(issue("parentheses_negative_value", "numeric_quality", "info", "Parentheses negative value needs sign preservation."))
        if value in {"-", "–", "—", "0"} or previous_value in {"-", "–", "—", "0"}:
            issues.append(issue("dash_or_zero_value", "numeric_quality", "low", "Dash or zero value needs normalization policy."))
        if any(token in value for token in [",", "$"]) or re.search(r"\b(?:RM|MYR|USD)\b", value, re.IGNORECASE):
            issues.append(issue("amount_format_normalization", "numeric_quality", "info", "Amount contains currency/comma formatting."))
        if amount is not None and amount < 0 and label and not NEGATIVE_NATURE_RE.search(label):
            issues.append(issue("suspicious_negative_value", "numeric_quality", "medium", "Negative value appears under a label that may normally be positive."))
        if is_weak_label(label) and value:
            issues.append(issue("amount_with_weak_label", "mapping_readiness", "high", "Amount row has weak label evidence."))
        if (is_date_only_label(label) or is_year_only_label(label) or is_generic_period_label(label)) and value:
            issues.append(issue("year_header_row_extracted_as_fact", "comparative_quality", "high", "Period header row appears to be extracted as a fact."))
        if previous_value and str(candidate.get("row_type")) == "numeric_fact":
            issues.append(issue("comparative_value_under_numeric_type", "comparative_quality", "medium", "Candidate has previous_value but row_type is numeric_fact."))

    if row_type == "text_block":
        text_value = text or clean_text(candidate.get("source_snippet")) or clean_text(candidate.get("value"))
        word_count = len(text_value.split())
        if word_count < 8 or len(text_value) < 60:
            issues.append(issue("short_text_block", "text_block_quality", "medium", "Text block is short and may be a heading or line fragment.", "text"))
        if len(text_value) > 2500 or word_count > 350:
            issues.append(issue("long_text_block", "text_block_quality", "medium", "Text block is very long and may merge unrelated disclosure text.", "text"))
        if is_heading_like_label(text_value) and word_count <= 10:
            issues.append(issue("text_block_heading_only", "text_block_quality", "medium", "Text block looks like a heading only.", "text"))
        if is_weak_label(label):
            issues.append(issue("weak_text_block_label", "text_block_quality", "low", "Text block has weak or missing label.", "label"))

    if not section:
        issues.append(issue("missing_statement_section", "section_quality", "medium", "Candidate has no statement_section.", "statement_section"))
    elif normalize_label(section) in GENERIC_SECTIONS:
        issues.append(issue("generic_statement_section", "section_quality", "low", "Candidate statement_section is too generic.", "statement_section"))
    if row_type in NUMERIC_ROW_TYPES and NARRATIVE_SECTION_RE.search(section):
        issues.append(issue("numeric_under_narrative_section", "section_quality", "medium", "Numeric fact is under a narrative/report section.", "statement_section"))
    if row_type == "text_block" and NUMERIC_STATEMENT_SECTION_RE.search(section):
        issues.append(issue("text_under_numeric_section", "section_quality", "low", "Text block is under a numeric statement section.", "statement_section"))

    return issues


def readiness_for_candidate(candidate: dict[str, Any], issues: list[dict[str, str]]) -> str:
    row_type = str(candidate.get("row_type") or "unknown")
    issue_codes = {item["code"] for item in issues}
    high_blockers = {
        "empty_label",
        "date_only_label",
        "year_only_label",
        "generic_period_label",
        "missing_numeric_value",
        "non_numeric_value",
        "date_or_year_value_as_amount",
        "numeric_value_in_label",
        "amount_with_weak_label",
        "year_header_row_extracted_as_fact",
        "duplicate_label_conflicting_values",
    }
    medium_risks = {
        "missing_statement_section",
        "generic_statement_section",
        "missing_year_context",
        "missing_previous_value",
        "heading_like_numeric_fact",
        "short_text_block",
        "text_block_heading_only",
        "exact_duplicate_same_page",
        "duplicate_label_value_same_case",
    }
    if row_type in NON_MAPPING_ROW_TYPES:
        return "not_ready"
    if issue_codes & high_blockers:
        return "low"
    if row_type in NUMERIC_ROW_TYPES and parse_amount(candidate.get("value")) is not None and not (issue_codes & medium_risks):
        return "high"
    if row_type == "text_block":
        text = clean_text(candidate.get("text") or candidate.get("source_snippet") or candidate.get("value"))
        if len(text.split()) >= 15 and "missing_statement_section" not in issue_codes and "text_block_heading_only" not in issue_codes:
            return "high"
    if issue_codes & medium_risks:
        return "medium"
    return "medium"


def _candidate_identity(candidate: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "index": index,
        "case_id": candidate.get("case_id"),
        "page_number": candidate.get("page_number"),
        "row_type": candidate.get("row_type"),
        "label": candidate.get("label"),
        "value": candidate.get("value"),
        "previous_value": candidate.get("previous_value"),
        "statement_section": candidate.get("statement_section"),
        "extraction_method": candidate.get("extraction_method"),
    }


def flatten_candidates(v2_report: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for case_report in v2_report.get("case_reports") or []:
        case_id = str(case_report.get("case_id") or "")
        for candidate in case_report.get("candidates") or []:
            enriched = dict(candidate)
            enriched.setdefault("case_id", case_id)
            candidates.append(enriched)
    return candidates


def _add_duplicate_issues(candidates: list[dict[str, Any]], analysis: list[dict[str, Any]]) -> dict[str, Any]:
    exact: dict[tuple[Any, ...], list[int]] = defaultdict(list)
    label_value_case: dict[tuple[Any, ...], list[int]] = defaultdict(list)
    label_case_values: dict[tuple[Any, ...], set[tuple[str, str]]] = defaultdict(set)
    label_case_indexes: dict[tuple[Any, ...], list[int]] = defaultdict(list)
    compact_counts: Counter[str] = Counter()
    for idx, candidate in enumerate(candidates):
        case_id = candidate.get("case_id")
        label = normalize_label(candidate.get("label") or candidate.get("text") or candidate.get("source_snippet"))
        compact_counts[compact_label(label)] += 1
        value = clean_text(candidate.get("value"))
        previous = clean_text(candidate.get("previous_value"))
        page = candidate.get("page_number")
        row_type = candidate.get("row_type")
        section = normalize_label(candidate.get("statement_section"))
        exact[(case_id, page, row_type, section, label, value, previous)].append(idx)
        label_value_case[(case_id, label, value, previous)].append(idx)
        label_case_values[(case_id, label)].add((value, previous))
        label_case_indexes[(case_id, label)].append(idx)

    duplicate_summary: Counter[str] = Counter()
    duplicate_labels: Counter[str] = Counter()
    for indexes in exact.values():
        if len(indexes) > 1:
            duplicate_summary["exact_duplicate_same_page"] += len(indexes)
            for idx in indexes:
                analysis[idx]["issues"].append(
                    issue("exact_duplicate_same_page", "duplicate_quality", "medium", "Exact duplicate candidate appears on the same page.")
                )
                duplicate_labels[normalize_label(candidates[idx].get("label")) or "(blank)"] += 1
    for indexes in label_value_case.values():
        if len(indexes) > 1:
            duplicate_summary["duplicate_label_value_same_case"] += len(indexes)
            for idx in indexes:
                analysis[idx]["issues"].append(
                    issue("duplicate_label_value_same_case", "duplicate_quality", "low", "Duplicate label/value appears within the same case.")
                )
                duplicate_labels[normalize_label(candidates[idx].get("label")) or "(blank)"] += 1
    for key, values in label_case_values.items():
        label = key[1]
        useful_values = {pair for pair in values if pair != ("", "")}
        if label and len(useful_values) > 1:
            duplicate_summary["duplicate_label_conflicting_values"] += len(label_case_indexes[key])
            duplicate_labels[label] += len(label_case_indexes[key])
            for idx in label_case_indexes[key]:
                analysis[idx]["issues"].append(
                    issue("duplicate_label_conflicting_values", "duplicate_quality", "high", "Same case label appears with conflicting values.")
                )
    near_duplicates = [
        {"normalized_label": label, "count": count}
        for label, count in compact_counts.most_common()
        if label and count > 1
    ][:25]
    for item in analysis:
        item["readiness"] = readiness_for_candidate(item["candidate"], item["issues"])
    return {
        "issue_counts": dict(sorted(duplicate_summary.items())),
        "top_duplicate_labels": [{"label": label, "count": count} for label, count in duplicate_labels.most_common(25)],
        "top_near_duplicate_labels": near_duplicates,
    }


def _reference_case_map(reference_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(case.get("case_id")): case for case in reference_report.get("case_reports") or []}


def _comparison_case_map(comparison_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(case.get("case_id")): case for case in comparison_report.get("per_case") or []}


def _summarize_reference_overlap(
    candidates: list[dict[str, Any]],
    reference_report: dict[str, Any],
    comparison_report: dict[str, Any],
) -> dict[str, Any]:
    labels = [candidate.get("label") or candidate.get("text") or candidate.get("source_snippet") for candidate in candidates]
    facts = [fact for case in reference_report.get("case_reports") or [] for fact in case.get("facts") or []]
    top_missing = comparison_report.get("top_reference_concepts_not_represented_in_v2") or []
    likely_extraction_misses = []
    likely_label_normalization = []
    likely_structural = []
    for item in top_missing[:25]:
        concept = item.get("concept")
        best = max((overlap_score(concept, label) for label in labels), default=0.0)
        entry = {"concept": concept, "count": item.get("count", 0), "best_v2_label_overlap": round(best, 3)}
        if STRUCTURAL_CONCEPT_RE.search(str(concept or "")):
            likely_structural.append(entry)
        elif best >= 0.2:
            likely_label_normalization.append(entry)
        else:
            likely_extraction_misses.append(entry)
    return {
        "reference_total_facts": len(facts),
        "reference_concepts_count": len({fact.get("qname") for fact in facts if fact.get("qname")}),
        "rough_label_concept_overlap_count": (comparison_report.get("aggregate_metrics") or {}).get("rough_label_concept_overlap_count", 0),
        "top_reference_concepts_not_represented_in_v2": top_missing[:25],
        "top_v2_labels_not_found_in_reference": (comparison_report.get("top_v2_candidates_not_found_in_reference") or [])[:25],
        "likely_extraction_misses": likely_extraction_misses[:10],
        "likely_label_normalization_issues": likely_label_normalization[:10],
        "likely_structural_taxonomy_concepts": likely_structural[:10],
        "limitation": "This is rough offline overlap only and is not final taxonomy mapping accuracy.",
    }


def classify_case_readiness(
    *,
    total_candidates: int,
    numeric_candidates: int,
    text_block_candidates: int,
    readiness_counts: Counter,
    issue_counts: Counter,
    reference_text_blocks: int = 0,
) -> str:
    if not total_candidates:
        return "not_ready_for_mapping"
    not_ready = readiness_counts.get("not_ready", 0)
    low = readiness_counts.get("low", 0)
    high = readiness_counts.get("high", 0)
    medium = readiness_counts.get("medium", 0)
    blocking_label = sum(issue_counts.get(code, 0) for code in ["date_only_label", "year_only_label", "generic_period_label", "amount_with_weak_label"])
    duplicate_conflicts = issue_counts.get("duplicate_label_conflicting_values", 0)
    text_issues = sum(issue_counts.get(code, 0) for code in ["short_text_block", "text_block_heading_only", "weak_text_block_label"])
    numeric_issues = sum(issue_counts.get(code, 0) for code in ["non_numeric_value", "date_or_year_value_as_amount", "missing_numeric_value"])
    if not_ready > total_candidates * 0.45 or numeric_issues > 0:
        return "needs_numeric_cleanup_first"
    if duplicate_conflicts > max(3, total_candidates * 0.15):
        return "needs_manual_review_policy"
    if blocking_label >= max(1, total_candidates * 0.1):
        return "needs_candidate_cleanup_first"
    if reference_text_blocks and text_block_candidates == 0:
        return "needs_text_block_cleanup_first"
    if text_issues > max(3, text_block_candidates * 0.3):
        return "needs_text_block_cleanup_first"
    if high + medium >= total_candidates * 0.65 and low <= total_candidates * 0.25:
        return "ready_for_mapping_prototype"
    return "needs_candidate_cleanup_first"


def score_from_counts(total: int, high: int, medium: int, low: int, not_ready: int) -> float:
    if total <= 0:
        return 0.0
    score = ((high * 1.0) + (medium * 0.65) + (low * 0.25) - (not_ready * 0.15)) / total
    return round(max(0.0, min(1.0, score)) * 100, 1)


def _top_issue_entries(issue_counts: Counter, limit: int = 10) -> list[dict[str, Any]]:
    return [{"issue": code, "count": count} for code, count in issue_counts.most_common(limit)]


def _build_recommendations(issue_counts: Counter) -> tuple[list[str], list[str], list[str], list[str], str]:
    safe = [
        "Remove or reclassify pure date labels extracted as numeric facts.",
        "Reclassify pure year/date rows as metadata or heading, not facts.",
        "Normalize whitespace, punctuation, currency symbols, commas, dashes, and parentheses negatives.",
        "Suppress empty candidates and keep empty candidate pages as processed benchmark evidence.",
    ]
    conservative = [
        "Infer current/prior years only from nearby table headers with explicit evidence.",
        "Apply subtotal versus total classification with section-aware heuristics.",
        "Handle duplicate label conflicts with an explicit review or aggregation policy.",
        "Use nearby headings for section inheritance when statement_section is missing.",
        "Tune text-block grouping so narrative disclosures are not split line by line or merged across sections.",
    ]
    mapping_stage = [
        "Match labels to taxonomy concepts only after candidate validity gates pass.",
        "Separate detail rows from summary concepts before mapping.",
        "Define sign policy and concept-specific guardrails before value normalization changes.",
        "Keep dimensions and aggregation decisions in the mapping stage, not extraction cleanup.",
    ]
    manual = [
        "Review duplicate labels with conflicting values.",
        "Review weak labels attached to numeric values.",
        "Review ambiguous labels that could map to multiple taxonomy concepts.",
        "Review suspicious negative values and possible current/prior reversal cases.",
    ]
    label_blockers = sum(issue_counts.get(code, 0) for code in ["date_only_label", "year_only_label", "generic_period_label", "amount_with_weak_label"])
    duplicate_blockers = issue_counts.get("duplicate_label_conflicting_values", 0)
    text_blockers = sum(issue_counts.get(code, 0) for code in ["short_text_block", "text_block_heading_only", "weak_text_block_label"])
    numeric_blockers = sum(issue_counts.get(code, 0) for code in ["non_numeric_value", "date_or_year_value_as_amount", "missing_numeric_value"])
    ranked = {
        "label": label_blockers,
        "duplicate": duplicate_blockers,
        "text": text_blockers,
        "numeric": numeric_blockers,
    }
    largest = max(ranked, key=ranked.get)
    if largest == "label":
        next_feature = "Feature #13S - Extraction v2 candidate normalization and label cleanup before mapping."
    elif largest == "duplicate":
        next_feature = "Feature #13S - Extraction v2 duplicate and conflict control before mapping."
    elif largest == "text":
        next_feature = "Feature #13S - Extraction v2 text-block boundary and section cleanup."
    else:
        next_feature = "Feature #13S - Mapping candidate generation v2 with conservative taxonomy readiness gates."
    return safe, conservative, mapping_stage, manual, next_feature


def mapping_readiness_gates() -> list[dict[str, Any]]:
    return [
        {
            "gate": "Candidate validity gate",
            "checks": [
                "numeric candidates must have numeric values",
                "text blocks must have sufficient text",
                "labels must not be empty",
                "pure year/date rows must not be treated as facts",
            ],
        },
        {
            "gate": "Duplicate conflict gate",
            "checks": [
                "duplicate label/value rows need evidence for detail rows",
                "duplicate labels with conflicting values require review or aggregation policy",
            ],
        },
        {
            "gate": "Section confidence gate",
            "checks": [
                "candidate should have a reasonable statement_section",
                "missing or generic section lowers readiness",
            ],
        },
        {
            "gate": "Year/context gate",
            "checks": [
                "current/prior values should be assigned consistently",
                "year headers must not become facts",
            ],
        },
        {
            "gate": "Sign gate",
            "checks": [
                "negative values should preserve original evidence",
                "sign normalization must not happen silently",
            ],
        },
        {
            "gate": "Text-block gate",
            "checks": [
                "text blocks should not be over-split into single-line fragments",
                "text blocks should not be merged across unrelated sections",
            ],
        },
        {
            "gate": "Mapping confidence gate",
            "checks": [
                "no automatic mapping for weak labels or generic headings",
                "manual review is required for low-confidence mapping",
            ],
        },
    ]


def analyze_candidate_quality_reports(
    *,
    v2_report: dict[str, Any],
    comparison_report: dict[str, Any],
    reference_report: dict[str, Any],
    closeout_report: dict[str, Any] | None = None,
    input_paths: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    candidates = flatten_candidates(v2_report)
    candidate_analysis: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        issues = detect_candidate_issues(candidate)
        candidate_analysis.append(
            {
                "candidate_id": f"{candidate.get('case_id')}:{candidate.get('page_number')}:{index}",
                "candidate": _candidate_identity(candidate, index),
                "issues": issues,
                "readiness": readiness_for_candidate(candidate, issues),
            }
        )
    duplicate_summary = _add_duplicate_issues(candidates, candidate_analysis)

    row_type_counts = Counter(str(candidate.get("row_type") or "unknown") for candidate in candidates)
    source_counts = Counter(source_bucket(candidate) for candidate in candidates)
    issue_counts: Counter = Counter()
    issue_category_counts: Counter = Counter()
    for item in candidate_analysis:
        for candidate_issue in item["issues"]:
            issue_counts[candidate_issue["code"]] += 1
            issue_category_counts[candidate_issue["category"]] += 1
    readiness_counts = Counter(item["readiness"] for item in candidate_analysis)

    comparison_cases = _comparison_case_map(comparison_report)
    reference_cases = _reference_case_map(reference_report)
    per_case: list[dict[str, Any]] = []
    grouped_analysis: dict[str, list[dict[str, Any]]] = defaultdict(list)
    grouped_candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in candidate_analysis:
        grouped_analysis[str(item["candidate"].get("case_id"))].append(item)
    for candidate in candidates:
        grouped_candidates[str(candidate.get("case_id"))].append(candidate)

    for case_id in sorted(grouped_candidates):
        case_candidates = grouped_candidates[case_id]
        case_analysis = grouped_analysis[case_id]
        case_issue_counts = Counter(
            candidate_issue["code"]
            for item in case_analysis
            for candidate_issue in item["issues"]
        )
        case_readiness_counts = Counter(item["readiness"] for item in case_analysis)
        case_row_counts = Counter(str(candidate.get("row_type") or "unknown") for candidate in case_candidates)
        case_source_counts = Counter(source_bucket(candidate) for candidate in case_candidates)
        comparison_case = comparison_cases.get(case_id, {})
        reference_case = reference_cases.get(case_id, {})
        total = len(case_candidates)
        high = case_readiness_counts.get("high", 0)
        medium = case_readiness_counts.get("medium", 0)
        low = case_readiness_counts.get("low", 0)
        not_ready = case_readiness_counts.get("not_ready", 0)
        per_case.append(
            {
                "case_id": case_id,
                "total_candidates": total,
                "numeric_candidates": sum(case_row_counts.get(row_type, 0) for row_type in NUMERIC_ROW_TYPES),
                "text_block_candidates": case_row_counts.get("text_block", 0),
                "huggingface_candidates": case_source_counts.get("huggingface", 0),
                "native_only_candidates": case_source_counts.get("native_only", 0),
                "openai_candidates": case_source_counts.get("openai", 0),
                "reference_facts": reference_case.get("total_facts", comparison_case.get("reference_total_facts", 0)),
                "reference_numeric_facts": reference_case.get("numeric_fact_count", comparison_case.get("reference_numeric_facts", 0)),
                "reference_text_blocks": reference_case.get("text_block_count", comparison_case.get("reference_text_blocks", 0)),
                "candidate_quality_score": score_from_counts(total, high, medium, low, not_ready),
                "mapping_readiness_score": score_from_counts(total, high, medium, low, not_ready),
                "high_readiness_count": high,
                "medium_readiness_count": medium,
                "low_readiness_count": low,
                "not_ready_count": not_ready,
                "top_candidate_quality_issues": _top_issue_entries(case_issue_counts, 10),
                "top_mapping_blockers": _top_issue_entries(
                    Counter({code: count for code, count in case_issue_counts.items() if count and code not in {"amount_format_normalization"}}),
                    10,
                ),
                "top_labels_needing_cleanup": [
                    {"label": label, "count": count}
                    for label, count in Counter(
                        normalize_label(item["candidate"].get("label")) or "(blank)"
                        for item in case_analysis
                        if any(candidate_issue["category"] in {"label_pollution", "label_quality"} for candidate_issue in item["issues"])
                    ).most_common(10)
                ],
                "ready_for_mapping_prototype": classify_case_readiness(
                    total_candidates=total,
                    numeric_candidates=sum(case_row_counts.get(row_type, 0) for row_type in NUMERIC_ROW_TYPES),
                    text_block_candidates=case_row_counts.get("text_block", 0),
                    readiness_counts=case_readiness_counts,
                    issue_counts=case_issue_counts,
                    reference_text_blocks=int(reference_case.get("text_block_count") or comparison_case.get("reference_text_blocks") or 0),
                ),
            }
        )

    top_suspicious_labels = [
        {"label": label, "count": count}
        for label, count in Counter(
            normalize_label(item["candidate"].get("label")) or "(blank)"
            for item in candidate_analysis
            if any(candidate_issue["category"] in {"label_pollution", "label_quality"} for candidate_issue in item["issues"])
        ).most_common(25)
    ]
    top_section_problems = [
        {"issue": code, "count": count}
        for code, count in Counter(
            candidate_issue["code"]
            for item in candidate_analysis
            for candidate_issue in item["issues"]
            if candidate_issue["category"] == "section_quality"
        ).most_common(25)
    ]
    numeric_summary = {
        "numeric_candidate_count": sum(row_type_counts.get(row_type, 0) for row_type in NUMERIC_ROW_TYPES),
        "missing_value_count": issue_counts.get("missing_numeric_value", 0),
        "non_numeric_value_count": issue_counts.get("non_numeric_value", 0),
        "date_or_year_value_as_amount_count": issue_counts.get("date_or_year_value_as_amount", 0),
        "parentheses_negative_count": issue_counts.get("parentheses_negative_value", 0),
        "dash_or_zero_count": issue_counts.get("dash_or_zero_value", 0),
        "amount_format_normalization_count": issue_counts.get("amount_format_normalization", 0),
        "suspicious_negative_count": issue_counts.get("suspicious_negative_value", 0),
    }
    text_summary = {
        "text_block_count": row_type_counts.get("text_block", 0),
        "short_text_block_count": issue_counts.get("short_text_block", 0),
        "long_text_block_count": issue_counts.get("long_text_block", 0),
        "heading_only_text_block_count": issue_counts.get("text_block_heading_only", 0),
        "weak_text_block_label_count": issue_counts.get("weak_text_block_label", 0),
        "cases_missing_text_block_signal": (comparison_report.get("aggregate_metrics") or {}).get("missing_text_block_cases", []),
    }
    source_quality = {
        "source_distribution": dict(sorted(source_counts.items())),
        "huggingface_candidate_count": source_counts.get("huggingface", 0),
        "native_only_candidate_count": source_counts.get("native_only", 0),
        "openai_candidate_count": source_counts.get("openai", 0),
        "unknown_source_candidate_count": source_counts.get("unknown", 0),
    }
    safe, conservative, mapping_stage, manual, recommended_next = _build_recommendations(issue_counts)
    reference_overlap = _summarize_reference_overlap(candidates, reference_report, comparison_report)

    input_paths = input_paths or {}
    metadata = {
        "generated_at": utc_now_iso(),
        "feature": "13R",
        "read_only": True,
        "database_mutated": False,
        "production_behavior_changed": False,
        "ui_upload_required": False,
        "xbrl_generated": False,
        "arelle_validation_run": False,
        "live_huggingface_calls_made": False,
        "live_openai_calls_made": False,
        "reference_xml_sent_to_model": False,
        "benchmark_rerun": False,
    }
    quality_report = {
        "run_metadata": {
            **metadata,
            "report_type": "candidate_quality",
            "script": "scripts/analyze_extraction_v2_candidate_quality.py",
        },
        "input_reports": input_paths,
        "final_13q_benchmark_still_successful": True,
        "aggregate_candidate_counts": {
            "total_candidates": len(candidates),
            "candidate_type_distribution": dict(sorted(row_type_counts.items())),
            "source_distribution": dict(sorted(source_counts.items())),
            "readiness_distribution": dict(sorted(readiness_counts.items())),
        },
        "per_case": per_case,
        "quality_issue_counts": dict(sorted(issue_counts.items())),
        "quality_issue_category_counts": dict(sorted(issue_category_counts.items())),
        "top_issue_categories": [{"category": key, "count": count} for key, count in issue_category_counts.most_common(10)],
        "top_suspicious_labels": top_suspicious_labels,
        "top_duplicate_labels": duplicate_summary["top_duplicate_labels"],
        "top_near_duplicate_labels": duplicate_summary["top_near_duplicate_labels"],
        "top_section_problems": top_section_problems,
        "numeric_quality_summary": numeric_summary,
        "text_block_quality_summary": text_summary,
        "source_quality_summary": source_quality,
        "reference_overlap_summary": reference_overlap,
        "candidate_samples_with_issues": [
            item for item in candidate_analysis if item["issues"]
        ][:100],
        "limitations": [
            "Heuristic analysis only; scores are provisional and are not final mapping accuracy.",
            "Reference report is used only for offline comparison and is not sent to any model.",
            "No benchmark rerun, model call, DB mutation, XBRL generation, Arelle validation, UI upload, or production cutover is performed.",
        ],
    }
    readiness_report = {
        "run_metadata": {
            **metadata,
            "report_type": "mapping_readiness",
            "script": "scripts/analyze_extraction_v2_candidate_quality.py",
        },
        "input_reports": input_paths,
        "readiness_assessment": {
            "overall_status": "promising_but_not_production_ready",
            "assessment": (
                "#13Q benchmark succeeded and Extraction v2 plus Hugging Face Qwen now produces useful numeric "
                "and text-block candidates. Candidate normalization, duplicate control, section confidence, and "
                "mapping readiness gates are needed before production cutover."
            ),
            "production_ready": False,
            "mapping_pipeline_ready": False,
            "xbrl_generation_validated": False,
            "arelle_validation_passed": False,
        },
        "aggregate_readiness_counts": dict(sorted(readiness_counts.items())),
        "per_case_readiness": per_case,
        "mapping_readiness_gates": mapping_readiness_gates(),
        "blocker_list": _top_issue_entries(issue_counts, 25),
        "candidate_cleanup_recommendations": {
            "safe_deterministic_cleanup_candidates": safe,
            "needs_conservative_heuristics": conservative,
            "needs_mapping_stage_design": mapping_stage,
            "needs_manual_review": manual,
        },
        "recommended_next_feature": recommended_next,
        "limitations": [
            "Readiness scores are heuristic and conservative.",
            "This report does not perform taxonomy mapping.",
            "This report does not generate XBRL or run Arelle validation.",
            "Hugging Face candidates are not guaranteed correct without review.",
        ],
    }
    if closeout_report:
        quality_report["closeout_context"] = {
            "full_hf_benchmark_successful": (closeout_report.get("benchmark_completion_assessment") or {}).get("full_hf_benchmark_successful"),
            "openai_used": (closeout_report.get("runtime") or {}).get("openai_used"),
            "recommended_next_feature": closeout_report.get("recommended_next_feature"),
        }
        readiness_report["closeout_context"] = quality_report["closeout_context"]
    return quality_report, readiness_report


def render_candidate_quality_markdown(report: dict[str, Any]) -> str:
    aggregate = report["aggregate_candidate_counts"]
    numeric = report["numeric_quality_summary"]
    text = report["text_block_quality_summary"]
    source = report["source_quality_summary"]
    lines = [
        "# Feature #13R Extraction v2 Candidate Quality Report",
        "",
        "## Summary",
        "",
        f"- Total candidates analyzed: {aggregate.get('total_candidates', 0)}",
        f"- Candidate type distribution: {aggregate.get('candidate_type_distribution', {})}",
        f"- Source distribution: {aggregate.get('source_distribution', {})}",
        f"- Readiness distribution: {aggregate.get('readiness_distribution', {})}",
        f"- Database mutated: {report['run_metadata']['database_mutated']}",
        f"- Live model calls made: {report['run_metadata']['live_huggingface_calls_made'] or report['run_metadata']['live_openai_calls_made']}",
        f"- Reference XML sent to model: {report['run_metadata']['reference_xml_sent_to_model']}",
        "",
        "## Numeric Quality",
        "",
        f"- Numeric candidates: {numeric.get('numeric_candidate_count', 0)}",
        f"- Missing values: {numeric.get('missing_value_count', 0)}",
        f"- Non-numeric values: {numeric.get('non_numeric_value_count', 0)}",
        f"- Date/year values as amounts: {numeric.get('date_or_year_value_as_amount_count', 0)}",
        f"- Parentheses negatives: {numeric.get('parentheses_negative_count', 0)}",
        f"- Dash/zero values: {numeric.get('dash_or_zero_count', 0)}",
        f"- Amount formatting concerns: {numeric.get('amount_format_normalization_count', 0)}",
        "",
        "## Text-Block Quality",
        "",
        f"- Text blocks: {text.get('text_block_count', 0)}",
        f"- Short text blocks: {text.get('short_text_block_count', 0)}",
        f"- Long text blocks: {text.get('long_text_block_count', 0)}",
        f"- Heading-only text blocks: {text.get('heading_only_text_block_count', 0)}",
        f"- Weak text-block labels: {text.get('weak_text_block_label_count', 0)}",
        f"- Cases missing text-block signal: {text.get('cases_missing_text_block_signal', [])}",
        "",
        "## Source Quality",
        "",
        f"- Hugging Face candidates: {source.get('huggingface_candidate_count', 0)}",
        f"- Native-only candidates: {source.get('native_only_candidate_count', 0)}",
        f"- OpenAI candidates: {source.get('openai_candidate_count', 0)}",
        f"- Unknown-source candidates: {source.get('unknown_source_candidate_count', 0)}",
        "",
        "## Top Issue Categories",
        "",
    ]
    lines.extend(f"- {item['category']}: {item['count']}" for item in report.get("top_issue_categories", []))
    lines.extend(["", "## Per Case", ""])
    lines.extend([
        "| Case | Candidates | Numeric | Text Blocks | HF | Native | Score | Readiness |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ])
    for case in report.get("per_case", []):
        lines.append(
            "| {case_id} | {total_candidates} | {numeric_candidates} | {text_block_candidates} | {huggingface_candidates} | {native_only_candidates} | {candidate_quality_score} | {ready_for_mapping_prototype} |".format(
                **case
            )
        )
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.get("limitations", []))
    lines.append("")
    return "\n".join(lines)


def render_mapping_readiness_markdown(report: dict[str, Any]) -> str:
    assessment = report["readiness_assessment"]
    lines = [
        "# Feature #13R Extraction v2 Mapping Readiness Report",
        "",
        "## Assessment",
        "",
        f"- Overall status: {assessment.get('overall_status')}",
        f"- Production ready: {assessment.get('production_ready')}",
        f"- Mapping pipeline ready: {assessment.get('mapping_pipeline_ready')}",
        f"- XBRL generation validated: {assessment.get('xbrl_generation_validated')}",
        f"- Arelle validation passed: {assessment.get('arelle_validation_passed')}",
        f"- Database mutated: {report['run_metadata']['database_mutated']}",
        "",
        assessment.get("assessment", ""),
        "",
        "## Readiness Counts",
        "",
        f"- {report.get('aggregate_readiness_counts', {})}",
        "",
        "## Per Case Readiness",
        "",
        "| Case | High | Medium | Low | Not Ready | Score | Classification |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for case in report.get("per_case_readiness", []):
        lines.append(
            "| {case_id} | {high_readiness_count} | {medium_readiness_count} | {low_readiness_count} | {not_ready_count} | {mapping_readiness_score} | {ready_for_mapping_prototype} |".format(
                **case
            )
        )
    lines.extend(["", "## Mapping Readiness Gates", ""])
    for gate in report.get("mapping_readiness_gates", []):
        lines.append(f"### {gate['gate'].title()}")
        for check in gate.get("checks", []):
            lines.append(f"- {check}")
        lines.append("")
    recommendations = report.get("candidate_cleanup_recommendations", {})
    lines.extend(["## Cleanup Recommendations", ""])
    for title, items in recommendations.items():
        lines.append(f"### {title.replace('_', ' ').title()}")
        lines.extend(f"- {item}" for item in items)
        lines.append("")
    lines.extend(["## Recommended Next Feature", "", f"- {report.get('recommended_next_feature')}", ""])
    return "\n".join(lines)
