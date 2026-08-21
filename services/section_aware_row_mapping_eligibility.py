"""Deterministic extracted-row eligibility classification for #19C."""

from __future__ import annotations

import re
from typing import Any, Mapping

from schemas import RowMappingEligibility
from services.section_aware_taxonomy_concept_cards import normalize_concept_label


ELIGIBILITY_VERSION = "19C-row-eligibility-v1"
ELIGIBLE_OUTCOMES = {"fact_candidate", "subtotal_candidate", "total_candidate"}
STRUCTURAL_SECTION_OUTCOMES = {
    "narrative_only",
    "container_only",
    "not_applicable",
    "classification_failed",
}
TOTAL_RE = re.compile(r"\b(total|net total|grand total|total assets|total liabilities|total equity)\b", re.I)
SUBTOTAL_RE = re.compile(r"\b(subtotal|gross profit|profit before tax|profit from operations)\b", re.I)
HEADER_RE = re.compile(r"^(description|particulars|note|notes|current year|previous year|prior year|rm|myr)$", re.I)


def _has_value(value: Any) -> bool:
    return value is not None and str(value).strip() not in {"", "-", "—", "–"}


def classify_row_mapping_eligibility(
    row: Mapping[str, Any],
    *,
    section_outcome: str | None,
    duplicate_group_id: str | None = None,
    duplicate_rank: int = 0,
    competing_source_row_ids: list[str] | None = None,
) -> RowMappingEligibility:
    source_row_id = str(row.get("source_row_id") or row.get("row_id") or "")
    label = " ".join(str(row.get("label") or row.get("extracted_label") or "").split())
    normalized = normalize_concept_label(label)
    row_type = str(row.get("row_type") or "unknown").strip().lower()
    values_present = _has_value(row.get("current_value", row.get("value"))) or _has_value(
        row.get("prior_value", row.get("previous_value"))
    )
    reasons: list[str] = [f"eligibility_version:{ELIGIBILITY_VERSION}"]

    if section_outcome in STRUCTURAL_SECTION_OUTCOMES:
        outcome = "structural_only"
        reasons.append(f"section_outcome:{section_outcome}")
    elif section_outcome in {"ambiguous", "unassigned", None, ""}:
        outcome = "ambiguous_eligibility"
        reasons.append(f"section_outcome:{section_outcome or 'missing'}")
    elif duplicate_group_id and duplicate_rank > 0:
        outcome = "duplicate_row"
        reasons.append("later_exact_duplicate_retained_without_mapping")
    elif not label and not values_present:
        outcome = "unsupported"
        reasons.append("row_has_no_label_or_value")
    elif row_type in {"heading", "section_heading"}:
        outcome = "heading_only"
        reasons.append(f"source_row_type:{row_type}")
    elif row_type in {"table_header", "header"} or HEADER_RE.fullmatch(normalized):
        outcome = "table_header"
        reasons.append("table_header_signal")
    elif row_type in {"text_block", "narrative", "narrative_row"}:
        outcome = "narrative_row"
        reasons.append(f"source_row_type:{row_type}")
    elif row_type == "continuation_label":
        outcome = "continuation_label"
        reasons.append("continuation_label_signal")
    elif not values_present:
        outcome = "empty_value"
        reasons.append("no_usable_current_or_prior_value")
    elif row_type in {"subtotal", "subtotal_or_total"} and TOTAL_RE.search(label):
        outcome = "total_candidate"
        reasons.append("total_label_and_numeric_value")
    elif row_type in {"subtotal", "subtotal_or_total"} or SUBTOTAL_RE.search(label):
        outcome = "subtotal_candidate"
        reasons.append("subtotal_label_or_source_type")
    elif TOTAL_RE.search(label):
        outcome = "total_candidate"
        reasons.append("total_label_and_numeric_value")
    elif row_type in {"metadata", "structural", "structural_only"}:
        outcome = "structural_only"
        reasons.append(f"source_row_type:{row_type}")
    elif row_type not in {
        "numeric_fact",
        "comparative_numeric_fact",
        "fact",
        "unknown",
        "",
    }:
        outcome = "unsupported"
        reasons.append(f"unsupported_source_row_type:{row_type}")
    else:
        outcome = "fact_candidate"
        reasons.append("fact_like_label_and_usable_value")

    competitors = sorted(set(str(item) for item in competing_source_row_ids or [] if str(item) != source_row_id))
    if duplicate_group_id:
        reasons.append(f"duplicate_group:{duplicate_group_id}")
    if competitors:
        reasons.append("competing_source_rows_present")
    return RowMappingEligibility(
        source_row_id=source_row_id,
        outcome=outcome,
        eligible=outcome in ELIGIBLE_OUTCOMES,
        reasons=reasons,
        duplicate_group_id=duplicate_group_id,
        competing_source_row_ids=competitors,
        requires_human_review=True,
    )
