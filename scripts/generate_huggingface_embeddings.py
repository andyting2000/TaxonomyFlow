import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

import numpy as np
from huggingface_hub import AsyncInferenceClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings
from scripts.generate_openai_embeddings import (
    SOURCE_ALL,
    SOURCE_DB_TAXONOMY_TAGS,
    SOURCE_DB_TEMPLATE_FIELDS,
    SOURCE_MPERS_TEMPLATE_CONCEPTS,
    SOURCE_TEMPLATE_SERVICE_CONCEPTS,
    SOURCE_TAXONOMY_TAGS,
    SOURCE_XML_TEMPLATE_FIELDS,
    chunked,
    default_report_path as _openai_default_report_path,
    embedding_hash,
    existing_embedding_keys,
    fetch_source_records,
    upsert_embedding_record,
)


PROVIDER = "huggingface"
PLACEHOLDER_TOKENS = {"", "replace-with-your-model-provider-token", "YOUR_MODEL_API_TOKEN_HERE"}


@dataclass(frozen=True)
class HuggingFaceEmbeddingConfig:
    token: str
    model: str
    expected_dimension: Optional[int] = None
    normalize: bool = True


def load_huggingface_embedding_config(settings_obj: Any = settings) -> HuggingFaceEmbeddingConfig:
    return HuggingFaceEmbeddingConfig(
        token=str(getattr(settings_obj, "model_api_token", "") or getattr(settings_obj, "hugging_face_token", "") or "").strip(),
        model=str(getattr(settings_obj, "embedding_model_id", "Qwen/Qwen3-Embedding-8B") or "").strip(),
        expected_dimension=getattr(settings_obj, "embedding_dimension", None),
        normalize=bool(getattr(settings_obj, "embedding_normalize", True)),
    )


def is_huggingface_configured(config: Optional[HuggingFaceEmbeddingConfig] = None) -> bool:
    config = config or load_huggingface_embedding_config()
    return config.token not in PLACEHOLDER_TOKENS


def normalize_embedding(value: Any, *, normalize: bool = True) -> List[float]:
    array = np.array(value, dtype=float)
    if array.ndim == 0:
        raise ValueError("Embedding response did not contain a vector.")
    if array.ndim > 1:
        array = array.mean(axis=0)
    if normalize:
        norm = np.linalg.norm(array)
        if norm > 0:
            array = array / norm
    return array.astype(float).tolist()


async def huggingface_embeddings(
    inputs: Union[str, Sequence[str]],
    *,
    client: Any = None,
    config: Optional[HuggingFaceEmbeddingConfig] = None,
) -> Dict[str, Any]:
    config = config or load_huggingface_embedding_config()
    input_list = [inputs] if isinstance(inputs, str) else list(inputs)
    if not input_list:
        return {
            "ok": False,
            "provider": PROVIDER,
            "operation": "embedding",
            "error_type": "empty_input",
            "error": "At least one input string is required for Hugging Face embeddings.",
            "model": config.model,
        }
    if not is_huggingface_configured(config):
        return {
            "ok": False,
            "provider": PROVIDER,
            "operation": "embedding",
            "error_type": "configuration",
            "error": "MODEL_API_TOKEN is required when --apply would generate Hugging Face embeddings.",
            "model": config.model,
        }

    try:
        client = client or AsyncInferenceClient(model=config.model, token=config.token)
        embeddings = []
        for text in input_list:
            response = await client.feature_extraction(str(text))
            embeddings.append(normalize_embedding(response, normalize=config.normalize))
    except Exception as exc:
        return {
            "ok": False,
            "provider": PROVIDER,
            "operation": "embedding",
            "error_type": type(exc).__name__,
            "error": str(exc).replace(config.token, "[redacted]") if config.token else str(exc),
            "model": config.model,
        }

    dimensions = sorted({len(vector) for vector in embeddings})
    return {
        "ok": bool(embeddings),
        "provider": PROVIDER,
        "operation": "embedding",
        "model": config.model,
        "dimensions": dimensions[0] if len(dimensions) == 1 else None,
        "dimension_values": dimensions,
        "expected_dimension": config.expected_dimension,
        "embedding_count": len(embeddings),
        "embeddings": embeddings,
    }


def default_report_path() -> Path:
    return _openai_default_report_path("huggingface_embedding_generation")


async def discover_dimension(config: Optional[HuggingFaceEmbeddingConfig] = None) -> Dict[str, Any]:
    result = await huggingface_embeddings("dimension check", config=config or load_huggingface_embedding_config())
    if not result.get("ok"):
        return {
            "ok": False,
            "provider": PROVIDER,
            "model": result.get("model"),
            "dimension": None,
            "expected_dimension": result.get("expected_dimension"),
            "error_type": result.get("error_type"),
            "error": result.get("error"),
        }
    return {
        "ok": True,
        "provider": PROVIDER,
        "model": result["model"],
        "dimension": result.get("dimensions"),
        "expected_dimension": result.get("expected_dimension"),
        "embedding_count": result.get("embedding_count"),
    }


async def run_generation(args: argparse.Namespace) -> Dict[str, Any]:
    config = load_huggingface_embedding_config()
    source_records = await fetch_source_records(args.source, args.limit)
    existing_keys = await existing_embedding_keys(
        source_records,
        provider=PROVIDER,
        model=config.model,
    )
    pending_records = [
        record
        for record in source_records
        if args.force or (record.source_type, record.source_id, record.source_text_hash) not in existing_keys
    ]

    report: Dict[str, Any] = {
        "feature": "13P",
        "mode": "apply" if args.apply else "dry_run",
        "mutates_database": bool(args.apply),
        "provider": PROVIDER,
        "model": config.model,
        "expected_dimension": config.expected_dimension,
        "normalize": config.normalize,
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
        "production_data_changed": False,
    }

    if args.discover_dimension:
        report["dimension_discovery"] = await discover_dimension(config)

    if not args.apply:
        return report

    if not pending_records:
        return report

    if not is_huggingface_configured(config):
        report["errors"].append(
            {
                "error_type": "configuration",
                "error": "MODEL_API_TOKEN is required when --apply would generate Hugging Face embeddings.",
            }
        )
        return report

    batch_size = max(1, args.batch_size)
    retry_count = max(0, args.max_retries)
    for batch in chunked(pending_records, batch_size):
        response: Dict[str, Any] = {}
        for attempt in range(retry_count + 1):
            response = await huggingface_embeddings([record.source_text for record in batch], config=config)
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
                    "error_type": response.get("error_type", "HuggingFaceEmbeddingError"),
                    "error": response.get("error", "Hugging Face embedding request failed."),
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
                    model=config.model,
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
            report["production_data_changed"] = True
            if action == "inserted":
                report["inserted"] += 1
            elif action == "updated":
                report["updated"] += 1
            elif action == "skipped_existing":
                report["skipped_existing"] += 1
        report["completed_batches"] += 1
        if args.sleep_between_batches > 0:
            await asyncio.sleep(args.sleep_between_batches)

    report["dimension_values"].sort()
    return report


def write_report(report: Dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return output_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate Hugging Face semantic embeddings into the provider-versioned store."
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
    )
    parser.add_argument("--limit", type=int, default=None, help="Optional source record limit.")
    parser.add_argument("--batch-size", type=int, default=20, help="Hugging Face embedding batch size.")
    parser.add_argument("--sleep-between-batches", type=float, default=0.0)
    parser.add_argument("--max-retries", type=int, default=settings.hf_inference_max_retries)
    parser.add_argument("--force", action="store_true", help="Regenerate rows even when provider/model/source/hash exists.")
    parser.add_argument("--apply", action="store_true", help="Write embeddings to semantic_embeddings. Dry-run is default.")
    parser.add_argument("--discover-dimension", action="store_true")
    parser.add_argument("--output", default=None)
    return parser


async def async_main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    report = await run_generation(args)
    output_path = Path(args.output) if args.output else default_report_path()
    write_report(report, output_path)

    print(f"Hugging Face embedding generation report: {output_path}")
    print(f"Mode: {report['mode']}")
    print(f"Provider: {report['provider']}")
    print(f"Model: {report['model']}")
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
