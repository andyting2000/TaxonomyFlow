"""Targeted concept metadata enrichment v2 for Azure DI mapping blockers."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from services.azure_di_concept_metadata_enricher import (
    build_enriched_concept_metadata,
    clean_text,
    infer_statement_family,
    normalize_text,
    token_set,
)


NUMERIC_ROW_TYPES = {"numeric_fact", "comparative_numeric_fact", "subtotal_or_total"}


CURATED_ALIAS_GROUPS_V2: list[dict[str, Any]] = [
    {
        "group": "ppe_abbreviations_v2",
        "aliases": ["PPE", "property plant equipment", "property, plant and equipment", "property plant and equipment"],
        "target_local_names": ["PropertyPlantAndEquipment"],
        "target_label_patterns": ["property plant equipment", "property plant and equipment"],
        "statement_family": "financial_position",
        "expected_type": "numeric",
    },
    {
        "group": "cash_and_bank_balances_v2",
        "aliases": [
            "cash and bank balances",
            "cash at bank",
            "cash in hand and at bank",
            "bank balances",
            "cash and cash equivalents at end of year",
            "cash and cash equivalents at end of period",
        ],
        "target_local_names": ["CashAndBankBalances", "CashAndCashEquivalents"],
        "target_label_patterns": ["cash and cash equivalents", "cash and bank balances"],
        "statement_family": "cash_flows",
        "expected_type": "numeric",
    },
    {
        "group": "receivables_plural_v2",
        "aliases": [
            "other receivable",
            "other receivables",
            "trade receivable",
            "trade receivables",
            "decrease in receivable",
            "decrease in receivables",
            "receivable",
            "receivables",
        ],
        "target_local_names": ["TradeAndOtherCurrentReceivables", "OtherCurrentReceivables", "CurrentTradeReceivables"],
        "target_label_patterns": ["current receivables", "trade and other current receivables", "other current receivables"],
        "statement_family": "financial_position",
        "expected_type": "numeric",
    },
    {
        "group": "payables_plural_v2",
        "aliases": [
            "other payable",
            "other payables",
            "trade payable",
            "trade payables",
            "decrease in payable",
            "decrease in payables",
            "payable",
            "payables",
        ],
        "target_local_names": ["TradeAndOtherCurrentPayables", "OtherCurrentPayables", "CurrentTradePayables"],
        "target_label_patterns": ["current payables", "trade and other current payables", "other current payables"],
        "statement_family": "financial_position",
        "expected_type": "numeric",
    },
    {
        "group": "director_account_v2",
        "aliases": [
            "amount due to director",
            "amount due to directors",
            "amount owing to director",
            "amount owing to directors",
            "increase in director's account",
            "director's account",
            "directors account",
        ],
        "target_local_names": [
            "OtherCurrentPayablesDueToDirectors",
            "OtherCurrentReceivablesDueFromDirectors",
            "CurrentPayablesDueToDirectors",
            "CurrentReceivablesDueFromDirectors",
        ],
        "target_label_patterns": ["due to directors", "due from directors", "directors"],
        "statement_family": "financial_position",
        "expected_type": "numeric",
    },
    {
        "group": "bank_overdraft_unsecured_v2",
        "aliases": ["bank overdraft unsecured", "bank overdraft - unsecured", "bank overdraft -unsecured", "unsecured bank overdraft"],
        "target_local_names": ["UnsecuredBankOverdrafts", "CurrentPortionOfNoncurrentUnsecuredBankOverdrafts", "BankOverdraftsClassifiedAsCashEquivalents"],
        "target_label_patterns": ["unsecured bank overdrafts", "bank overdrafts"],
        "statement_family": "financial_position",
        "expected_type": "numeric",
    },
    {
        "group": "administrative_expenses_v2",
        "aliases": ["administration expenses", "administrative expenses", "admin expenses"],
        "target_local_names": ["AdministrativeExpense"],
        "target_label_patterns": ["administrative expenses"],
        "statement_family": "comprehensive_income",
        "expected_type": "numeric",
    },
    {
        "group": "profit_loss_v2",
        "aliases": [
            "loss before tax",
            "profit before tax",
            "loss after tax",
            "profit after tax",
            "loss for the financial year",
            "profit for the financial year",
            "loss after tax and representing total comprehensive loss for the year",
            "loss attributable to owners of the company",
        ],
        "target_local_names": ["ProfitLossBeforeTax", "ProfitLoss", "ProfitLossAttributableToOwnersOfParent", "ComprehensiveIncome"],
        "target_label_patterns": ["profit loss before tax", "total profit loss", "attributable to owners", "comprehensive income"],
        "statement_family": "comprehensive_income",
        "expected_type": "numeric",
    },
    {
        "group": "tax_expense_v2",
        "aliases": ["tax expense", "income tax expense", "taxation", "tax charge"],
        "target_local_names": ["IncomeTaxExpenseContinuingOperations"],
        "target_label_patterns": ["tax expense"],
        "statement_family": "comprehensive_income",
        "expected_type": "numeric",
    },
    {
        "group": "share_capital_v2",
        "aliases": ["contributed share capital", "ordinary shares", "ordinary shares issued", "no par value"],
        "target_local_names": ["CapitalFromOrdinaryShares"],
        "target_label_patterns": ["capital from ordinary shares"],
        "statement_family": "financial_position",
        "expected_type": "numeric",
    },
    {
        "group": "depreciation_abbreviations_v2",
        "aliases": ["depn", "deprn", "depreciation", "depreciation expense", "accumulated depreciation"],
        "target_local_names": ["DepreciationPropertyPlantAndEquipment", "DepreciationAndAmortisationExpense", "AdjustmentsForDepreciationExpense"],
        "target_label_patterns": ["depreciation"],
        "statement_family": "comprehensive_income",
        "expected_type": "numeric",
    },
    {
        "group": "amortisation_spelling_v2",
        "aliases": ["amortisation", "amortization", "amort.", "amortisation expense", "amortization expense"],
        "target_local_names": ["AmortisationExpense", "DepreciationAndAmortisationExpense", "AdjustmentsForAmortisationExpense"],
        "target_label_patterns": ["amortisation", "amortization"],
        "statement_family": "comprehensive_income",
        "expected_type": "numeric",
    },
    {
        "group": "directors_report_text_v2",
        "aliases": [
            "directors report",
            "director's report",
            "directors hereby submit their report",
            "all material transfers to or from reserves and provisions",
            "since the end of the previous financial year no director",
            "neither during nor at the end of the financial year",
            "no dividend was paid since the end of the previous financial year",
            "no indemnity given to or insurance effected for directors",
            "this report was approved by the board of directors",
        ],
        "target_local_names": ["DisclosureOfDirectorsReportExplanatory"],
        "target_label_patterns": ["director report text block"],
        "statement_family": "directors_report",
        "expected_type": "text_block",
    },
    {
        "group": "statement_by_directors_text_v2",
        "aliases": ["statement by directors", "pursuant to section 251", "section 251(2) of the companies act"],
        "target_local_names": ["DisclosureOfStatementByDirectorsExplanatory", "DisclosureOfStatementByDirectorsForBusinessReviewExplanatory"],
        "target_label_patterns": ["statement by directors"],
        "statement_family": "statement_by_directors",
        "expected_type": "text_block",
    },
    {
        "group": "accounting_policies_text_v2",
        "aliases": [
            "significant accounting policies",
            "basis of preparation",
            "financial statements have been prepared in compliance",
            "prepared using the historical cost convention",
            "financial instruments",
            "subsequent measurement financial assets",
            "short-term other receivable",
            "transaction costs of an equity transaction",
        ],
        "target_local_names": [
            "DisclosureOfSignificantAccountingPoliciesExplanatory",
            "DisclosureOfBasisOfPreparationOfFinancialStatementsExplanatory",
            "DescriptionOfAccountingPolicyForOtherFinancialLiabilitiesExplanatory",
            "DisclosureOfFinancialInstrumentsMeasuredAtAmortisedCostExplanatory",
        ],
        "target_label_patterns": ["accounting policies", "basis of preparation", "financial instruments"],
        "statement_family": "accounting_policies",
        "expected_type": "text_block",
    },
    {
        "group": "notes_text_v2",
        "aliases": ["notes to the financial statements", "other notes to accounts", "bank overdraft represents the surplus of unpresented cheques"],
        "target_local_names": ["DisclosureOfOtherNotesToAccountsExplanatory", "DisclosureOfCashAndCashEquivalentsExplanatory"],
        "target_label_patterns": ["other notes to accounts", "cash and cash equivalents text block"],
        "statement_family": "notes",
        "expected_type": "text_block",
    },
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def no_side_effect_metadata() -> dict[str, Any]:
    return {
        "feature": "14D",
        "generated_at": utc_now_iso(),
        "read_only": True,
        "database_mutated": False,
        "db_schema_changed": False,
        "migration_created": False,
        "api_routes_implemented": False,
        "frontend_code_modified": False,
        "production_behavior_changed": False,
        "production_extraction_behavior_changed": False,
        "production_mapping_behavior_changed": False,
        "taxonomy_mapping_performed": False,
        "final_mapping_approved": False,
        "real_human_approval_recorded": False,
        "production_mapping_approval_produced": False,
        "semantic_matcher_called": False,
        "production_semantic_matcher_called": False,
        "embeddings_used": False,
        "xbrl_generated": False,
        "arelle_validation_run": False,
        "azure_di_live_call_made": False,
        "live_huggingface_calls_made": False,
        "live_openai_calls_made": False,
        "external_provider_calls": False,
        "reference_xml_sent_to_model": False,
        "reference_xml_sent_to_provider": False,
    }


def local_name(qname: str) -> str:
    return clean_text(str(qname).split(":")[-1])


def split_camel(value: str) -> str:
    import re

    return clean_text(re.sub(r"([a-z])([A-Z])", r"\1 \2", value))


def alias_record(alias: str, group: str, strength: float = 0.98) -> dict[str, Any]:
    return {
        "alias": clean_text(alias),
        "normalized_alias": normalize_text(alias),
        "source": "curated_14d_alias",
        "group": group,
        "strength": strength,
    }


def _concept_matches_group(concept: Mapping[str, Any], group: Mapping[str, Any]) -> bool:
    qname = local_name(str(concept.get("concept_qname") or ""))
    qname_norm = normalize_text(split_camel(qname))
    label_norm = normalize_text(concept.get("concept_label") or "")
    haystack = f"{qname_norm} {label_norm}"
    target_names = [normalize_text(split_camel(name)) for name in group.get("target_local_names") or []]
    target_patterns = [normalize_text(pattern) for pattern in group.get("target_label_patterns") or []]
    if any(target and target in qname_norm for target in target_names):
        return True
    return any(pattern and pattern in haystack for pattern in target_patterns)


def _type_compatible(concept: Mapping[str, Any], expected_type: str | None) -> bool:
    if expected_type == "numeric":
        return concept.get("is_numeric_concept") is True and concept.get("is_text_block_concept") is not True
    if expected_type == "text_block":
        return concept.get("is_text_block_concept") is True
    return True


def apply_curated_aliases_v2(concepts: Iterable[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Counter[str]]:
    enriched = [dict(concept) for concept in concepts]
    unresolved: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()

    for group in CURATED_ALIAS_GROUPS_V2:
        matches = [
            concept
            for concept in enriched
            if _concept_matches_group(concept, group) and _type_compatible(concept, group.get("expected_type"))
        ]
        if not matches:
            unresolved.append(
                {
                    "group": group["group"],
                    "aliases": group.get("aliases", []),
                    "reason": "target_concept_not_found_in_local_metadata_or_reference_inventory",
                }
            )
            continue
        for concept in matches:
            aliases = set(concept.get("aliases") or [])
            records = list(concept.get("alias_records") or [])
            for alias in group.get("aliases") or []:
                alias_norm = normalize_text(alias)
                if not alias_norm:
                    continue
                if alias_norm not in aliases:
                    aliases.add(alias_norm)
                    records.append(alias_record(alias, group["group"]))
                    counts[group["group"]] += 1
            statement_family = group.get("statement_family")
            if statement_family and concept.get("statement_family") in {None, "", "unknown", "notes"}:
                concept["statement_family"] = statement_family
            concept["aliases"] = sorted(aliases)
            concept["alias_records"] = records
            concept["token_set"] = sorted(token_set(f"{concept.get('concept_label', '')} {' '.join(aliases)}"))
            warnings = list(concept.get("enrichment_warnings") or [])
            warnings.append(f"14D_alias_group:{group['group']}")
            concept["enrichment_warnings"] = sorted(set(warnings))
    return enriched, unresolved, counts


def diagnose_14c_blockers(
    *,
    decisions_report: Mapping[str, Any],
    mapping_report: Mapping[str, Any] | None = None,
    review_queue: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    decisions = [row for row in decisions_report.get("simulated_decisions") or [] if not row.get("xbrl_eligible")]
    records_by_id = {row.get("mapping_input_id"): row for row in (mapping_report or {}).get("mapping_records") or []}
    queue_by_id = {row.get("mapping_input_id"): row for row in (review_queue or {}).get("queue_items") or []}
    decision_counts = Counter(str(row.get("decision_type") or "unknown") for row in decisions)
    workflow_counts = Counter(str(row.get("workflow_status") or "unknown") for row in decisions)
    tier_counts = Counter(str(row.get("original_confidence_tier") or "none") for row in decisions)
    row_type_counts = Counter(str(row.get("row_type") or "unknown") for row in decisions)
    blocker_counts = Counter(blocker for row in decisions for blocker in row.get("xbrl_blockers") or [])

    def row_summary(row: Mapping[str, Any]) -> dict[str, Any]:
        evidence = row.get("source_evidence") or {}
        mapping_id = row.get("mapping_input_id")
        mapping = records_by_id.get(mapping_id, {})
        queue = queue_by_id.get(mapping_id, {})
        top = mapping.get("top_suggestion") or queue.get("top_suggestion") or row.get("selected_suggestion") or {}
        return {
            "mapping_input_id": mapping_id,
            "label": evidence.get("label") or mapping.get("label") or queue.get("label"),
            "row_type": row.get("row_type") or mapping.get("row_type") or queue.get("row_type"),
            "statement_section": evidence.get("statement_section") or mapping.get("statement_section") or queue.get("statement_section"),
            "decision_type": row.get("decision_type"),
            "workflow_status": row.get("workflow_status"),
            "confidence_tier": row.get("original_confidence_tier"),
            "blockers": row.get("xbrl_blockers") or [],
            "top_concept": top.get("concept_qname"),
            "top_concept_label": top.get("concept_label"),
        }

    alias_rows = [row_summary(row) for row in decisions if row.get("decision_type") == "request_alias_enrichment"]
    manual_rows = [row_summary(row) for row in decisions if row.get("decision_type") == "require_manual_taxonomy_mapping"]
    deferred_rows = [row_summary(row) for row in decisions if row.get("decision_type") == "defer_mapping"]
    blocked_rows = [row_summary(row) for row in decisions if row.get("decision_type") == "blocked_from_xbrl"]
    return {
        "non_approved_count": len(decisions),
        "decision_type_counts": dict(decision_counts),
        "workflow_status_counts": dict(workflow_counts),
        "confidence_tier_counts": dict(tier_counts),
        "row_type_counts": dict(row_type_counts),
        "blocker_counts": dict(blocker_counts),
        "top_labels_needing_alias_enrichment": alias_rows[:25],
        "top_labels_needing_concept_metadata_enrichment": [*alias_rows[:10], *blocked_rows[:10]],
        "top_ambiguous_concept_groups": manual_rows[:25],
        "top_text_block_mapping_blockers": [row_summary(row) for row in decisions if row.get("row_type") == "text_block"][:25],
        "top_numeric_mapping_blockers": [row_summary(row) for row in decisions if row.get("row_type") in NUMERIC_ROW_TYPES][:25],
        "top_no_safe_labels": [row_summary(row) for row in decisions if row.get("original_confidence_tier") in {None, "none"}][:25],
        "labels_improved_from_13z_to_14a_but_unapproved": [*manual_rows[:10], *deferred_rows[:10]],
        "candidate_labels_that_may_be_context_only": [
            row
            for row in [row_summary(item) for item in decisions]
            if str(row.get("row_type")) == "text_block" and row.get("decision_type") in {"request_alias_enrichment", "blocked_from_xbrl"}
        ][:25],
    }


def build_enriched_concept_metadata_v2(
    *,
    local_concepts: list[dict[str, Any]] | None = None,
    template_path: str | None = "mpers_templates.json",
    reference_report_path: str | None = None,
    run_id: str | None = None,
    input_paths: Mapping[str, Any] | None = None,
    decisions_report: Mapping[str, Any] | None = None,
    mapping_report: Mapping[str, Any] | None = None,
    review_queue: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    base_concepts, base_report = build_enriched_concept_metadata(
        local_concepts=local_concepts,
        template_path=template_path or "mpers_templates.json",
        reference_report_path=reference_report_path,
        run_id=run_id,
        input_paths=input_paths,
    )
    enriched, unresolved_v2, alias_counts_v2 = apply_curated_aliases_v2(base_concepts)
    blocker_diagnosis = diagnose_14c_blockers(
        decisions_report=decisions_report or {},
        mapping_report=mapping_report,
        review_queue=review_queue,
    )
    report = build_enrichment_v2_report(
        enriched_concepts=enriched,
        base_report=base_report,
        unresolved_aliases_v2=unresolved_v2,
        alias_counts_v2=alias_counts_v2,
        blocker_diagnosis=blocker_diagnosis,
        input_paths=input_paths or {},
        run_id=run_id,
    )
    return enriched, report


def build_enrichment_v2_report(
    *,
    enriched_concepts: list[Mapping[str, Any]],
    base_report: Mapping[str, Any],
    unresolved_aliases_v2: list[dict[str, Any]],
    alias_counts_v2: Counter[str],
    blocker_diagnosis: Mapping[str, Any],
    input_paths: Mapping[str, Any],
    run_id: str | None,
) -> dict[str, Any]:
    families = Counter(str(concept.get("concept_family") or infer_statement_family(concept.get("concept_label")) or "unknown") for concept in enriched_concepts)
    sources = Counter(str((concept.get("source_metadata") or {}).get("source") or concept.get("source") or "unknown") for concept in enriched_concepts)
    alias_count = sum(len(concept.get("aliases") or []) for concept in enriched_concepts)
    numeric_count = sum(1 for concept in enriched_concepts if concept.get("is_numeric_concept") is True)
    text_count = sum(1 for concept in enriched_concepts if concept.get("is_text_block_concept") is True)
    return {
        "run_metadata": {
            **no_side_effect_metadata(),
            "run_id": run_id,
            "report_type": "azure_di_concept_metadata_enrichment_v2",
            "script": "scripts/refine_azure_di_mapping_candidates_14d.py",
        },
        "input_reports": dict(input_paths),
        "source_feature_chain": ["13X", "13Y", "13Z", "14A", "14B", "14C", "14D"],
        "concept_sources_used": dict(sources),
        "concept_count": len(enriched_concepts),
        "alias_count": alias_count,
        "base_14a_alias_count": base_report.get("alias_count", 0),
        "curated_alias_count": sum(alias_counts_v2.values()),
        "curated_aliases_by_group": dict(sorted(alias_counts_v2.items())),
        "base_14a_unresolved_alias_count": base_report.get("unresolved_alias_count", 0),
        "unresolved_alias_count": len(unresolved_aliases_v2),
        "unresolved_aliases": unresolved_aliases_v2,
        "numeric_concept_count": numeric_count,
        "text_block_concept_count": text_count,
        "concept_families": dict(sorted(families.items())),
        "blocker_diagnosis": dict(blocker_diagnosis),
        "metadata_limitations": [
            "Enrichment v2 is deterministic and attaches aliases only to existing local/reference-inventory qnames.",
            "No fake concept qnames are created.",
            "Reference report, when provided, is used only as offline concept inventory and not as a direct answer key.",
            "No Azure DI, Hugging Face, OpenAI, embeddings, semantic matcher, DB, XBRL, or Arelle path is used.",
        ],
    }


def status_rank(status: str | None) -> int:
    return {
        "no_safe_suggestion": 0,
        "blocked_by_gate": 0,
        "low_confidence_suggestion": 1,
        "ambiguous_multiple_suggestions": 1,
        "medium_confidence_suggestion": 2,
        "high_confidence_suggestion": 3,
    }.get(str(status or ""), 0)


def build_refinement_comparison_14d(
    *,
    baseline_14a_candidates: Mapping[str, Any],
    baseline_14c_decisions: Mapping[str, Any],
    baseline_14c_eligibility: Mapping[str, Any],
    refined_14d_candidates: Mapping[str, Any],
    refined_14d_queue: Mapping[str, Any],
    refined_14d_decisions: Mapping[str, Any],
    refined_14d_eligibility: Mapping[str, Any],
    enrichment_report: Mapping[str, Any],
    input_paths: Mapping[str, Any],
    run_id: str | None,
) -> dict[str, Any]:
    before_records = {row.get("mapping_input_id"): row for row in baseline_14a_candidates.get("mapping_records") or []}
    after_records = {row.get("mapping_input_id"): row for row in refined_14d_candidates.get("mapping_records") or []}
    improved: list[dict[str, Any]] = []
    unchanged: list[dict[str, Any]] = []
    worsened: list[dict[str, Any]] = []
    for mapping_id, after in after_records.items():
        before = before_records.get(mapping_id, {})
        row = {
            "mapping_input_id": mapping_id,
            "label": after.get("label"),
            "row_type": after.get("row_type"),
            "before_status": before.get("mapping_status"),
            "after_status": after.get("mapping_status"),
            "before_top_concept": (before.get("top_suggestion") or {}).get("concept_qname"),
            "after_top_concept": (after.get("top_suggestion") or {}).get("concept_qname"),
            "before_score": (before.get("top_suggestion") or {}).get("score"),
            "after_score": (after.get("top_suggestion") or {}).get("score"),
        }
        if status_rank(row["after_status"]) > status_rank(row["before_status"]):
            improved.append(row)
        elif status_rank(row["after_status"]) < status_rank(row["before_status"]):
            worsened.append(row)
        else:
            unchanged.append(row)
    return {
        "run_metadata": {
            **no_side_effect_metadata(),
            "run_id": run_id,
            "report_type": "azure_di_refinement_comparison",
            "script": "scripts/refine_azure_di_mapping_candidates_14d.py",
        },
        "input_reports": dict(input_paths),
        "source_feature_chain": ["13X", "13Y", "13Z", "14A", "14B", "14C", "14D"],
        "before_14a_status_counts": dict(baseline_14a_candidates.get("status_counts") or {}),
        "after_14d_status_counts": dict(refined_14d_candidates.get("status_counts") or {}),
        "before_14c_decision_type_counts": dict(baseline_14c_decisions.get("decision_type_counts") or {}),
        "after_14d_decision_type_counts": dict(refined_14d_decisions.get("decision_type_counts") or {}),
        "before_14c_xbrl_eligible_count": baseline_14c_eligibility.get("xbrl_eligible_count", 0),
        "after_14d_xbrl_eligible_count": refined_14d_eligibility.get("xbrl_eligible_count", 0),
        "before_14c_blocked_deferred_or_enrichment_needed": int(baseline_14c_decisions.get("simulated_decision_count") or 0)
        - int(baseline_14c_decisions.get("xbrl_eligible_count") or 0),
        "after_14d_blocked_deferred_or_enrichment_needed": int(refined_14d_decisions.get("simulated_decision_count") or 0)
        - int(refined_14d_decisions.get("xbrl_eligible_count") or 0),
        "mapping_labels_improved": improved,
        "mapping_labels_unchanged": unchanged[:50],
        "mapping_labels_worsened": worsened,
        "workflow_status_distribution_14d": refined_14d_queue.get("workflow_status_distribution") or {},
        "priority_distribution_14d": refined_14d_queue.get("priority_distribution") or {},
        "curated_aliases_by_group": enrichment_report.get("curated_aliases_by_group") or {},
        "unresolved_aliases": enrichment_report.get("unresolved_aliases") or [],
        "cautionary_notes": [
            "All mapping outputs remain suggested_only.",
            "All simulated approvals remain simulated_only=true and human_approved=false.",
            "No production mapping approval, XBRL generation, or Arelle validation occurred.",
            "If eligibility does not improve, the report should be read as blocker diagnosis rather than production readiness.",
        ],
        "recommended_next_feature": recommend_next_feature_14d(refined_14d_eligibility),
    }


def recommend_next_feature_14d(eligibility_report: Mapping[str, Any]) -> str:
    total = int(eligibility_report.get("total_review_items") or 0)
    eligible = int(eligibility_report.get("xbrl_eligible_count") or 0)
    if total and eligible >= total * 0.5:
        return "Feature #14E - Reviewed mapping quality evaluation against reference XML, no DB mutation."
    if total and eligible >= total * 0.25:
        return "Feature #14E - Manual mapping review UI/API planning if review workflow is now acceptable."
    return "Feature #14E - Concept metadata enrichment v3 if too few mappings are still simulated eligible."


def render_enrichment_v2_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Azure DI Concept Metadata Enrichment v2 - Feature #14D",
        "",
        "## Summary",
        "",
        f"- Concepts: {report.get('concept_count', 0)}",
        f"- Aliases: {report.get('alias_count', 0)}",
        f"- Curated aliases attached in v2: {report.get('curated_alias_count', 0)}",
        f"- Unresolved alias groups in v2: {report.get('unresolved_alias_count', 0)}",
        f"- Numeric concepts: {report.get('numeric_concept_count', 0)}",
        f"- Text-block concepts: {report.get('text_block_concept_count', 0)}",
        "",
        "## #14C Blocker Diagnosis",
        "",
    ]
    diagnosis = report.get("blocker_diagnosis") or {}
    lines.append(f"- Non-approved #14C decisions: {diagnosis.get('non_approved_count', 0)}")
    lines.append(f"- Decision types: {diagnosis.get('decision_type_counts', {})}")
    lines.append(f"- Row types: {diagnosis.get('row_type_counts', {})}")
    lines.extend(["", "## Curated Alias Groups", ""])
    aliases = report.get("curated_aliases_by_group") or {}
    lines.extend(f"- {key}: {value}" for key, value in aliases.items()) if aliases else lines.append("- None")
    lines.extend(["", "## Unresolved Alias Groups", ""])
    unresolved = report.get("unresolved_aliases") or []
    lines.extend(f"- {row.get('group')}: {row.get('reason')}" for row in unresolved) if unresolved else lines.append("- None")
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.get("metadata_limitations", []))
    lines.append("")
    return "\n".join(lines)


def render_refinement_comparison_14d_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Azure DI Refinement Comparison - Feature #14D",
        "",
        "## Summary",
        "",
        f"- #14C XBRL eligible: {report.get('before_14c_xbrl_eligible_count', 0)}",
        f"- #14D XBRL eligible: {report.get('after_14d_xbrl_eligible_count', 0)}",
        f"- #14C decisions: {report.get('before_14c_decision_type_counts', {})}",
        f"- #14D decisions: {report.get('after_14d_decision_type_counts', {})}",
        f"- #14D mapping statuses: {report.get('after_14d_status_counts', {})}",
        f"- Recommended next feature: {report.get('recommended_next_feature')}",
        "",
        "## Improved Labels",
        "",
    ]
    improved = report.get("mapping_labels_improved") or []
    lines.extend(
        f"- `{row.get('mapping_input_id')}` {row.get('label')}: {row.get('before_status')} -> {row.get('after_status')}"
        for row in improved[:25]
    ) if improved else lines.append("- None")
    lines.extend(["", "## Worsened Labels", ""])
    worsened = report.get("mapping_labels_worsened") or []
    lines.extend(
        f"- `{row.get('mapping_input_id')}` {row.get('label')}: {row.get('before_status')} -> {row.get('after_status')}"
        for row in worsened[:25]
    ) if worsened else lines.append("- None")
    lines.extend(["", "## Cautionary Notes", ""])
    lines.extend(f"- {item}" for item in report.get("cautionary_notes", []))
    lines.append("")
    return "\n".join(lines)

