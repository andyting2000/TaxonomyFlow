"""Template-constrained deterministic Top-K taxonomy retrieval for #19C."""

from __future__ import annotations

from difflib import SequenceMatcher
import math
import re
from typing import Any, Iterable, Mapping, Sequence

from schemas import (
    CandidateScoreBreakdown,
    RowMappingEligibility,
    SectionAwareCandidateSet,
    SectionAwareTaxonomyCandidate,
    TaxonomyConceptCard,
)
from services.section_aware_taxonomy_concept_cards import (
    cards_for_template_groups,
    normalize_concept_label,
)


RETRIEVAL_VERSION = "19C-section-aware-retrieval-v2"
HARD_MAX_CANDIDATES = 20
NUMERIC_RE = re.compile(r"^\s*\(?[-+]?\s*(?:[A-Z]{3}|RM|MYR|\$)?\s*[\d,]+(?:\.\d+)?\)?\s*%?\s*$", re.I)
PRESENTATION_PREFIX_RE = re.compile(r"^\s*(add|less)\b\s*:?[\s-]*", re.I)
EVIDENCE_NOISE_TOKENS = {"DISCUSSION", "DRAFT", "WIE"}


class CandidateRetrievalRowError(ValueError):
    """A bounded failure caused by one row's retrieval/scoring shape."""

    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code


class CandidateRetrievalSystemError(ValueError):
    """A retrieval-index/inventory defect that is unsafe to isolate per row."""

    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code


def semantic_source_label(value: Any) -> tuple[str, list[str]]:
    """Build a scoring-only label while retaining an auditable cleanup trail."""

    raw = str(value or "").strip()
    working = raw
    reasons: list[str] = []
    prefix = PRESENTATION_PREFIX_RE.match(working)
    if prefix and working[prefix.end():].strip():
        reasons.append(f"removed_presentation_prefix:{prefix.group(1).lower()}")
        working = working[prefix.end():].strip()
    parts = working.split()
    while parts and parts[-1] in EVIDENCE_NOISE_TOKENS:
        token = parts.pop()
        reasons.append(f"removed_trailing_evidence_noise:{token}")
    normalized = normalize_concept_label(" ".join(parts))
    normalized = re.sub(r"\bnon\s+current\b", "noncurrent", normalized)
    return normalized, sorted(reasons)


def _semantic_normalize(value: Any) -> str:
    normalized = normalize_concept_label(value)
    return re.sub(r"\bnon\s+current\b", "noncurrent", normalized)


def _tokens(value: Any) -> set[str]:
    return set(_semantic_normalize(value).split())


def _token_similarity(left: Any, right: Any) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _lexical_similarity(left: Any, right: Any) -> float:
    normalized_left = _semantic_normalize(left)
    normalized_right = _semantic_normalize(right)
    if not normalized_left or not normalized_right:
        return 0.0
    if normalized_left == normalized_right:
        return 1.0
    sequence = SequenceMatcher(None, normalized_left, normalized_right).ratio()
    return max(sequence, _token_similarity(normalized_left, normalized_right))


def _expected_period_type(row: Mapping[str, Any], statement_families: Sequence[str]) -> str | None:
    label, _ = semantic_source_label(row.get("label") or row.get("extracted_label"))
    families = set(statement_families)
    if "financial_position" in families:
        return "instant"
    if families.intersection({"profit_or_loss", "comprehensive_income"}):
        return "duration"
    if "cash_flows" in families:
        if any(phrase in label for phrase in ("at beginning", "at end", "beginning of", "end of", "closing balance", "opening balance")):
            return "instant"
        return "duration"
    if "changes_in_equity" in families:
        return "instant" if "balance" in label else "duration"
    return None


def _is_numeric_row(row: Mapping[str, Any]) -> bool:
    values = [
        row.get("current_value", row.get("value")),
        row.get("prior_value", row.get("previous_value")),
    ]
    return any(value not in (None, "") and NUMERIC_RE.match(str(value)) for value in values)


def _datatype_compatible(row: Mapping[str, Any], card: TaxonomyConceptCard) -> bool:
    datatype = str(card.datatype or "").lower()
    substitution_group = str(card.substitution_group or "").lower()
    if (
        any(token in datatype for token in ("domainitem", "hypercubeitem"))
        or any(token in substitution_group for token in ("dimensionitem", "hypercubeitem"))
        or card.local_name.endswith(("Axis", "Member", "Table", "LineItems"))
    ):
        return False
    if not _is_numeric_row(row):
        return True
    return not any(token in datatype for token in ("textblock", "stringitem", "boolean", "dateitem"))


def _best_label_score(row_label: str, card: TaxonomyConceptCard) -> tuple[float, str]:
    variants = [
        card.standard_label,
        card.terse_label,
        card.verbose_label,
        card.local_name,
    ]
    scored = [(_lexical_similarity(row_label, value), str(value)) for value in variants if value]
    return max(scored, default=(0.0, ""), key=lambda item: (item[0], item[1]))


def _alias_score(row_label: str, card: TaxonomyConceptCard) -> tuple[float, str | None]:
    normalized = _semantic_normalize(row_label)
    exact = [alias for alias in card.aliases if _semantic_normalize(alias) == normalized]
    if exact:
        return 1.0, sorted(exact)[0]
    scored = [(_lexical_similarity(normalized, alias), alias) for alias in card.aliases]
    best = max(scored, default=(0.0, None), key=lambda item: (item[0], str(item[1])))
    return best


def _semantic_profile(value: Any) -> set[str]:
    text = _semantic_normalize(value)
    compact = re.sub(r"[^a-z0-9]", "", text)
    profile: set[str] = set()
    markers = {
        "asset": ("asset",),
        "liability": ("liabilit",),
        "equity": ("equity", "shareholder"),
        "receivable": ("receivab",),
        "payable": ("payab", "accrual", "due to"),
        "reserve": ("reserve",),
        "inventory": ("inventor",),
        "investment": ("invest",),
        "provision": ("provision",),
        "tax": (" tax", "tax ", "taxation", "incometax", "currenttax", "deferredtax"),
        "expense": ("expense", " cost", "cost "),
        "revenue": ("revenue", "turnover", " sales"),
        "cash": ("cash", "bank balance"),
        "capital": ("capital",),
        "retained": ("retained", "accumulated loss"),
        "total": ("total", "subtotal"),
    }
    padded = f" {text} "
    for family, values in markers.items():
        if any(value in padded or value.replace(" ", "") in compact for value in values):
            profile.add(family)
    if "cost of sales" in text or "costofsales" in compact:
        profile.discard("revenue")
    if "noncurrent" in compact:
        profile.add("noncurrent")
    elif "current" in text or "current" in compact:
        profile.add("current")
    if "other comprehensive income" in text or "othercomprehensiveincome" in compact:
        profile.add("oci")
    if "comprehensive income" in text or "comprehensiveincome" in compact:
        profile.add("comprehensive")
    if "profit" in text or "loss" in text:
        profile.add("profit")
        if "comprehensive" not in profile:
            profile.add("ordinary_profit")
    if ("other income" in text or profile.intersection({"revenue"})) and "comprehensive" not in profile:
        profile.add("ordinary_income")
    return profile


def _target_families(label: str, statement_families: Sequence[str]) -> list[str]:
    text = _semantic_normalize(label)
    targets: list[str] = []
    if "comprehensive" in text:
        targets.append("comprehensive_income")
    elif "cost of sales" in text:
        targets.append("cost_of_sales")
    elif "gross profit" in text:
        targets.append("gross_profit")
    elif ("staff" in text or "employee" in text) and ("cost" in text or "expense" in text):
        targets.append("employee_expense")
    elif "operating" in text and ("cost" in text or "expense" in text):
        targets.append("operating_expense")
    elif "operating" in text and ("profit" in text or "loss" in text):
        targets.append("operating_profit")
    elif ("profit" in text or "loss" in text) and ("before tax" in text or "before taxation" in text):
        targets.append("profit_before_tax")
    elif "tax" in text or "taxation" in text:
        targets.append("tax_position" if "financial_position" in statement_families else "tax_expense")
    elif "turnover" in text or "revenue" in text or text == "sales":
        targets.append("revenue")
    elif "other income" in text:
        targets.append("ordinary_income")
    elif "receiv" in text:
        targets.append("receivable")
    elif "payab" in text or "accrual" in text or "due to" in text:
        targets.append("payable")
    elif "current assets" in text:
        targets.append("current_assets")
    elif "current liabilities" in text:
        targets.append("current_liabilities")
    elif "equity and liabilities" in text:
        targets.append("equity_and_liabilities")
    elif "shareholder" in text and "equity" in text:
        targets.append("equity_total")
    elif "total assets" in text:
        targets.append("assets_total")
    elif "cash" in text or "bank" in text:
        targets.append("cash")
    elif "capital" in text:
        targets.append("capital")
    elif "retained" in text or "accumulated loss" in text:
        targets.append("retained_earnings")
    return targets


def _card_semantic_text(card: TaxonomyConceptCard, *, include_hierarchy: bool = False) -> str:
    values = [card.qname, card.local_name, card.standard_label, *card.aliases]
    if include_hierarchy:
        values.extend(card.parent_concepts)
        values.extend(card.concept_path)
    return _semantic_normalize(" ".join(values))


def _card_supports_target(card: TaxonomyConceptCard, target: str) -> bool:
    text = _card_semantic_text(card)
    compact = re.sub(r"[^a-z0-9]", "", text)
    profile = _semantic_profile(text)
    exact_local = _semantic_normalize(card.local_name)
    if target == "comprehensive_income":
        return exact_local == "comprehensive income"
    if target == "cost_of_sales":
        return "cost of sales" in text or "costofsales" in compact
    if target == "gross_profit":
        return "gross profit" in text or "grossprofit" in compact
    if target == "employee_expense":
        return ("employee" in text or "staff" in text) and "expense" in profile
    if target == "operating_expense":
        return "operating" in text and "expense" in profile and "comprehensive" not in profile
    if target == "operating_profit":
        return "operating" in text and "ordinary_profit" in profile
    if target == "profit_before_tax":
        return "before tax" in text and "ordinary_profit" in profile
    if target == "tax_expense":
        return "tax" in profile and "expense" in profile and "comprehensive" not in profile
    if target == "tax_position":
        return "tax" in profile and bool(profile.intersection({"asset", "liability"}))
    if target == "revenue":
        return "revenue" in profile
    if target == "ordinary_income":
        return "ordinary_income" in profile
    if target in {"receivable", "payable"}:
        return target in profile and "tax" not in profile
    if target in {"cash", "capital"}:
        return target in profile
    if target == "current_assets":
        return exact_local == "current assets"
    if target == "current_liabilities":
        return exact_local == "current liabilities"
    if target == "equity_and_liabilities":
        return exact_local == "equity and liabilities"
    if target == "equity_total":
        return "equity" in profile and "total" in profile
    if target == "assets_total":
        return exact_local == "assets"
    if target == "retained_earnings":
        return "retained" in profile
    return False


def _context_profile(parent_label: str | None, sibling_labels: Sequence[str]) -> set[str]:
    profile = _semantic_profile(parent_label or "")
    sibling_profiles = [_semantic_profile(label) for label in sibling_labels]
    position_signals = {
        family
        for family in ("asset", "liability", "equity")
        if any(family in item and "total" in item for item in sibling_profiles)
    }
    current_signals = {
        family
        for family in ("current", "noncurrent")
        if any(family in item and "total" in item for item in sibling_profiles)
    }
    if len(position_signals) == 1:
        profile.update(position_signals)
    if len(current_signals) == 1:
        profile.update(current_signals)
    return profile


def _semantic_match_score(source_profile: set[str], candidate_profile: set[str], supported_target: bool) -> float:
    if supported_target:
        return 1.0
    relevant = source_profile.intersection(
        {
            "asset", "liability", "equity", "receivable", "payable", "reserve",
            "inventory", "investment", "provision", "tax", "expense", "revenue",
            "ordinary_income", "ordinary_profit", "comprehensive", "oci", "cash",
            "capital", "retained", "current", "noncurrent", "total",
        }
    )
    if not relevant:
        return 0.0
    return len(relevant.intersection(candidate_profile)) / len(relevant)


def _semantic_contrast_penalty(
    source_profile: set[str],
    candidate_profile: set[str],
    targets: Sequence[str],
) -> tuple[float, list[str]]:
    penalties: list[tuple[str, float]] = []
    pairs = (
        ("current", "noncurrent", 0.32),
        ("noncurrent", "current", 0.32),
        ("asset", "liability", 0.28),
        ("liability", "asset", 0.28),
        ("receivable", "payable", 0.34),
        ("payable", "receivable", 0.34),
        ("receivable", "reserve", 0.34),
        ("payable", "reserve", 0.34),
        ("reserve", "receivable", 0.30),
        ("reserve", "payable", 0.30),
        ("ordinary_income", "expense", 0.30),
        ("expense", "ordinary_income", 0.30),
    )
    for source, candidate, amount in pairs:
        if source in source_profile and candidate in candidate_profile:
            penalties.append((f"semantic_contrast:{source}!={candidate}", amount))
    if source_profile.intersection({"ordinary_income", "ordinary_profit"}) and "oci" in candidate_profile:
        penalties.append(("semantic_contrast:ordinary_income_or_profit!=oci", 0.40))
    if "comprehensive_income" in targets:
        if "ordinary_profit" in candidate_profile:
            penalties.append(("semantic_contrast:comprehensive_income!=ordinary_profit", 0.28))
        if "oci" in candidate_profile:
            penalties.append(("semantic_contrast:total_comprehensive_income!=oci_component", 0.20))
    if "tax_expense" in targets and candidate_profile.intersection({"asset", "liability"}):
        penalties.append(("semantic_contrast:tax_expense!=tax_position", 0.36))
    if "tax_position" in targets:
        if "liability" in source_profile and "asset" in candidate_profile:
            penalties.append(("semantic_contrast:tax_liability!=tax_asset", 0.34))
        if "asset" in source_profile and "liability" in candidate_profile:
            penalties.append(("semantic_contrast:tax_asset!=tax_liability", 0.34))
    if set(targets).intersection({"receivable", "payable"}) and "tax" in candidate_profile:
        penalties.append(("semantic_contrast:general_balance!=tax_specific_balance", 0.20))
    amount = min(0.65, sum(value for _, value in penalties))
    return amount, [reason for reason, _ in penalties]


def score_taxonomy_candidate(
    *,
    row: Mapping[str, Any],
    card: TaxonomyConceptCard,
    template_group_ids: Sequence[str],
    statement_families: Sequence[str],
    sibling_labels: Sequence[str] = (),
    parent_label: str | None = None,
    normalized_semantic_label: str | None = None,
    semantic_target_families: Sequence[str] = (),
    semantic_scope_limitations: Sequence[str] = (),
    concept_labels_by_qname: Mapping[str, str] | None = None,
) -> tuple[CandidateScoreBreakdown | None, str | None]:
    if not set(template_group_ids).intersection(card.template_group_ids):
        return None, "template_group_incompatible"
    if card.abstract:
        return None, "abstract_concept_not_selectable_for_fact"
    if not _datatype_compatible(row, card):
        return None, "datatype_incompatible_with_numeric_row"

    expected_period = _expected_period_type(row, statement_families)
    if expected_period and card.period_type and card.period_type != expected_period:
        return None, f"period_type_incompatible:{expected_period}!={card.period_type}"

    raw_label = str(row.get("label") or row.get("extracted_label") or "")
    label = normalized_semantic_label or semantic_source_label(raw_label)[0]
    targets = list(semantic_target_families) or _target_families(label, statement_families)
    lexical, matched_label = _best_label_score(label, card)
    alias, matched_alias = _alias_score(label, card)
    documentation = _lexical_similarity(label, card.documentation) if card.documentation else 0.0
    reasons = [
        "candidate_membership_is_within_classified_template_groups",
        f"best_label_similarity:{lexical:.4f}:{matched_label}",
    ]
    if matched_alias:
        reasons.append(f"best_alias_similarity:{alias:.4f}:{matched_alias}")

    exclusion_hits = sorted(
        indicator
        for indicator in card.exclusion_indicators
        if _semantic_normalize(indicator) in _semantic_normalize(label)
    )
    positive_hits = sorted(
        indicator
        for indicator in card.positive_indicators
        if _semantic_normalize(indicator) in _semantic_normalize(label)
    )
    labels_by_qname = dict(concept_labels_by_qname or {})
    parent_concept_labels = [
        labels_by_qname.get(parent) or parent.split(":", 1)[-1]
        for parent in card.parent_concepts
    ]
    sibling_similarity = max(
        (
            _lexical_similarity(sibling, concept_parent)
            for sibling in sibling_labels
            for concept_parent in parent_concept_labels
        ),
        default=0.0,
    )
    hierarchy_similarity = (
        max(
            (_lexical_similarity(parent_label, concept_parent) for concept_parent in parent_concept_labels),
            default=0.0,
        )
        if parent_label
        else 0.0
    )
    source_profile = _semantic_profile(label)
    context_profile = _context_profile(parent_label, sibling_labels)
    effective_source_profile = source_profile.union(context_profile)
    candidate_profile = _semantic_profile(_card_semantic_text(card, include_hierarchy=True))
    supported_target = bool(targets) and all(_card_supports_target(card, target) for target in targets)
    semantic_match = _semantic_match_score(effective_source_profile, candidate_profile, supported_target)
    semantic_penalty, semantic_reasons = _semantic_contrast_penalty(
        effective_source_profile,
        candidate_profile,
        targets,
    )
    total_signal = 1.0 if "total" in source_profile and "total" in candidate_profile else 0.0
    section_compatible = bool(set(statement_families).intersection(card.statement_family)) or not card.statement_family
    exclusion_penalty = min(0.25, 0.08 * len(exclusion_hits))
    scope_limitation_penalty = 0.30 if semantic_scope_limitations else 0.0
    if exclusion_hits:
        reasons.append("exclusion_indicators:" + ",".join(exclusion_hits))
    if positive_hits:
        reasons.append("positive_indicators:" + ",".join(positive_hits))
    if expected_period:
        reasons.append(f"period_type_compatible:{expected_period}")
    if targets:
        reasons.append("semantic_target_families:" + ",".join(sorted(targets)))
    if supported_target:
        reasons.append("candidate_exactly_supports_semantic_target")
    if context_profile:
        reasons.append("reliable_hierarchy_context:" + ",".join(sorted(context_profile)))
    reasons.extend(semantic_reasons)
    if semantic_scope_limitations:
        reasons.append(
            "semantic_family_absent_from_template_scope:"
            + ",".join(sorted(semantic_scope_limitations))
        )

    components = {
        "lexical_score": 0.26 * lexical,
        "alias_score": 0.16 * alias,
        "documentation_score": 0.02 * documentation,
        "semantic_phrase_score": 0.20 * semantic_match,
        "section_compatibility_score": 0.06 if section_compatible else 0.0,
        "template_group_score": 0.13,
        "datatype_score": 0.04,
        "period_type_score": 0.04 if expected_period and card.period_type == expected_period else 0.02,
        "balance_score": 0.0,
        "hierarchy_score": 0.03 * hierarchy_similarity,
        "sibling_context_score": 0.03 * sibling_similarity,
        "value_shape_score": 0.03 if _is_numeric_row(row) else 0.01,
        "total_subtotal_score": 0.03 * total_signal,
        "exclusion_penalty": exclusion_penalty,
        "abstract_penalty": 0.0,
        "semantic_contrast_penalty": semantic_penalty,
        "scope_limitation_penalty": scope_limitation_penalty,
    }
    total = sum(value for key, value in components.items() if not key.endswith("penalty"))
    total -= sum(value for key, value in components.items() if key.endswith("penalty"))
    total = round(max(0.0, min(1.0, total)), 6)
    reasons.append("score_is_a_deterministic_rank_not_a_correctness_probability")
    return CandidateScoreBreakdown(**components, total_score=total, reasons=reasons), None


def audit_section_aware_candidate_scope(
    *,
    row: Mapping[str, Any],
    row_eligibility: RowMappingEligibility,
    section_id: str | None,
    subsection_id: str | None,
    template_group_ids: Sequence[str],
    statement_families: Sequence[str],
    inventory_cards: Iterable[TaxonomyConceptCard],
    concept_inventory_hash: str,
    min_candidate_score: float = 0.0,
    sibling_labels: Sequence[str] = (),
    parent_label: str | None = None,
) -> dict[str, Any]:
    """Return the complete deterministic scope, including excluded concepts."""

    cards = list(inventory_cards)
    allowed_cards = cards_for_template_groups(template_group_ids, cards=cards)
    semantic_label, normalization_reasons = semantic_source_label(
        row.get("label") or row.get("extracted_label")
    )
    targets = _target_families(semantic_label, statement_families)
    limitations = sorted(
        target
        for target in targets
        if not any(_card_supports_target(card, target) for card in allowed_cards)
    )
    labels_by_qname = {card.qname: card.standard_label for card in cards}
    threshold = max(0.0, min(1.0, float(min_candidate_score)))
    scored: list[tuple[TaxonomyConceptCard, CandidateScoreBreakdown]] = []
    excluded: list[tuple[TaxonomyConceptCard, str]] = []
    for card in allowed_cards:
        try:
            breakdown, exclusion_reason = score_taxonomy_candidate(
                row=row,
                card=card,
                template_group_ids=template_group_ids,
                statement_families=statement_families,
                sibling_labels=sibling_labels,
                parent_label=parent_label,
                normalized_semantic_label=semantic_label,
                semantic_target_families=targets,
                semantic_scope_limitations=limitations,
                concept_labels_by_qname=labels_by_qname,
            )
        except CandidateRetrievalRowError:
            raise
        except Exception as exc:
            raise CandidateRetrievalRowError(
                "candidate_scoring_failed",
                "Candidate scoring failed for this row.",
            ) from exc
        if exclusion_reason:
            excluded.append((card, exclusion_reason))
            continue
        if breakdown is None or not math.isfinite(float(breakdown.total_score)):
            raise CandidateRetrievalRowError(
                "candidate_scoring_failed",
                "Candidate scoring produced an invalid result.",
            )
        if breakdown.total_score >= threshold:
            scored.append((card, breakdown))
        else:
            excluded.append((card, f"below_min_candidate_score:{threshold:.6f}"))
    try:
        scored.sort(key=lambda item: (-item[1].total_score, item[0].qname))
        excluded.sort(key=lambda item: item[0].qname)
    except Exception as exc:
        raise CandidateRetrievalRowError(
            "candidate_sort_failed",
            "Candidate ordering failed for this row.",
        ) from exc
    candidate_records: list[dict[str, Any]] = []
    for rank, (card, breakdown) in enumerate(scored, start=1):
        candidate_records.append(
            {
                "rank": rank,
                "qname": card.qname,
                "selectable": True,
                "concept_card": card.model_dump(mode="json"),
                "score": breakdown.model_dump(mode="json"),
                "exclusion_reason": None,
            }
        )
    for card, exclusion_reason in excluded:
        candidate_records.append(
            {
                "rank": None,
                "qname": card.qname,
                "selectable": False,
                "concept_card": card.model_dump(mode="json"),
                "score": None,
                "exclusion_reason": exclusion_reason,
            }
        )
    return {
        "source_row_id": row_eligibility.source_row_id,
        "raw_label": str(row.get("label") or row.get("extracted_label") or ""),
        "semantic_source_label": semantic_label,
        "semantic_normalization_reasons": normalization_reasons,
        "semantic_target_families": targets,
        "semantic_scope_limitations": limitations,
        "section_id": section_id,
        "subsection_id": subsection_id,
        "template_group_ids": sorted(set(template_group_ids)),
        "statement_families": sorted(set(statement_families)),
        "candidate_count_before_filter": len(allowed_cards),
        "candidate_count_after_filter": len(scored),
        "concept_inventory_hash": concept_inventory_hash,
        "retrieval_version": RETRIEVAL_VERSION,
        "candidate_records": candidate_records,
    }


def retrieve_section_aware_candidates(
    *,
    row: Mapping[str, Any],
    row_eligibility: RowMappingEligibility,
    section_id: str | None,
    subsection_id: str | None,
    template_group_ids: Sequence[str],
    statement_families: Sequence[str],
    inventory_cards: Iterable[TaxonomyConceptCard],
    concept_inventory_hash: str,
    max_candidates: int = 8,
    min_candidate_score: float = 0.0,
    sibling_labels: Sequence[str] = (),
    parent_label: str | None = None,
) -> SectionAwareCandidateSet:
    top_k = min(HARD_MAX_CANDIDATES, max(1, int(max_candidates)))
    warnings: list[str] = []
    normalized_label, normalization_reasons = semantic_source_label(
        row.get("label") or row.get("extracted_label")
    )
    targets = _target_families(normalized_label, statement_families)
    if not row_eligibility.eligible:
        return SectionAwareCandidateSet(
            source_row_id=row_eligibility.source_row_id,
            section_id=section_id,
            subsection_id=subsection_id,
            template_group_ids=sorted(set(template_group_ids)),
            row_eligibility=row_eligibility,
            candidate_outcome="row_not_eligible",
            top_k=top_k,
            semantic_source_label=normalized_label,
            semantic_normalization_reasons=normalization_reasons,
            semantic_target_families=targets,
            retrieval_version=RETRIEVAL_VERSION,
            concept_inventory_hash=concept_inventory_hash,
            warnings=[f"row_eligibility:{row_eligibility.outcome}"],
        )
    if not template_group_ids:
        return SectionAwareCandidateSet(
            source_row_id=row_eligibility.source_row_id,
            section_id=section_id,
            subsection_id=subsection_id,
            template_group_ids=[],
            row_eligibility=row_eligibility,
            candidate_outcome="no_safe_candidate",
            top_k=top_k,
            semantic_source_label=normalized_label,
            semantic_normalization_reasons=normalization_reasons,
            semantic_target_families=targets,
            retrieval_version=RETRIEVAL_VERSION,
            concept_inventory_hash=concept_inventory_hash,
            warnings=["no_classified_template_group"],
        )

    try:
        audit = audit_section_aware_candidate_scope(
            row=row,
            row_eligibility=row_eligibility,
            section_id=section_id,
            subsection_id=subsection_id,
            template_group_ids=template_group_ids,
            statement_families=statement_families,
            inventory_cards=inventory_cards,
            concept_inventory_hash=concept_inventory_hash,
            min_candidate_score=min_candidate_score,
            sibling_labels=sibling_labels,
            parent_label=parent_label,
        )
    except CandidateRetrievalRowError:
        raise
    except ValueError as exc:
        if "Unknown or non-mapping template groups" not in str(exc):
            raise CandidateRetrievalSystemError(
                "candidate_card_invalid",
                "The local candidate inventory is invalid.",
            ) from exc
        return SectionAwareCandidateSet(
            source_row_id=row_eligibility.source_row_id,
            section_id=section_id,
            subsection_id=subsection_id,
            template_group_ids=sorted(set(template_group_ids)),
            row_eligibility=row_eligibility,
            candidate_outcome="no_safe_candidate",
            top_k=top_k,
            semantic_source_label=normalized_label,
            semantic_normalization_reasons=normalization_reasons,
            semantic_target_families=targets,
            retrieval_version=RETRIEVAL_VERSION,
            concept_inventory_hash=concept_inventory_hash,
            requires_human_review=True,
            warnings=["unknown_canonical_template_group", "empty_candidate_scope"],
        )
    except Exception as exc:
        raise CandidateRetrievalSystemError(
            "candidate_card_invalid",
            "The local candidate inventory is invalid.",
        ) from exc
    excluded_reasons: dict[str, int] = {}
    candidate_records = list(audit["candidate_records"])
    selected_records = [record for record in candidate_records if record["selectable"]][:top_k]
    candidates = []
    for rank, record in enumerate(selected_records, start=1):
        card = TaxonomyConceptCard.model_validate(record["concept_card"])
        breakdown = CandidateScoreBreakdown.model_validate(record["score"])
        candidates.append(
            SectionAwareTaxonomyCandidate(
                rank=rank,
                concept_id=card.concept_id,
                qname=card.qname,
                selectable=True,
                concept_card=card,
                score=breakdown,
            )
        )
    for record in candidate_records:
        excluded = record.get("exclusion_reason")
        if excluded:
            excluded_reasons[excluded] = excluded_reasons.get(excluded, 0) + 1
    if excluded_reasons:
        warnings.extend(
            f"excluded:{reason}:{count}" for reason, count in sorted(excluded_reasons.items())
        )
    limitations = list(audit["semantic_scope_limitations"])
    warnings.extend(
        f"semantic_family_absent_from_template_scope:{family}"
        for family in limitations
    )
    return SectionAwareCandidateSet(
        source_row_id=row_eligibility.source_row_id,
        section_id=section_id,
        subsection_id=subsection_id,
        template_group_ids=sorted(set(template_group_ids)),
        row_eligibility=row_eligibility,
        candidate_outcome="candidates_available" if candidates else "no_safe_candidate",
        candidate_count_before_filter=int(audit["candidate_count_before_filter"]),
        candidate_count_after_filter=int(audit["candidate_count_after_filter"]),
        top_k=top_k,
        candidates=candidates,
        semantic_source_label=str(audit["semantic_source_label"]),
        semantic_normalization_reasons=list(audit["semantic_normalization_reasons"]),
        semantic_target_families=list(audit["semantic_target_families"]),
        semantic_scope_limitations=limitations,
        retrieval_version=RETRIEVAL_VERSION,
        concept_inventory_hash=concept_inventory_hash,
        requires_human_review=True,
        warnings=warnings,
    )
