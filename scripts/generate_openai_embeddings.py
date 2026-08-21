import argparse
import asyncio
import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings
from database import (
    AsyncSessionLocal,
    MBRSTaxonomyTag,
    SemanticEmbedding,
    XMLTemplateField,
)
from services.openai_provider import (
    OpenAIProviderConfig,
    is_openai_configured,
    load_openai_config,
    openai_embeddings,
)
from services.xbrl_template_service import get_xbrl_template_service


SOURCE_DB_TAXONOMY_TAGS = "db-taxonomy-tags"
SOURCE_DB_TEMPLATE_FIELDS = "db-template-fields"
SOURCE_TEMPLATE_SERVICE_CONCEPTS = "template-service-concepts"
SOURCE_MPERS_TEMPLATE_CONCEPTS = "mpers-template-concepts"
SOURCE_TAXONOMY_TAGS = "taxonomy-tags"
SOURCE_XML_TEMPLATE_FIELDS = "xml-template-fields"
SOURCE_ALL = "all"
SOURCE_TYPE_TAXONOMY_TAG = "mbrs_taxonomy_tag"
SOURCE_TYPE_XML_TEMPLATE_FIELD = "xml_template_field"
SOURCE_TYPE_TEMPLATE_SERVICE_CONCEPT = "template_service_concept"
SOURCE_TYPE_MPERS_TEMPLATE_CONCEPT = "mpers_template_concept"
PROVIDER = "openai"
DEFAULT_REPORT_DIR = Path("reports")
MPERS_TEMPLATE_PATH = Path("mpers_templates.json")


@dataclass(frozen=True)
class EmbeddingSourceRecord:
    source_type: str
    source_id: str
    source_label: str
    source_text: str
    source_text_hash: str
    metadata: Dict[str, Any] = field(default_factory=dict)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def embedding_hash(embedding: Sequence[float]) -> str:
    stable = ",".join(f"{float(value):.12g}" for value in embedding)
    return sha256_text(stable)


def build_taxonomy_source_text(tag: MBRSTaxonomyTag) -> str:
    parts = [
        f"Label: {tag.label}",
        f"XBRL tag: {tag.xbrl_tag}",
        f"Namespace: {tag.namespace}",
        f"Period type: {tag.period_type}",
    ]
    return "\n".join(part for part in parts if part and not part.endswith(": None"))


def build_template_field_source_text(field: XMLTemplateField) -> str:
    parts = [
        f"Label: {field.label}",
        f"Field id: {field.field_id}",
        f"XBRL tag: {field.xbrl_tag}",
        f"Statement code: {field.statement_code}",
        f"Statement type: {field.statement_type}",
        f"Level: {field.level}",
        f"Required: {field.required}",
    ]
    return "\n".join(part for part in parts if part and not part.endswith(": None"))


def build_template_concept_source_text(record: Dict[str, Any]) -> str:
    aliases = record.get("aliases") or []
    aliases_text = ", ".join(str(alias) for alias in aliases if str(alias).strip())
    parts = [
        f"Statement: {record.get('statement_description')}",
        f"Template code: {record.get('template_code')}",
        f"Concept label: {record.get('concept_label')}",
        f"Concept id: {record.get('concept_id')}",
        f"Namespace: {record.get('namespace')}",
        f"Parent: {record.get('parent')}",
        f"Level: {record.get('level')}",
        f"Required: {record.get('required')}",
        f"Aliases: {aliases_text}" if aliases_text else None,
    ]
    return "\n".join(
        str(part)
        for part in parts
        if part is not None and not str(part).endswith(": None")
    )


def source_record_from_taxonomy_tag(tag: MBRSTaxonomyTag) -> EmbeddingSourceRecord:
    source_text = build_taxonomy_source_text(tag)
    return EmbeddingSourceRecord(
        source_type=SOURCE_TYPE_TAXONOMY_TAG,
        source_id=str(tag.id),
        source_label=str(tag.label or ""),
        source_text=source_text,
        source_text_hash=sha256_text(source_text),
        metadata={
            "xbrl_tag": tag.xbrl_tag,
            "namespace": tag.namespace,
            "period_type": tag.period_type,
        },
    )


def source_record_from_template_field(field: XMLTemplateField) -> EmbeddingSourceRecord:
    source_text = build_template_field_source_text(field)
    return EmbeddingSourceRecord(
        source_type=SOURCE_TYPE_XML_TEMPLATE_FIELD,
        source_id=str(field.id),
        source_label=str(field.label or ""),
        source_text=source_text,
        source_text_hash=sha256_text(source_text),
        metadata={
            "field_id": field.field_id,
            "xbrl_tag": field.xbrl_tag,
            "statement_code": field.statement_code,
            "statement_type": field.statement_type,
            "level": field.level,
            "required": field.required,
        },
    )


def source_record_from_template_concept(
    record: Dict[str, Any],
    *,
    source_type: str = SOURCE_TYPE_TEMPLATE_SERVICE_CONCEPT,
) -> EmbeddingSourceRecord:
    source_text = build_template_concept_source_text(record)
    return EmbeddingSourceRecord(
        source_type=source_type,
        source_id=str(record["source_id"]),
        source_label=str(record.get("concept_label") or ""),
        source_text=source_text,
        source_text_hash=sha256_text(source_text),
        metadata=dict(record),
    )


def template_service_source_records() -> List[EmbeddingSourceRecord]:
    service = get_xbrl_template_service()
    return [
        source_record_from_template_concept(record)
        for record in service.get_embedding_source_concepts()
    ]


def mpers_template_json_source_records(path: Path = MPERS_TEMPLATE_PATH) -> List[EmbeddingSourceRecord]:
    if not path.exists():
        return []

    data = json.loads(path.read_text(encoding="utf-8"))
    records = []
    for template_code in sorted((data.get("templates") or {}).keys()):
        template = data["templates"][template_code]
        statement_description = template.get("description", template_code)
        for concept in template.get("concepts", []):
            source = {
                "source_type": SOURCE_TYPE_MPERS_TEMPLATE_CONCEPT,
                "source_id": f"{template_code}:{concept.get('id', '')}",
                "template_code": template_code,
                "statement_description": statement_description,
                "concept_id": concept.get("id", ""),
                "concept_label": concept.get("label", ""),
                "namespace": concept.get("namespace"),
                "level": concept.get("level"),
                "parent": concept.get("parent"),
                "required": concept.get("required", False),
                "position": concept.get("position", 0),
                "aliases": concept.get("aliases") or [],
            }
            records.append(
                source_record_from_template_concept(
                    source,
                    source_type=SOURCE_TYPE_MPERS_TEMPLATE_CONCEPT,
                )
            )
    return records


def chunked(values: Sequence[EmbeddingSourceRecord], size: int) -> Iterable[Sequence[EmbeddingSourceRecord]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]


def default_report_path(prefix: str = "openai_embedding_generation") -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return DEFAULT_REPORT_DIR / f"{prefix}_{timestamp}.json"


async def fetch_source_records(source: str, limit: Optional[int] = None) -> List[EmbeddingSourceRecord]:
    records: List[EmbeddingSourceRecord] = []

    def append_limited(new_records: List[EmbeddingSourceRecord]) -> None:
        if limit and source == SOURCE_ALL:
            remaining = max(0, limit - len(records))
            records.extend(new_records[:remaining])
        else:
            records.extend(new_records[:limit] if limit else new_records)

    async with AsyncSessionLocal() as session:
        if source in {SOURCE_DB_TAXONOMY_TAGS, SOURCE_TAXONOMY_TAGS, SOURCE_ALL}:
            stmt = select(MBRSTaxonomyTag).order_by(MBRSTaxonomyTag.id)
            if limit and source != SOURCE_ALL:
                stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            append_limited(
                [source_record_from_taxonomy_tag(tag) for tag in result.scalars().all()]
            )

        if not limit or source != SOURCE_ALL or len(records) < limit:
            should_fetch_template_fields = source in {
                SOURCE_DB_TEMPLATE_FIELDS,
                SOURCE_XML_TEMPLATE_FIELDS,
                SOURCE_ALL,
            }
        else:
            should_fetch_template_fields = False

        if should_fetch_template_fields:
            stmt = select(XMLTemplateField).order_by(XMLTemplateField.id)
            if limit and source != SOURCE_ALL:
                stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            append_limited(
                [source_record_from_template_field(field) for field in result.scalars().all()]
            )

    if (not limit or source != SOURCE_ALL or len(records) < limit) and source in {
        SOURCE_TEMPLATE_SERVICE_CONCEPTS,
        SOURCE_ALL,
    }:
        append_limited(template_service_source_records())

    if source == SOURCE_MPERS_TEMPLATE_CONCEPTS:
        append_limited(mpers_template_json_source_records())

    if limit and source == SOURCE_ALL:
        return records[:limit]
    return records


async def existing_embedding_keys(
    records: Sequence[EmbeddingSourceRecord],
    *,
    provider: str,
    model: str,
) -> set[tuple[str, str, str]]:
    if not records:
        return set()

    keys = set()
    async with AsyncSessionLocal() as session:
        for record in records:
            result = await session.execute(
                select(SemanticEmbedding).where(
                    SemanticEmbedding.provider == provider,
                    SemanticEmbedding.model == model,
                    SemanticEmbedding.source_type == record.source_type,
                    SemanticEmbedding.source_id == record.source_id,
                    SemanticEmbedding.source_text_hash == record.source_text_hash,
                )
            )
            if result.scalar_one_or_none() is not None:
                keys.add((record.source_type, record.source_id, record.source_text_hash))
    return keys


async def upsert_embedding_record(
    record: EmbeddingSourceRecord,
    embedding: Sequence[float],
    *,
    provider: str,
    model: str,
    force: bool = False,
) -> str:
    dimension = len(embedding)
    vector = [float(value) for value in embedding]

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SemanticEmbedding).where(
                SemanticEmbedding.provider == provider,
                SemanticEmbedding.model == model,
                SemanticEmbedding.source_type == record.source_type,
                SemanticEmbedding.source_id == record.source_id,
                SemanticEmbedding.source_text_hash == record.source_text_hash,
            )
        )
        existing = result.scalar_one_or_none()
        if existing and not force:
            return "skipped_existing"

        if existing:
            existing.source_label = record.source_label
            existing.source_text = record.source_text
            existing.dimension = dimension
            existing.embedding = vector
            existing.embedding_hash = embedding_hash(vector)
            existing.is_active = True
            existing.updated_at = datetime.utcnow()
            action = "updated"
        else:
            session.add(
                SemanticEmbedding(
                    source_type=record.source_type,
                    source_id=record.source_id,
                    source_label=record.source_label,
                    source_text=record.source_text,
                    provider=provider,
                    model=model,
                    dimension=dimension,
                    embedding=vector,
                    source_text_hash=record.source_text_hash,
                    embedding_hash=embedding_hash(vector),
                    is_active=True,
                )
            )
            action = "inserted"

        await session.commit()
        return action


async def discover_dimension(config: Optional[OpenAIProviderConfig] = None) -> Dict[str, Any]:
    result = openai_embeddings(
        "dimension check",
        config=config or load_openai_config(),
    )
    if not result.get("ok"):
        return {
            "ok": False,
            "provider": PROVIDER,
            "model": result.get("model"),
            "dimension": None,
            "error_type": result.get("error_type"),
            "error": result.get("error"),
        }
    return {
        "ok": True,
        "provider": PROVIDER,
        "model": result["model"],
        "dimension": result.get("dimensions"),
        "embedding_count": result.get("embedding_count"),
        "usage": result.get("usage"),
    }


async def run_generation(args: argparse.Namespace) -> Dict[str, Any]:
    config = load_openai_config()
    source_records = await fetch_source_records(args.source, args.limit)
    existing_keys = await existing_embedding_keys(
        source_records,
        provider=PROVIDER,
        model=config.embedding_model,
    )
    pending_records = [
        record for record in source_records
        if args.force or (record.source_type, record.source_id, record.source_text_hash) not in existing_keys
    ]

    report: Dict[str, Any] = {
        "feature": "13F",
        "mode": "apply" if args.apply else "dry_run",
        "mutates_database": bool(args.apply),
        "provider": PROVIDER,
        "model": config.embedding_model,
        "source": args.source,
        "limit": args.limit,
        "batch_size": args.batch_size,
        "sleep_between_batches": args.sleep_between_batches,
        "max_retries": args.max_retries,
        "force": bool(args.force),
        "source_records": len(source_records),
        "source_records_by_type": {
            source_type: sum(1 for record in source_records if record.source_type == source_type)
            for source_type in sorted({record.source_type for record in source_records})
        },
        "existing_embeddings": len(existing_keys),
        "would_generate": len(pending_records),
        "generated": 0,
        "inserted": 0,
        "updated": 0,
        "failed": 0,
        "failed_source_ids": [],
        "skipped_existing": len(source_records) - len(pending_records),
        "completed_batches": 0,
        "failed_batches": 0,
        "dimension_values": [],
        "dimension_discovery": None,
        "errors": [],
        "legacy_columns_written": False,
        "production_matcher_changed": False,
    }

    if args.discover_dimension:
        report["dimension_discovery"] = await discover_dimension(config)

    if not args.apply:
        return report

    if not pending_records:
        return report

    if not is_openai_configured(config):
        report["errors"].append(
            {
                "error_type": "configuration",
                "error": "OPENAI_API_KEY is required when --apply would generate embeddings.",
            }
        )
        return report

    batch_size = max(1, args.batch_size)
    retry_count = max(0, args.max_retries)
    for batch in chunked(pending_records, batch_size):
        response: Dict[str, Any] = {}
        for attempt in range(retry_count + 1):
            response = openai_embeddings([record.source_text for record in batch], config=config)
            if response.get("ok"):
                break
            if attempt < retry_count and args.sleep_between_batches > 0:
                await asyncio.sleep(args.sleep_between_batches)

        if not response.get("ok"):
            failed_ids = [record.source_id for record in batch]
            report["failed"] += len(batch)
            report["failed_batches"] += 1
            report["failed_source_ids"].extend(failed_ids)
            report["errors"].append(
                {
                    "error_type": response.get("error_type", "OpenAIEmbeddingError"),
                    "error": response.get("error", "OpenAI embedding request failed."),
                    "source_ids": failed_ids,
                }
            )
            continue

        embeddings = response.get("embeddings", [])
        if len(embeddings) != len(batch):
            failed_ids = [record.source_id for record in batch]
            report["failed"] += len(batch)
            report["failed_batches"] += 1
            report["failed_source_ids"].extend(failed_ids)
            report["errors"].append(
                {
                    "error_type": "embedding_count_mismatch",
                    "error": f"Expected {len(batch)} embeddings but received {len(embeddings)}.",
                    "source_ids": failed_ids,
                }
            )
            continue

        for record, vector in zip(batch, embeddings):
            try:
                action = await upsert_embedding_record(
                    record,
                    vector,
                    provider=PROVIDER,
                    model=config.embedding_model,
                    force=args.force,
                )
            except Exception as exc:
                report["failed"] += 1
                report["failed_source_ids"].append(record.source_id)
                report["errors"].append(
                    {
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "source_ids": [record.source_id],
                    }
                )
                continue

            report["generated"] += 1
            dimension = len(vector)
            if dimension not in report["dimension_values"]:
                report["dimension_values"].append(dimension)
            if action == "inserted":
                report["inserted"] += 1
            elif action == "updated":
                report["updated"] += 1
            elif action == "skipped_existing":
                report["skipped_existing"] += 1
        report["completed_batches"] += 1
        if args.sleep_between_batches > 0:
            await asyncio.sleep(args.sleep_between_batches)

    return report


def write_report(report: Dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return output_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate OpenAI semantic embeddings into the shadow provider-versioned store."
    )
    parser.add_argument(
        "--source",
        choices=[
            SOURCE_DB_TAXONOMY_TAGS,
            SOURCE_DB_TEMPLATE_FIELDS,
            SOURCE_TEMPLATE_SERVICE_CONCEPTS,
            SOURCE_MPERS_TEMPLATE_CONCEPTS,
            SOURCE_TAXONOMY_TAGS,
            SOURCE_XML_TEMPLATE_FIELDS,
            SOURCE_ALL,
        ],
        default=SOURCE_ALL,
        help=(
            "Source records to inspect or embed. Defaults to all. "
            "taxonomy-tags/xml-template-fields are legacy aliases for db-* sources."
        ),
    )
    parser.add_argument("--limit", type=int, default=None, help="Optional source record limit.")
    parser.add_argument("--batch-size", type=int, default=50, help="OpenAI embedding batch size.")
    parser.add_argument(
        "--sleep-between-batches",
        type=float,
        default=0.0,
        help="Optional delay in seconds between successful batches and retry attempts.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="Retry failed OpenAI embedding batches this many times before marking them failed.",
    )
    parser.add_argument("--force", action="store_true", help="Regenerate rows even when provider/model/source/hash exists.")
    parser.add_argument("--apply", action="store_true", help="Write embeddings to semantic_embeddings. Dry-run is default.")
    parser.add_argument(
        "--discover-dimension",
        action="store_true",
        help="Call OpenAI with a tiny input and report the returned embedding dimension.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="JSON report path. Defaults to reports/openai_embedding_generation_<timestamp>.json.",
    )
    return parser


async def async_main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    report = await run_generation(args)
    output_path = Path(args.output) if args.output else default_report_path()
    write_report(report, output_path)

    print(f"OpenAI embedding generation report: {output_path}")
    print(f"Mode: {report['mode']}")
    print(f"Source records: {report['source_records']}")
    print(f"Would generate: {report['would_generate']}")
    if report.get("dimension_discovery"):
        discovery = report["dimension_discovery"]
        print(f"Dimension discovery: {discovery.get('dimension')} ({'ok' if discovery.get('ok') else 'skipped/failed'})")
    if report["errors"]:
        print(f"Errors: {len(report['errors'])}")
        return 1 if args.apply else 0
    if args.apply:
        print(
            "Inserted: {inserted}; Updated: {updated}; Generated: {generated}; "
            "Skipped: {skipped_existing}; Failed: {failed}".format(**report)
        )
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
