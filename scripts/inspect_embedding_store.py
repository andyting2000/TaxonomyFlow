import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings
from database import AsyncSessionLocal
from services.semantic_matcher import SemanticMatcher
from services.xbrl_template_service import get_xbrl_template_service


EMBEDDING_TABLES = ("xml_template_fields", "mbrs_taxonomy_tags")
EMBEDDING_COLUMN = "embedding"
PROVIDER_EMBEDDING_TABLE = "semantic_embeddings"
PROVIDER_SOURCE_TYPES = {
    "mbrs_taxonomy_tags": "mbrs_taxonomy_tag",
    "xml_template_fields": "xml_template_field",
}
LEGACY_HF_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-8B"
LEGACY_HF_EMBEDDING_DIMENSION = SemanticMatcher.EMBEDDING_DIMENSIONS
VECTOR_TYPE_RE = re.compile(r"vector(?:\((\d+)\))?")


def parse_vector_dimension(data_type: Optional[str]) -> Optional[int]:
    match = VECTOR_TYPE_RE.search(str(data_type or ""))
    if not match:
        return None
    if match.group(1) is None:
        return None
    return int(match.group(1))


def summarize_configuration(settings_obj: Any = settings) -> Dict[str, Any]:
    model_provider = str(getattr(settings_obj, "model_provider", "") or "").lower()
    embedding_model = str(getattr(settings_obj, "embedding_model_id", "") or "")
    embedding_dimension = getattr(settings_obj, "embedding_dimension", None)
    return {
        "model_provider": model_provider,
        "active_provider": "huggingface",
        "active_embedding_model": embedding_model,
        "active_expected_dimension": embedding_dimension,
        "openai_embedding_model": str(getattr(settings_obj, "openai_embedding_model", "") or ""),
        "legacy_hugging_face_embedding_model": LEGACY_HF_EMBEDDING_MODEL,
        "legacy_hugging_face_embedding_dimension": LEGACY_HF_EMBEDDING_DIMENSION,
        "live_hugging_face_embedding_calls_enabled": True,
        "openai_mode_embedding_behavior": "inactive_legacy_only",
    }


def _safe_table_names(table_names: Iterable[str]) -> List[str]:
    allowed = set(EMBEDDING_TABLES)
    return [table_name for table_name in table_names if table_name in allowed]


async def inspect_embedding_schema(table_names: Iterable[str] = EMBEDDING_TABLES) -> List[Dict[str, Any]]:
    safe_tables = _safe_table_names(table_names)
    if not safe_tables:
        return []

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                """
                SELECT
                    c.relname AS table_name,
                    a.attname AS column_name,
                    format_type(a.atttypid, a.atttypmod) AS data_type,
                    a.atttypmod AS type_modifier
                FROM pg_attribute a
                JOIN pg_class c ON c.oid = a.attrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relname = ANY(:table_names)
                    AND a.attname = :column_name
                    AND NOT a.attisdropped
                    AND n.nspname = 'public'
                ORDER BY c.relname, a.attname
                """
            ),
            {"table_names": safe_tables, "column_name": EMBEDDING_COLUMN},
        )
        rows = result.mappings().all()

    return [
        {
            "table_name": row["table_name"],
            "column_name": row["column_name"],
            "data_type": row["data_type"],
            "vector_dimension": parse_vector_dimension(row["data_type"]),
            "type_modifier": row["type_modifier"],
        }
        for row in rows
    ]


async def inspect_embedding_counts(table_names: Iterable[str] = EMBEDDING_TABLES) -> List[Dict[str, Any]]:
    counts = []

    async with AsyncSessionLocal() as session:
        for table_name in _safe_table_names(table_names):
            result = await session.execute(
                text(
                    f"""
                    SELECT
                        COUNT(*) AS total_rows,
                        COUNT({EMBEDDING_COLUMN}) AS rows_with_embedding,
                        COUNT(*) - COUNT({EMBEDDING_COLUMN}) AS rows_missing_embedding
                    FROM {table_name}
                    """
                )
            )
            row = result.mappings().one()
            counts.append(
                {
                    "table_name": table_name,
                    "total_rows": int(row["total_rows"]),
                    "rows_with_embedding": int(row["rows_with_embedding"]),
                    "rows_missing_embedding": int(row["rows_missing_embedding"]),
                }
            )

    return counts


async def table_exists(table_name: str) -> bool:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                        AND table_name = :table_name
                )
                """
            ),
            {"table_name": table_name},
        )
        return bool(result.scalar())


async def inspect_provider_embedding_columns() -> List[Dict[str, Any]]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                """
                SELECT
                    column_name,
                    format_type(a.atttypid, a.atttypmod) AS data_type
                FROM information_schema.columns c
                JOIN pg_attribute a
                    ON a.attname = c.column_name
                JOIN pg_class cls
                    ON cls.oid = a.attrelid
                    AND cls.relname = c.table_name
                WHERE c.table_schema = 'public'
                    AND c.table_name = :table_name
                    AND NOT a.attisdropped
                ORDER BY c.ordinal_position
                """
            ),
            {"table_name": PROVIDER_EMBEDDING_TABLE},
        )
        rows = result.mappings().all()

    return [
        {
            "table_name": PROVIDER_EMBEDDING_TABLE,
            "column_name": row["column_name"],
            "data_type": row["data_type"],
            "vector_dimension": parse_vector_dimension(row["data_type"]),
        }
        for row in rows
    ]


async def inspect_provider_embedding_counts() -> List[Dict[str, Any]]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                """
                SELECT
                    provider,
                    model,
                    dimension,
                    source_type,
                    COUNT(*) AS total_rows,
                    COUNT(*) FILTER (WHERE is_active) AS active_rows
                FROM semantic_embeddings
                GROUP BY provider, model, dimension, source_type
                ORDER BY provider, model, dimension, source_type
                """
            )
        )
        rows = result.mappings().all()

    return [
        {
            "provider": row["provider"],
            "model": row["model"],
            "dimension": int(row["dimension"]),
            "source_type": row["source_type"],
            "total_rows": int(row["total_rows"]),
            "active_rows": int(row["active_rows"]),
        }
        for row in rows
    ]


async def inspect_provider_missing_counts() -> List[Dict[str, Any]]:
    counts = []
    async with AsyncSessionLocal() as session:
        active_provider = "huggingface"
        active_model = settings.embedding_model_id
        for source_table, source_type in PROVIDER_SOURCE_TYPES.items():
            source_total_result = await session.execute(
                text(f"SELECT COUNT(*) FROM {source_table}")
            )
            source_total = int(source_total_result.scalar() or 0)
            embedded_result = await session.execute(
                text(
                    """
                    SELECT COUNT(DISTINCT source_id)
                    FROM semantic_embeddings
                    WHERE provider = :provider
                        AND model = :model
                        AND source_type = :source_type
                        AND is_active
                    """
                ),
                {"provider": active_provider, "model": active_model, "source_type": source_type},
            )
            embedded_sources = int(embedded_result.scalar() or 0)
            counts.append(
                {
                    "source_table": source_table,
                    "source_type": source_type,
                    "source_total": source_total,
                    "active_huggingface_embedded_sources": embedded_sources,
                    "missing_huggingface_embeddings": max(0, source_total - embedded_sources),
                }
            )
        service_source_type = "template_service_concept"
        service_sources = get_xbrl_template_service().get_embedding_source_concepts()
        service_source_ids = {str(record["source_id"]) for record in service_sources}
        service_total = len(service_source_ids)
        service_embedded_result = await session.execute(
            text(
                """
                SELECT COUNT(DISTINCT source_id)
                FROM semantic_embeddings
                WHERE provider = :provider
                    AND model = :model
                    AND source_type = :source_type
                    AND is_active
                """
            ),
            {"provider": active_provider, "model": active_model, "source_type": service_source_type},
        )
        service_embedded_sources = int(service_embedded_result.scalar() or 0)
        counts.append(
            {
                "source_table": "XBRLTemplateService",
                "source_type": service_source_type,
                "source_records_total": len(service_sources),
                "source_total": service_total,
                "duplicate_source_records": max(0, len(service_sources) - service_total),
                "active_huggingface_embedded_sources": service_embedded_sources,
                "missing_huggingface_embeddings": max(0, service_total - service_embedded_sources),
            }
        )
    return counts


async def collect_embedding_store_report() -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "mode": "read_only",
        "mutates_database": False,
        "configuration": summarize_configuration(),
        "database_access": {"ok": True, "error": None},
        "embedding_store": {
            "tables": list(EMBEDDING_TABLES),
            "columns": [],
            "counts": [],
        },
        "provider_versioned_embedding_store": {
            "table": PROVIDER_EMBEDDING_TABLE,
            "exists": False,
            "columns": [],
            "counts_by_provider_model_dimension_source_type": [],
            "missing_counts_by_source_type": [],
            "openai_embeddings_exist": False,
            "huggingface_embeddings_exist": False,
        },
        "code_findings": {
            "semantic_matcher_dimension_constant": LEGACY_HF_EMBEDDING_DIMENSION,
            "semantic_matcher_openai_mode_disables_live_hf_client": False,
            "semantic_search_tables": ["mbrs_taxonomy_tags"],
            "template_embedding_table_present_in_schema": "xml_template_fields",
            "production_semantic_matcher_behavior": (
                "Hugging Face Qwen embedding model is active; legacy vector(1752) columns remain untouched"
            ),
            "hugging_face_embedding_touchpoints": [
                {
                    "file": "services/semantic_matcher.py",
                    "reference": "AsyncInferenceClient.feature_extraction",
                    "status_in_active_mode": "enabled when MODEL_API_TOKEN is configured",
                },
                {
                    "file": "services/xbrl_template_service.py",
                    "reference": "find_matching_concept_hybrid imports semantic_matcher and queries mbrs_taxonomy_tags.embedding",
                    "status_in_active_mode": "uses existing legacy vector(1752) semantic search when populated",
                },
                {
                    "file": "services/smart_ai_processor.py",
                    "reference": "_semantic_match_to_template_field delegates to xbrl_template_service.find_matching_concept_hybrid",
                    "status_in_active_mode": "no direct embedding API call; inherits xbrl_template_service behavior",
                },
                {
                    "file": "services/mpers_template_service.py",
                    "reference": "legacy hybrid matching path imports semantic_matcher and checks 1752-dimensional embeddings",
                    "status_in_active_mode": "uses Hugging Face client when available if this legacy service path is used",
                },
            ],
        },
    }

    try:
        report["embedding_store"]["columns"] = await inspect_embedding_schema()
        report["embedding_store"]["counts"] = await inspect_embedding_counts()
        provider_table_exists = await table_exists(PROVIDER_EMBEDDING_TABLE)
        report["provider_versioned_embedding_store"]["exists"] = provider_table_exists
        if provider_table_exists:
            provider_counts = await inspect_provider_embedding_counts()
            report["provider_versioned_embedding_store"]["columns"] = (
                await inspect_provider_embedding_columns()
            )
            report["provider_versioned_embedding_store"][
                "counts_by_provider_model_dimension_source_type"
            ] = provider_counts
            report["provider_versioned_embedding_store"][
                "missing_counts_by_source_type"
            ] = await inspect_provider_missing_counts()
            report["provider_versioned_embedding_store"]["openai_embeddings_exist"] = any(
                row["provider"] == "openai" and row["total_rows"] > 0
                for row in provider_counts
            )
            report["provider_versioned_embedding_store"]["huggingface_embeddings_exist"] = any(
                row["provider"] == "huggingface" and row["model"] == settings.embedding_model_id and row["total_rows"] > 0
                for row in provider_counts
            )
    except Exception as exc:
        report["database_access"] = {
            "ok": False,
            "error": str(exc),
            "error_type": type(exc).__name__,
        }

    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only inspection of taxonomy/template embedding storage."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of a compact text report.",
    )
    return parser


def render_text_report(report: Dict[str, Any]) -> str:
    lines = [
        "Embedding store inspection",
        "Mode: read-only",
        f"Active provider: {report['configuration'].get('active_provider', 'huggingface')}",
        f"MODEL_PROVIDER: {report['configuration'].get('model_provider')}",
        f"EMBEDDING_MODEL_ID: {report['configuration'].get('active_embedding_model', report['configuration'].get('legacy_hugging_face_embedding_model'))}",
        f"EMBEDDING_DIMENSION: {report['configuration'].get('active_expected_dimension', report['configuration'].get('legacy_hugging_face_embedding_dimension'))}",
        f"OpenAI legacy model: {report['configuration'].get('openai_embedding_model')}",
        (
            "Live HF embedding calls enabled: "
            f"{report['configuration']['live_hugging_face_embedding_calls_enabled']}"
        ),
        "",
    ]

    if not report["database_access"]["ok"]:
        lines.extend(
            [
                "Database access: unavailable",
                f"Error: {report['database_access']['error_type']}: {report['database_access']['error']}",
            ]
        )
        return "\n".join(lines)

    lines.append("Embedding columns:")
    for column in report["embedding_store"]["columns"]:
        lines.append(
            "  - {table_name}.{column_name}: {data_type} dimension={vector_dimension}".format(
                **column
            )
        )

    lines.append("")
    lines.append("Embedding row counts:")
    for count in report["embedding_store"]["counts"]:
        lines.append(
            "  - {table_name}: total={total_rows}, with_embedding={rows_with_embedding}, missing={rows_missing_embedding}".format(
                **count
            )
        )

    provider_store = report.get("provider_versioned_embedding_store", {})
    lines.append("")
    lines.append(
        f"Provider-versioned table: {provider_store.get('table')} exists={provider_store.get('exists')}"
    )
    if provider_store.get("exists"):
        lines.append("Provider-versioned columns:")
        for column in provider_store.get("columns", []):
            lines.append(
                "  - {column_name}: {data_type} dimension={vector_dimension}".format(
                    **column
                )
            )
        lines.append("Provider/model/dimension counts:")
        counts = provider_store.get("counts_by_provider_model_dimension_source_type", [])
        if counts:
            for count in counts:
                lines.append(
                    "  - {provider}/{model} dimension={dimension} source={source_type}: total={total_rows}, active={active_rows}".format(
                        **count
                    )
                )
        else:
            lines.append("  - none")
        lines.append("Missing active Hugging Face embeddings by source:")
        for count in provider_store.get("missing_counts_by_source_type", []):
            duplicate_note = ""
            if "source_records_total" in count:
                duplicate_note = (
                    f", raw_source_records={count['source_records_total']}"
                    f", duplicate_source_records={count.get('duplicate_source_records', 0)}"
                )
            lines.append(
                "  - {source_table}: source_total={source_total}, active_huggingface_sources={active_huggingface_embedded_sources}, missing={missing_huggingface_embeddings}{duplicate_note}".format(
                    duplicate_note=duplicate_note,
                    **count
                )
            )
        if provider_store.get("openai_embeddings_exist"):
            lines.append("OpenAI embeddings: present, inactive/legacy")
    lines.append("")
    lines.append(
        "Production semantic matcher: "
        + report["code_findings"]["production_semantic_matcher_behavior"]
    )

    return "\n".join(lines)


async def async_main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    report = await collect_embedding_store_report()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_text_report(report))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
