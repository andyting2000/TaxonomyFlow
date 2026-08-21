import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

from sqlalchemy import case, func, select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from database import AsyncSessionLocal, ExtractedDataItem, FilingJob, FinancialStatementPage
from scripts.validate_xbrl_arelle import DEFAULT_TAXONOMY_ENTRYPOINT, VALIDATION_MODE_ARGS
from services.arelle_validator import DEFAULT_TIMEOUT_SECONDS, local_schema_ref_remaps, validate_with_arelle
from services.xbrl_generator import generate_xbrl_for_job


DIAGNOSTIC_CATEGORIES = [
    "taxonomy_resolution_errors",
    "schemaRef_issues",
    "missing_contexts",
    "duplicate_facts",
    "invalid_concept_names",
    "namespace_issues",
    "unit_issues",
    "calculation_issues",
    "other",
]


COMPARISON_MODES = ["full", "no_formula", "instance_focused", "skip_formula_table"]
BASELINE_EXPERIMENT_MODES = ["skip_formula_table", "instance_baseline"]
TAXONOMY_METADATA_PATTERNS = (
    ".taxonomyPackage.xml",
    "taxonomyPackage.xml",
    "catalog.xml",
)


def _as_dict(value: Any) -> Dict[str, Any]:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return value
    return dict(value)


def _diagnostic_lines(validation: Dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for key in ("errors", "warnings"):
        for item in validation.get(key) or []:
            text = str(item).strip()
            if text:
                lines.append(text)
    for line in str(validation.get("raw_output") or "").splitlines():
        text = line.strip()
        if text.lower().startswith("[info]"):
            continue
        if text and text not in lines:
            lines.append(text)
    return lines


def classify_diagnostics(validation: Dict[str, Any]) -> Dict[str, list[str]]:
    categories = {name: [] for name in DIAGNOSTIC_CATEGORIES}

    for line in _diagnostic_lines(validation):
        lowered = line.lower()
        matched = False

        checks = [
            (
                "taxonomy_resolution_errors",
                r"entry[ -]?point|dts|download|resolv|retriev|web cache|schemaimportmissing|could not load|ioerror",
            ),
            ("schemaRef_issues", r"schemaref|schema ref|mbrs\.ssm\.com\.my/taxonomy"),
            ("missing_contexts", r"contextref|context\b|missing context"),
            ("duplicate_facts", r"duplicate"),
            ("invalid_concept_names", r"concept|qname|element.*invalid|invalid.*element"),
            ("namespace_issues", r"namespace prefix|undeclared prefix|prefix .*not|namespace .*not|unknown namespace"),
            ("unit_issues", r"unitref|unit\b|measure"),
            ("calculation_issues", r"calculation|\bcalc\b|inconsistency"),
        ]

        for category, pattern in checks:
            if re.search(pattern, lowered):
                categories[category].append(line)
                matched = True

        if not matched:
            categories["other"].append(line)

    return categories


def classify_error_family(line: str) -> str:
    lowered = line.lower()
    if "formula_ssmt-fs-mpers" in lowered or "err:xpst0003" in lowered or "qnameexpression" in lowered:
        return "taxonomy_artifact_compatibility"
    if "table_ssmt-fs-mpers" in lowered or "xbrlte:abstractrulenodenochildren" in lowered:
        return "taxonomy_artifact_compatibility"
    if "schemaref" in lowered or "schemaimportmissing" in lowered or "could not load" in lowered or "ioerror" in lowered:
        return "arelle_mode_or_plugin_noise"
    if re.search(r"contextref|missing context|duplicate|unitref|calculation|invalid.*fact", lowered):
        return "generated_instance_defect"
    return "unknown"


def family_summary(validation: Dict[str, Any]) -> Dict[str, Any]:
    families = {
        "taxonomy_artifact_compatibility": [],
        "arelle_mode_or_plugin_noise": [],
        "generated_instance_defect": [],
        "unknown": [],
    }
    for line in _diagnostic_lines(validation):
        family = classify_error_family(line)
        if line not in families[family]:
            families[family].append(line)
    return {
        name: {
            "count": len(lines),
            "examples": lines[:10],
        }
        for name, lines in families.items()
    }


def taxonomy_resolution_status(categories: Dict[str, list[str]]) -> str:
    if categories["schemaRef_issues"]:
        return "failed_or_questionable"
    taxonomy_lines = "\n".join(categories["taxonomy_resolution_errors"]).lower()
    if "ioerror" in taxonomy_lines or "could not load" in taxonomy_lines:
        return "failed_or_questionable"
    return "no_taxonomy_resolution_error_detected"


def schema_ref_future_change_required(categories: Dict[str, list[str]]) -> bool:
    combined = "\n".join(
        categories["taxonomy_resolution_errors"] + categories["schemaRef_issues"]
    ).lower()
    return bool(combined)


def summarize_mode(validation: Dict[str, Any]) -> Dict[str, Any]:
    categories = classify_diagnostics(validation)
    diagnostic_text = "\n".join(_diagnostic_lines(validation))
    families = family_summary(validation)
    return {
        "is_valid": bool(validation.get("is_valid")),
        "return_code": validation.get("return_code"),
        "command_used": validation.get("command_used"),
        "taxonomy_resolution_status": taxonomy_resolution_status(categories),
        "diagnostic_counts": {name: len(lines) for name, lines in categories.items()},
        "formula_table_diagnostics_remain": any(
            token in diagnostic_text
            for token in (
                "formula_ssmt-fs-mpers",
                "table_ssmt-fs-mpers",
                "xbrlte:abstractRuleNodeNoChildren",
                "err:XPST0003",
            )
        ),
        "taxonomy_artifact_noise_remains": bool(families["taxonomy_artifact_compatibility"]["count"]),
        "generated_instance_defects_visible": bool(families["generated_instance_defect"]["count"]),
        "error_families": families,
    }


def validation_mode_recommendation(mode_summaries: Dict[str, Dict[str, Any]]) -> str:
    skip_table = mode_summaries.get("skip_formula_table", {})
    instance = mode_summaries.get("instance_focused", {})
    if not skip_table.get("formula_table_diagnostics_remain") and skip_table.get("generated_instance_defects_visible"):
        return "Use skip_formula_table or an equivalent instance-focused mode next to triage generated-instance mapping defects."
    if not skip_table.get("formula_table_diagnostics_remain") and not skip_table.get("generated_instance_defects_visible"):
        return "Use skip_formula_table next to establish a quieter baseline, then add targeted generated-instance mapping checks."
    if instance.get("formula_table_diagnostics_remain"):
        return "Formula/table taxonomy artifacts still dominate available modes; Feature #11F should decide a supported Arelle mode or taxonomy package strategy before mapping fixes."
    return "Continue with the quietest passing mode for generated-instance diagnostics."


async def find_review_job_with_template_coverage(session_factory=AsyncSessionLocal) -> Optional[Dict[str, Any]]:
    async with session_factory() as session:
        template_count = func.sum(
            case((ExtractedDataItem.template_field_id.is_not(None), 1), else_=0)
        )
        stmt = (
            select(
                FilingJob.id,
                FilingJob.company_name,
                FilingJob.status,
                func.count(ExtractedDataItem.id).label("extracted_rows"),
                template_count.label("template_field_rows"),
            )
            .join(FinancialStatementPage, FinancialStatementPage.job_id == FilingJob.id)
            .join(ExtractedDataItem, ExtractedDataItem.page_id == FinancialStatementPage.id)
            .where(FilingJob.status == "REVIEW")
            .group_by(FilingJob.id, FilingJob.company_name, FilingJob.status)
            .having(func.count(ExtractedDataItem.id) > 0)
            .having(template_count > 0)
            .order_by(FilingJob.id.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        row = result.mappings().first()
        await session.rollback()

    return dict(row) if row else None


async def describe_job(job_id: int, session_factory=AsyncSessionLocal) -> Optional[Dict[str, Any]]:
    async with session_factory() as session:
        template_count = func.sum(
            case((ExtractedDataItem.template_field_id.is_not(None), 1), else_=0)
        )
        reviewed_count = func.sum(case((ExtractedDataItem.is_reviewed.is_(True), 1), else_=0))
        stmt = (
            select(
                FilingJob.id,
                FilingJob.company_name,
                FilingJob.status,
                func.count(ExtractedDataItem.id).label("extracted_rows"),
                template_count.label("template_field_rows"),
                reviewed_count.label("reviewed_rows"),
            )
            .join(FinancialStatementPage, FinancialStatementPage.job_id == FilingJob.id)
            .join(ExtractedDataItem, ExtractedDataItem.page_id == FinancialStatementPage.id)
            .where(FilingJob.id == job_id)
            .group_by(FilingJob.id, FilingJob.company_name, FilingJob.status)
        )
        result = await session.execute(stmt)
        row = result.mappings().first()
        await session.rollback()

    return dict(row) if row else None


async def generate_for_job(
    job_id: int,
    session_factory=AsyncSessionLocal,
    generator: Callable[..., Awaitable[Any]] = generate_xbrl_for_job,
) -> Dict[str, Any]:
    async with session_factory() as session:
        response = await generator(job_id, session)
        await session.rollback()
    return _as_dict(response)


def validate_modes_for_instance(
    xbrl_path: str,
    taxonomy_entrypoint: str,
    report_dir: Path,
    timeout_seconds: int,
    validator: Callable[..., Any] = validate_with_arelle,
) -> Dict[str, Any]:
    mode_results: Dict[str, Any] = {}
    mode_summaries: Dict[str, Any] = {}
    for mode in COMPARISON_MODES:
        validation_copy_dir = report_dir / "validation_copies" / mode
        validation = _as_dict(
            validator(
                instance_path=str(xbrl_path),
                taxonomy_entrypoint=taxonomy_entrypoint,
                timeout_seconds=timeout_seconds,
                schema_ref_remaps=local_schema_ref_remaps(taxonomy_entrypoint),
                validation_copy_dir=str(validation_copy_dir),
                extra_args=VALIDATION_MODE_ARGS[mode],
                validation_mode=mode,
            )
        )
        mode_results[mode] = validation
        mode_summaries[mode] = summarize_mode(validation)

    return {
        "modes_tested": COMPARISON_MODES,
        "mode_options": {mode: VALIDATION_MODE_ARGS[mode] for mode in COMPARISON_MODES},
        "mode_results": mode_results,
        "mode_summaries": mode_summaries,
        "recommendation": validation_mode_recommendation(mode_summaries),
    }


def find_taxonomy_package_metadata(taxonomy_entrypoint: str) -> Dict[str, Any]:
    taxonomy_root = Path(taxonomy_entrypoint).resolve()
    for parent in taxonomy_root.parents:
        if parent.name == "SSMxT_2022v1.0":
            taxonomy_root = parent
            break

    matches: list[str] = []
    if taxonomy_root.exists():
        for path in taxonomy_root.rglob("*"):
            if path.is_file() and any(path.name.endswith(pattern) for pattern in TAXONOMY_METADATA_PATTERNS):
                matches.append(str(path))

    return {
        "taxonomy_root": str(taxonomy_root),
        "metadata_files_found": matches,
        "package_or_catalog_available": bool(matches),
        "assessment": (
            "Local taxonomy package/catalog metadata found; package loading can be tested."
            if matches
            else "No local taxonomy package/catalog metadata was found under the SSMxT_2022v1.0 tree."
        ),
    }


def _skipped_taxonomy_patterns_for_mode(mode: str) -> list[str]:
    args = VALIDATION_MODE_ARGS.get(mode, [])
    skipped: list[str] = []
    for index, arg in enumerate(args):
        if arg == "--skipLoading" and index + 1 < len(args):
            skipped.extend(pattern for pattern in str(args[index + 1]).split("|") if pattern)
    return skipped


def baseline_mode_recommendation(mode_summaries: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    for mode in BASELINE_EXPERIMENT_MODES:
        summary = mode_summaries.get(mode, {})
        if (
            summary.get("taxonomy_resolution_status") == "no_taxonomy_resolution_error_detected"
            and not summary.get("taxonomy_artifact_noise_remains")
            and not summary.get("generated_instance_defects_visible")
            and summary.get("is_valid")
        ):
            return {
                "recommended_baseline_mode": mode,
                "can_proceed_to_mapping_fixes": True,
                "reason": (
                    "Arelle validates the generated instance under a structural baseline after skipping local "
                    "FS-MPERS formula/table/existence-function artifacts. This is not full MBRS validation."
                ),
            }
        if (
            summary.get("taxonomy_resolution_status") == "no_taxonomy_resolution_error_detected"
            and not summary.get("taxonomy_artifact_noise_remains")
            and summary.get("generated_instance_defects_visible")
        ):
            return {
                "recommended_baseline_mode": mode,
                "can_proceed_to_mapping_fixes": True,
                "reason": "Taxonomy artifact noise is suppressed and generated-instance defects are visible.",
            }

    return {
        "recommended_baseline_mode": None,
        "can_proceed_to_mapping_fixes": False,
        "reason": (
            "Arelle remains blocked by local taxonomy artifact compatibility before generated-instance defects "
            "can be isolated."
        ),
    }


def validate_baseline_for_instance(
    xbrl_path: str,
    taxonomy_entrypoint: str,
    report_dir: Path,
    timeout_seconds: int,
    validator: Callable[..., Any] = validate_with_arelle,
) -> Dict[str, Any]:
    mode_results: Dict[str, Any] = {}
    mode_summaries: Dict[str, Any] = {}
    for mode in BASELINE_EXPERIMENT_MODES:
        validation_copy_dir = report_dir / "validation_copies" / mode
        validation = _as_dict(
            validator(
                instance_path=str(xbrl_path),
                taxonomy_entrypoint=taxonomy_entrypoint,
                timeout_seconds=timeout_seconds,
                schema_ref_remaps=local_schema_ref_remaps(taxonomy_entrypoint),
                validation_copy_dir=str(validation_copy_dir),
                extra_args=VALIDATION_MODE_ARGS[mode],
                validation_mode=mode,
            )
        )
        mode_results[mode] = validation
        mode_summaries[mode] = summarize_mode(validation)

    recommendation = baseline_mode_recommendation(mode_summaries)
    return {
        "baseline_goal": "Establish an Arelle mode that separates generated-instance structural defects from local taxonomy formula/table artifact compatibility noise.",
        "modes_tested": BASELINE_EXPERIMENT_MODES,
        "mode_options": {mode: VALIDATION_MODE_ARGS[mode] for mode in BASELINE_EXPERIMENT_MODES},
        "skipped_taxonomy_patterns": {
            mode: _skipped_taxonomy_patterns_for_mode(mode) for mode in BASELINE_EXPERIMENT_MODES
        },
        "taxonomy_package_metadata": find_taxonomy_package_metadata(taxonomy_entrypoint),
        "mode_results": mode_results,
        "mode_summaries": mode_summaries,
        "final_recommendation": recommendation,
        "limitations": [
            "The recommended baseline is instance structural validation, not full MBRS/FS-MPERS formula or table validation.",
            "Skipped taxonomy files must be recorded with every baseline validation report.",
            "A clean baseline result must not be described as full submission-ready validation.",
        ],
    }


async def run_validation(
    job_id: Optional[int],
    taxonomy_entrypoint: str,
    report_dir: Path,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    session_factory=AsyncSessionLocal,
    generator: Callable[..., Awaitable[Any]] = generate_xbrl_for_job,
    validator: Callable[..., Any] = validate_with_arelle,
) -> Dict[str, Any]:
    selected_job = await describe_job(job_id, session_factory) if job_id else None
    if job_id and not selected_job:
        return {
            "success": False,
            "error": f"Requested job {job_id} was not found or has no extracted rows.",
            "job": {"id": job_id},
        }

    if not selected_job:
        selected_job = await find_review_job_with_template_coverage(session_factory)

    if not selected_job:
        report = {
            "success": False,
            "error": "No REVIEW job with extracted rows and template_field_id coverage was found.",
            "job": None,
        }
        return report

    resolved_job_id = int(selected_job["id"])
    generation = await generate_for_job(resolved_job_id, session_factory, generator)
    xbrl_path = generation.get("file_path")
    xbrl_exists = bool(xbrl_path and Path(xbrl_path).exists())

    validation: Dict[str, Any]
    if generation.get("success") and xbrl_exists:
        validation_copy_dir = report_dir / "validation_copies"
        validation = _as_dict(
            validator(
                instance_path=str(xbrl_path),
                taxonomy_entrypoint=taxonomy_entrypoint,
                timeout_seconds=timeout_seconds,
                schema_ref_remaps=local_schema_ref_remaps(taxonomy_entrypoint),
                validation_copy_dir=str(validation_copy_dir),
                extra_args=VALIDATION_MODE_ARGS["full"],
                validation_mode="full",
            )
        )
    else:
        validation = {
            "is_valid": False,
            "errors": [generation.get("error") or f"Generated XBRL file not found: {xbrl_path}"],
            "warnings": [],
            "raw_output": "",
            "return_code": None,
            "duration_ms": 0,
            "instance_path": str(xbrl_path or ""),
            "taxonomy_entrypoint": taxonomy_entrypoint,
            "command_used": "",
        }

    categories = classify_diagnostics(validation)
    report = {
        "success": bool(generation.get("success") and xbrl_exists),
        "job": selected_job,
        "generation": {
            "success": generation.get("success"),
            "file_path": xbrl_path,
            "file_exists": xbrl_exists,
            "error": generation.get("error"),
        },
        "validation_copy_strategy": {
            "enabled": bool(validation.get("schema_ref_remaps")),
            "original_instance_path": validation.get("original_instance_path"),
            "validation_instance_path": validation.get("validation_instance_path"),
            "schema_ref_remaps": validation.get("schema_ref_remaps") or [],
            "original_xbrl_modified": False,
        },
        "validation": validation,
        "diagnostic_categories": categories,
        "taxonomy_resolution_status": taxonomy_resolution_status(categories),
        "schema_ref_future_change_required": bool(validation.get("schema_ref_remaps"))
        or schema_ref_future_change_required(categories),
    }

    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"arelle_validation_report_{resolved_job_id}.json"
    report["report_path"] = str(report_path)
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    if generation.get("success") and xbrl_exists:
        modes_report = validate_modes_for_instance(
            str(xbrl_path),
            taxonomy_entrypoint,
            report_dir,
            timeout_seconds,
            validator,
        )
        modes_report.update(
            {
                "success": True,
                "job": selected_job,
                "generation": report["generation"],
                "validation_copy_strategy": {
                    "enabled": True,
                    "original_xbrl_modified": False,
                    "original_instance_path": xbrl_path,
                },
            }
        )
        modes_report_path = report_dir / f"arelle_validation_modes_report_{resolved_job_id}.json"
        modes_report["report_path"] = str(modes_report_path)
        modes_report_path.write_text(json.dumps(modes_report, indent=2, default=str), encoding="utf-8")
        report["modes_report_path"] = str(modes_report_path)

        baseline_report = validate_baseline_for_instance(
            str(xbrl_path),
            taxonomy_entrypoint,
            report_dir,
            timeout_seconds,
            validator,
        )
        baseline_report.update(
            {
                "success": True,
                "job": selected_job,
                "generation": report["generation"],
                "validation_copy_strategy": {
                    "enabled": True,
                    "original_xbrl_modified": False,
                    "original_instance_path": xbrl_path,
                },
            }
        )
        baseline_report_path = report_dir / f"arelle_validation_baseline_report_{resolved_job_id}.json"
        baseline_report["report_path"] = str(baseline_report_path)
        baseline_report_path.write_text(json.dumps(baseline_report, indent=2, default=str), encoding="utf-8")
        report["baseline_report_path"] = str(baseline_report_path)
        report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate real XBRL for a REVIEW job, validate it with Arelle, and save a diagnostic report."
    )
    parser.add_argument("--job-id", type=int, help="Existing REVIEW job ID. If omitted, the newest matching REVIEW job is used.")
    parser.add_argument(
        "--taxonomy-entrypoint",
        default=str(DEFAULT_TAXONOMY_ENTRYPOINT),
        help="Local FS-MPERS taxonomy entrypoint XSD.",
    )
    parser.add_argument(
        "--report-dir",
        default=str(ROOT_DIR / "reports"),
        help="Directory for arelle_validation_report_<jobid>.json.",
    )
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    return parser.parse_args()


async def async_main() -> int:
    args = parse_args()
    report = await run_validation(
        job_id=args.job_id,
        taxonomy_entrypoint=str(Path(args.taxonomy_entrypoint)),
        report_dir=Path(args.report_dir),
        timeout_seconds=args.timeout,
    )
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
