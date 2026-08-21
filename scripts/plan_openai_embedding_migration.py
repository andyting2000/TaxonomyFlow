import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.inspect_embedding_store import (
    LEGACY_HF_EMBEDDING_DIMENSION,
    LEGACY_HF_EMBEDDING_MODEL,
    collect_embedding_store_report,
)


REPORT_PATH = Path("reports/openai_embedding_migration_plan.json")


def _detected_dimensions(inspection_report: Dict[str, Any]) -> List[int]:
    dimensions = []
    for column in inspection_report.get("embedding_store", {}).get("columns", []):
        dimension = column.get("vector_dimension")
        if isinstance(dimension, int) and dimension not in dimensions:
            dimensions.append(dimension)
    return dimensions


def _schema_change_required(
    current_dimensions: List[int],
    target_dimension: Optional[int],
) -> Any:
    if target_dimension is None:
        return "unknown"
    if not current_dimensions:
        return "unknown"
    return target_dimension not in current_dimensions


def build_migration_plan(
    inspection_report: Dict[str, Any],
    target_dimension: Optional[int] = None,
) -> Dict[str, Any]:
    current_dimensions = _detected_dimensions(inspection_report)
    existing_column_dimension_compatibility = _schema_change_required(
        current_dimensions,
        target_dimension,
    )
    configured_openai_model = inspection_report.get("configuration", {}).get(
        "openai_embedding_model", ""
    )

    return {
        "feature": "13C",
        "mode": "planning_only",
        "mutates_database": False,
        "current_state": {
            "model_provider": inspection_report.get("configuration", {}).get(
                "model_provider"
            ),
            "openai_embedding_model_configured": configured_openai_model,
            "legacy_hugging_face_embedding_model": LEGACY_HF_EMBEDDING_MODEL,
            "legacy_hugging_face_embedding_dimension": LEGACY_HF_EMBEDDING_DIMENSION,
            "detected_vector_dimensions": current_dimensions,
            "embedding_tables": inspection_report.get("embedding_store", {}).get(
                "tables", []
            ),
            "embedding_columns": inspection_report.get("embedding_store", {}).get(
                "columns", []
            ),
            "embedding_counts": inspection_report.get("embedding_store", {}).get(
                "counts", []
            ),
            "database_access": inspection_report.get("database_access", {}),
            "openai_mode_live_hf_embeddings_enabled": inspection_report.get(
                "configuration", {}
            ).get("live_hugging_face_embedding_calls_enabled"),
            "embedding_code_findings": inspection_report.get("code_findings", {}),
        },
        "hf_legacy_embedding_dimension": LEGACY_HF_EMBEDDING_DIMENSION,
        "openai_embedding_model_configured": configured_openai_model,
        "target_dimension": target_dimension,
        "target_dimension_basis": (
            "unknown_without_live_adapter_metadata_or_explicit_local_config"
            if target_dimension is None
            else "provided_explicitly_to_planning_script"
        ),
        "existing_column_dimension_compatibility": (
            "unknown"
            if existing_column_dimension_compatibility == "unknown"
            else "incompatible"
            if existing_column_dimension_compatibility
            else "compatible"
        ),
        "schema_change_required": True,
        "schema_change_reason": (
            "The recommended provider-versioned embedding table requires a future schema migration. "
            "In-place use of existing vector columns remains dimension-compatibility unknown until "
            "OpenAI embedding dimension is verified locally."
        ),
        "strategy_evaluation": [
            {
                "strategy": "add_openai_embedding_column_alongside_legacy_column",
                "assessment": "possible_but_less_flexible",
                "pros": [
                    "Keeps rollback simple by preserving the legacy column.",
                    "Can be queried with a dedicated OpenAI vector index.",
                ],
                "cons": [
                    "Ties the table schema to one OpenAI model dimension.",
                    "Repeats schema work if the model or dimension changes.",
                ],
            },
            {
                "strategy": "add_provider_versioned_embedding_table",
                "assessment": "recommended",
                "pros": [
                    "Preserves legacy 1752-dimensional vectors unchanged.",
                    "Supports provider, model, dimension, and generated_at metadata.",
                    "Allows side-by-side quality comparison and rollback.",
                    "Avoids destructive in-place replacement.",
                ],
                "cons": [
                    "Requires a new table, query path, and indexes in a future implementation feature.",
                    "Requires explicit cutover logic after regression evidence.",
                ],
            },
            {
                "strategy": "rebuild_existing_vector_column_in_place",
                "assessment": "not_recommended",
                "pros": [
                    "Smallest apparent runtime query change after migration.",
                ],
                "cons": [
                    "Destructive unless a full backup/restore path is proven.",
                    "Breaks rollback and historical comparison.",
                    "Likely requires changing vector dimensions if OpenAI dimension differs.",
                ],
            },
            {
                "strategy": "keep_string_template_matching_until_regression_confirms_benefit",
                "assessment": "safe_baseline",
                "pros": [
                    "Matches current OpenAI mode behavior.",
                    "Avoids introducing vector migration risk before quality evidence.",
                ],
                "cons": [
                    "Does not regain semantic similarity benefits.",
                    "May leave coverage lower for labels that need semantic matching.",
                ],
            },
        ],
        "recommended_strategy": {
            "name": "provider_versioned_embedding_table",
            "summary": (
                "Add a new provider-versioned embedding table in a future feature, keyed by "
                "source concept/template identifier plus provider, model, dimension, and generated_at. "
                "Keep existing mbrs_taxonomy_tags.embedding and xml_template_fields.embedding unchanged "
                "until multi-PDF regression evidence supports cutover."
            ),
            "schema_change_required": True,
            "reason": (
                "The current schema hardcodes vector(1752) for legacy Hugging Face embeddings. "
                "OpenAI target dimension is not proven locally in this planning feature, and even if "
                "compatible, provider-versioned storage gives safer rollback and comparison."
            ),
        },
        "rollback_strategy": [
            "Do not drop or overwrite existing 1752-dimensional embedding columns.",
            "Keep OpenAI embedding query path behind MODEL_PROVIDER/openai embedding feature flags until validated.",
            "Retain current string/template matching fallback as the safe OpenAI-mode rollback path.",
            "If OpenAI semantic matching regresses quality, disable the new provider-versioned query path without data loss.",
        ],
        "data_migration_steps": [
            "Create a future migration for provider-versioned embedding storage; do not change schema in #13C.",
            "Backfill OpenAI embeddings for mbrs_taxonomy_tags labels/xbrl_tag text into the new table.",
            "Optionally backfill xml_template_fields labels/xbrl_tag text if that table remains in active matching.",
            "Record provider='openai', model, dimension, source_table, source_id or source_key, source_text_hash, generated_at.",
            "Build a pgvector index appropriate to the detected OpenAI dimension after dimension is verified.",
            "Run side-by-side matching quality reports before enabling OpenAI embedding search in production matching.",
        ],
        "quality_comparison_plan": {
            "representative_jobs_or_pdfs": [
                "Use at least 3-5 processed jobs/PDFs; include job 11 because OpenAI extraction is known to reach REVIEW.",
                "Include at least one statement-of-financial-position-heavy PDF.",
                "Include at least one notes-heavy PDF.",
                "Include at least one PDF with detail rows that previously triggered guardrails.",
            ],
            "baseline_modes": [
                "current_openai_mode_string_template_matching",
                "legacy_hf_embedding_matching_if_available_as_read_only_baseline",
                "future_openai_embedding_matching_shadow_mode",
            ],
            "metrics": [
                "rows_with_template_field_id",
                "rows_without_template_field_id",
                "blank_statement_type_count",
                "duplicate_concept_groups",
                "suspicious_broad_mappings",
                "manual_review_count",
                "generated_xbrl_audit_findings",
                "guardrail_block_count",
            ],
            "acceptance_gate": (
                "Do not cut over to OpenAI semantic matching unless it improves or preserves "
                "mapping correctness across multiple PDFs without increasing broad/unsafe mappings."
            ),
        },
        "implementation_slices": [
            {
                "feature": "13D",
                "name": "OpenAI embedding store implementation",
                "scope": "schema migration plus read/write OpenAI embedding backfill path, still shadow-only",
            },
            {
                "feature": "13E",
                "name": "OpenAI semantic matcher shadow comparison",
                "scope": "side-by-side current vs OpenAI embedding matching reports across multiple PDFs",
            },
            {
                "feature": "13F",
                "name": "OpenAI semantic matcher guarded cutover",
                "scope": "production matching switch only after regression evidence and rollback control",
            },
        ],
        "non_goals_confirmed": [
            "No database schema change in #13C.",
            "No embedding regeneration in #13C.",
            "No production semantic matcher behavior change in #13C.",
            "No extraction, mapping, generated XBRL, Arelle, React, auth, or backend route changes in #13C.",
        ],
    }


async def build_report(target_dimension: Optional[int] = None) -> Dict[str, Any]:
    inspection = await collect_embedding_store_report()
    return build_migration_plan(inspection, target_dimension=target_dimension)


def write_report(report: Dict[str, Any], output_path: Path = REPORT_PATH) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return output_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a planning-only OpenAI embedding migration report."
    )
    parser.add_argument(
        "--output",
        default=str(REPORT_PATH),
        help="JSON report path. Defaults to reports/openai_embedding_migration_plan.json.",
    )
    parser.add_argument(
        "--target-dimension",
        type=int,
        default=None,
        help="Optional known OpenAI embedding dimension. Omit to keep target dimension unknown.",
    )
    return parser


async def async_main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    report = await build_report(target_dimension=args.target_dimension)
    output_path = write_report(report, Path(args.output))
    print(f"Wrote planning-only report: {output_path}")
    print(f"Recommended strategy: {report['recommended_strategy']['name']}")
    print(f"Schema change required: {report['schema_change_required']}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
