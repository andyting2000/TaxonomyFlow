"""Read-only deterministic replay of #19C candidate retrieval for one local job."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database import AsyncSessionLocal, ExtractedDataItem, FinancialStatementPage
from services.section_aware_initial_mapping import build_document_initial_mapping
from services.section_aware_initial_mapping_llm import InitialMappingLLMConfig
from services.toc_aware_document_structure import document_structure_artifact_path
from services.toc_aware_template_classification import (
    template_classification_artifact_path,
)


async def load_local_source_rows(job_id: int) -> list[dict[str, Any]]:
    structure_path = document_structure_artifact_path(job_id)
    structure = json.loads(structure_path.read_text(encoding="utf-8"))
    evidence = [
        item
        for item in structure.get("content_evidence") or []
        if item.get("content_type") == "extracted_row"
    ]
    async with AsyncSessionLocal() as session:
        records = (
            await session.execute(
                select(
                    ExtractedDataItem.id,
                    ExtractedDataItem.extracted_label,
                    ExtractedDataItem.extracted_value,
                    ExtractedDataItem.value_previous_year,
                    ExtractedDataItem.financial_year,
                    ExtractedDataItem.financial_year_previous,
                    FinancialStatementPage.page_number,
                )
                .join(
                    FinancialStatementPage,
                    ExtractedDataItem.page_id == FinancialStatementPage.id,
                )
                .where(FinancialStatementPage.job_id == int(job_id))
            )
        ).all()
    by_id = {str(record.id): record for record in records}
    if set(by_id) != {str(item.get("content_id")) for item in evidence}:
        raise ValueError("Persisted rows do not match current structure evidence")

    rows = []
    for item in evidence:
        record = by_id[str(item["content_id"])]
        provenance = dict(item.get("provenance") or {})
        table_index = provenance.get("table_index")
        rows.append(
            {
                "source_row_id": str(record.id),
                "original_candidate_id": provenance.get("original_candidate_id"),
                "persisted_extracted_data_item_id": str(record.id),
                "label": record.extracted_label,
                "normalized_label": "",
                "row_type": provenance.get("row_type") or "unknown",
                "current_value": record.extracted_value,
                "prior_value": record.value_previous_year,
                "current_year": record.financial_year,
                "prior_year": record.financial_year_previous,
                "statement_section": None,
                "page_number": record.page_number,
                "table_id": f"table:{table_index}" if table_index is not None else None,
                "table_title": None,
                "table_headers": [],
                "column_headers": [],
                "currency": None,
                "unit": None,
                "sign": None,
                "indentation": None,
                "parent_row_id": None,
                "provenance": provenance,
                "warnings": [],
            }
        )
    return rows


async def diagnose(job_id: int) -> dict[str, Any]:
    rows = await load_local_source_rows(job_id)
    events: list[dict[str, Any]] = []
    result = await build_document_initial_mapping(
        job_id=job_id,
        filing_id=job_id,
        source_rows=rows,
        llm_config=InitialMappingLLMConfig(mode="deterministic_only"),
        stage_callback=lambda stage, status, details: events.append(
            {"stage": stage, "status": status, **dict(details)}
        ),
    )
    retrieval = next(
        item
        for item in events
        if item["stage"] == "19C_candidate_retrieval"
        and item["status"] == "completed"
    )
    return {
        "diagnostic": "19C-candidate-retrieval-read-only-v1",
        "job_id": job_id,
        "read_only": True,
        "provider_calls": result.llm_calls,
        "persistence_invoked": False,
        "source_rows": len(rows),
        "retrieval": retrieval,
        "mapping_result": {
            "total_rows": result.total_rows,
            "eligible_rows": result.eligible_rows,
            "failed_rows": result.failed_rows,
            "decision_counts": dict(
                sorted(Counter(item.decision for item in result.mappings).items())
            ),
        },
        "safety": {
            key: value
            for key, value in result.safety_summary.items()
            if key.endswith("_mutations")
            or key
            in {
                "provider_calls",
                "recursive_retries",
                "xbrl_generation_count",
                "arelle_runs",
                "auditor_xml_used",
                "benchmark_gold_used",
            }
        },
        "artifacts_read": [
            str(document_structure_artifact_path(job_id)),
            str(template_classification_artifact_path(job_id)),
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True, type=int)
    arguments = parser.parse_args()
    try:
        report = asyncio.run(diagnose(arguments.job_id))
    except Exception as exc:
        cause = exc.__cause__ or exc
        report = {
            "diagnostic": "19C-candidate-retrieval-read-only-v1",
            "job_id": arguments.job_id,
            "read_only": True,
            "status": "failed",
            "exception_class": type(cause).__name__,
            "safe_exception_message": str(cause)[:256],
        }
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
        return 1
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
