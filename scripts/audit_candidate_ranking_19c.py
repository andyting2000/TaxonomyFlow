#!/usr/bin/env python3
"""Read-only complete candidate-scope audit for one local #19C job."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.diagnose_candidate_retrieval_job_19c import load_local_source_rows  # noqa: E402
from services.section_aware_initial_mapping import (  # noqa: E402
    _classification_contexts,
    detect_duplicate_and_competing_rows,
    nearest_structural_context_label,
)
from services.section_aware_row_mapping_eligibility import (  # noqa: E402
    classify_row_mapping_eligibility,
)
from services.section_aware_taxonomy_candidate_retriever import (  # noqa: E402
    RETRIEVAL_VERSION,
    audit_section_aware_candidate_scope,
)
from services.section_aware_taxonomy_concept_cards import (  # noqa: E402
    build_taxonomy_concept_inventory,
)
from services.template_group_registry import load_template_group_registry  # noqa: E402
from services.toc_aware_document_structure import load_document_structure  # noqa: E402
from services.toc_aware_template_classification import (  # noqa: E402
    load_template_classification,
)


AUDIT_VERSION = "19C-candidate-ranking-audit-v1"


def _public_candidate_record(record: Mapping[str, Any]) -> dict[str, Any]:
    card = dict(record["concept_card"])
    return {
        "rank": record.get("rank"),
        "qname": record["qname"],
        "label": card.get("standard_label"),
        "aliases": list(card.get("aliases") or []),
        "template_memberships": list(card.get("template_group_ids") or []),
        "role_memberships": list(card.get("role_uris") or []),
        "parent_concepts": list(card.get("parent_concepts") or []),
        "period_type": card.get("period_type"),
        "datatype": card.get("datatype"),
        "balance": card.get("balance"),
        "abstract": bool(card.get("abstract")),
        "selectable": bool(record.get("selectable")),
        "score": record.get("score"),
        "exclusion_reason": record.get("exclusion_reason"),
    }


async def audit_job(job_id: int) -> dict[str, Any]:
    rows = await load_local_source_rows(job_id)
    structure = load_document_structure(job_id)
    classification = load_template_classification(job_id, structure=structure)
    registry = load_template_group_registry()
    cards, inventory = build_taxonomy_concept_inventory()
    row_metadata, _ = detect_duplicate_and_competing_rows(rows)
    contexts = _classification_contexts(
        structure,
        classification,
        rows,
        registry=registry,
    )
    rows_by_section: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        context = contexts[str(row["source_row_id"])]
        key = str(context.get("subsection_id") or context.get("section_id") or "unassigned")
        rows_by_section.setdefault(key, []).append(row)

    audits: list[dict[str, Any]] = []
    eligibility_counts: Counter[str] = Counter()
    for row in rows:
        row_id = str(row["source_row_id"])
        context = contexts[row_id]
        duplicate = row_metadata.get(row_id, {})
        eligibility = classify_row_mapping_eligibility(
            row,
            section_outcome=context["classification_outcome"],
            duplicate_group_id=duplicate.get("duplicate_group_id"),
            duplicate_rank=int(duplicate.get("duplicate_rank") or 0),
            competing_source_row_ids=duplicate.get("competing_source_row_ids") or [],
        )
        eligibility_counts[eligibility.outcome] += 1
        if not eligibility.eligible:
            continue
        key = str(context.get("subsection_id") or context.get("section_id") or "unassigned")
        peers = rows_by_section[key]
        peer_index = next(
            index
            for index, item in enumerate(peers)
            if str(item["source_row_id"]) == row_id
        )
        siblings = [
            str(item.get("label") or "")
            for index, item in enumerate(peers)
            if index != peer_index and abs(index - peer_index) <= 3
        ]
        parent = next(
            (
                item
                for item in peers
                if str(item.get("source_row_id")) == str(row.get("parent_row_id"))
            ),
            None,
        )
        parent_label = (
            parent.get("label")
            if parent
            else nearest_structural_context_label(peers, peer_index)
        )
        scope = audit_section_aware_candidate_scope(
            row=row,
            row_eligibility=eligibility,
            section_id=context.get("section_id"),
            subsection_id=context.get("subsection_id"),
            template_group_ids=context.get("template_group_ids") or [],
            statement_families=context.get("statement_families") or [],
            inventory_cards=cards,
            concept_inventory_hash=inventory["concept_inventory_hash"],
            sibling_labels=siblings,
            parent_label=parent_label,
        )
        audits.append(
            {
                "source_row_id": row_id,
                "raw_label": scope["raw_label"],
                "semantic_source_label": scope["semantic_source_label"],
                "semantic_normalization_reasons": scope["semantic_normalization_reasons"],
                "semantic_target_families": scope["semantic_target_families"],
                "semantic_scope_limitations": scope["semantic_scope_limitations"],
                "section_id": context.get("section_id"),
                "subsection_id": context.get("subsection_id"),
                "section_title": context.get("section_title"),
                "subsection_title": context.get("subsection_title"),
                "template_group_ids": scope["template_group_ids"],
                "statement_families": scope["statement_families"],
                "candidate_count_before_filter": scope["candidate_count_before_filter"],
                "candidate_count_after_filter": scope["candidate_count_after_filter"],
                "candidates": [
                    _public_candidate_record(record)
                    for record in scope["candidate_records"]
                ],
            }
        )
    return {
        "audit_version": AUDIT_VERSION,
        "retrieval_version": RETRIEVAL_VERSION,
        "job_id": int(job_id),
        "read_only": True,
        "database_operation": "SELECT_ONLY",
        "provider_calls": 0,
        "persistence_invoked": False,
        "source_rows": len(rows),
        "eligible_rows": len(audits),
        "eligibility_counts": dict(sorted(eligibility_counts.items())),
        "concept_inventory_count": inventory["concept_count"],
        "concept_inventory_hash": inventory["concept_inventory_hash"],
        "rows": audits,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print the complete read-only #19C candidate audit for a local job."
    )
    parser.add_argument("job_id", type=int)
    arguments = parser.parse_args()
    try:
        result = asyncio.run(audit_job(arguments.job_id))
    except Exception as exc:
        print(
            json.dumps(
                {
                    "audit_version": AUDIT_VERSION,
                    "job_id": arguments.job_id,
                    "read_only": True,
                    "status": "failed",
                    "exception_class": type(exc).__name__,
                    "safe_exception_message": str(exc)[:256],
                },
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
