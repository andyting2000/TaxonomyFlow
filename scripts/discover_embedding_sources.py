import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import AsyncSessionLocal, MBRSTaxonomyTag, XMLTemplateField
from scripts.generate_openai_embeddings import (
    MPERS_TEMPLATE_PATH,
    mpers_template_json_source_records,
    template_service_source_records,
)


REPORT_PATH = Path("reports/openai_embedding_source_discovery.json")


def _sample_source_records(records: List[Any], limit: int = 3) -> List[Dict[str, Any]]:
    samples = []
    for record in records[:limit]:
        samples.append(
            {
                "source_type": record.source_type,
                "source_id": record.source_id,
                "source_label": record.source_label,
                "source_text_preview": record.source_text[:240],
                "metadata": record.metadata,
            }
        )
    return samples


async def _db_table_summary(
    source_name: str,
    source_type: str,
    model: Any,
    *,
    currently_used: str,
    stable_ids: bool = True,
) -> Dict[str, Any]:
    async with AsyncSessionLocal() as session:
        total = int((await session.execute(select(func.count(model.id)))).scalar() or 0)
        rows = (
            await session.execute(select(model).order_by(model.id).limit(3))
        ).scalars().all()

    samples = []
    for row in rows:
        samples.append(
            {
                "id": str(row.id),
                "label": getattr(row, "label", None),
                "xbrl_tag": getattr(row, "xbrl_tag", None),
                "field_id": getattr(row, "field_id", None),
                "statement_code": getattr(row, "statement_code", None),
            }
        )

    return {
        "source_name": source_name,
        "source_type": source_type,
        "record_count": total,
        "sample_records": samples,
        "currently_used_by_production": currently_used,
        "has_stable_ids": stable_ids,
        "has_embedding_suitable_text": total > 0,
        "embedding_suitability": (
            "usable if populated; current local table is empty"
            if total == 0
            else "usable label/xbrl fields"
        ),
    }


def _template_source_summary(
    source_name: str,
    source_type: str,
    records: List[Any],
    *,
    currently_used: str,
    source_path: Optional[Path] = None,
) -> Dict[str, Any]:
    return {
        "source_name": source_name,
        "source_type": source_type,
        "record_count": len(records),
        "sample_records": _sample_source_records(records),
        "currently_used_by_production": currently_used,
        "has_stable_ids": bool(records),
        "has_embedding_suitable_text": any(record.source_text for record in records),
        "embedding_suitability": (
            "recommended active template/concept source"
            if source_type == "template_service_concept"
            else "usable source, but template service is preferred because it reflects runtime-friendly descriptions"
        ),
        "source_path": str(source_path) if source_path else None,
    }


async def collect_source_discovery_report() -> Dict[str, Any]:
    db_taxonomy = await _db_table_summary(
        "mbrs_taxonomy_tags table",
        "mbrs_taxonomy_tag",
        MBRSTaxonomyTag,
        currently_used="taxonomy search and legacy semantic search when populated; empty in current local DB",
    )
    db_template_fields = await _db_table_summary(
        "xml_template_fields table",
        "xml_template_field",
        XMLTemplateField,
        currently_used="legacy/template table source; empty in current local DB",
    )

    json_records = mpers_template_json_source_records(MPERS_TEMPLATE_PATH)
    service_records = template_service_source_records()

    sources = [
        db_taxonomy,
        db_template_fields,
        _template_source_summary(
            "mpers_templates.json",
            "mpers_template_concept",
            json_records,
            currently_used="loaded by XBRLTemplateService at runtime",
            source_path=MPERS_TEMPLATE_PATH,
        ),
        _template_source_summary(
            "XBRLTemplateService loaded concepts",
            "template_service_concept",
            service_records,
            currently_used="used by template review, prompt building, and find_matching_concept_hybrid string/template matching",
        ),
        {
            "source_name": "taxonomy search/cache DB source",
            "source_type": "mbrs_taxonomy_tag",
            "record_count": db_taxonomy["record_count"],
            "sample_records": db_taxonomy["sample_records"],
            "currently_used_by_production": "routers/taxonomy.py searches mbrs_taxonomy_tags; current local table is empty",
            "has_stable_ids": True,
            "has_embedding_suitable_text": db_taxonomy["record_count"] > 0,
            "embedding_suitability": "not recommended for #13E local backfill because source table is empty",
        },
    ]

    recommended = "template-service-concepts" if service_records else None

    return {
        "feature": "13E",
        "mode": "read_only",
        "mutates_database": False,
        "sources": sources,
        "recommended_source_for_openai_embeddings": recommended,
        "reason": (
            "Current DB embedding source tables are empty. XBRLTemplateService loads "
            "mpers_templates.json and is the active concept source used by template review "
            "and string/template matching."
        ),
    }


def write_report(report: Dict[str, Any], output_path: Path = REPORT_PATH) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return output_path


def render_text_report(report: Dict[str, Any]) -> str:
    lines = [
        "OpenAI embedding source discovery",
        "Mode: read-only",
        f"Recommended source: {report.get('recommended_source_for_openai_embeddings')}",
        "",
    ]
    for source in report.get("sources", []):
        lines.append(
            "- {source_name}: type={source_type}, records={record_count}, suitable={has_embedding_suitable_text}".format(
                **source
            )
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only discovery of available OpenAI embedding source records."
    )
    parser.add_argument(
        "--output",
        default=str(REPORT_PATH),
        help="JSON report path. Defaults to reports/openai_embedding_source_discovery.json.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON report.")
    return parser


async def async_main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    report = await collect_source_discovery_report()
    output_path = write_report(report, Path(args.output))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_text_report(report))
        print(f"Wrote source discovery report: {output_path}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
