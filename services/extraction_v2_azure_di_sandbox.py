"""Read-only Azure DI-first Extraction v2 sandbox orchestration."""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from services.azure_document_intelligence_provider import AzureDocumentIntelligenceProvider
from services.extraction_v2_azure_di_pipeline import (
    SOURCE_METHOD,
    build_case_report,
    convert_azure_di_result_to_candidates,
)
from services.extraction_v2_duplicate_resolver import (
    render_duplicate_conflict_markdown,
    resolve_extraction_v2_duplicates,
)
from services.extraction_v2_mapping_handoff import (
    build_mapping_handoff_reports,
    render_candidates_markdown as render_handoff_markdown,
)
from services.extraction_v2_manual_review_policy import (
    build_manual_review_policy_reports,
    render_queue_markdown,
)
from services.extraction_v2_quality_analyzer import (
    analyze_candidate_quality_reports,
    render_candidate_quality_markdown,
)


APPROVAL_MESSAGE = (
    "Azure Document Intelligence processing uploads the PDF to Azure. "
    "Re-run with --approve-azure-document-intelligence-upload only if this is approved."
)
DEFAULT_OUTPUT_PREFIX = Path("reports/azure_di_sandbox")
NUMERIC_ROW_TYPES = {"numeric_fact", "comparative_numeric_fact", "subtotal_or_total"}


class AzureDISandboxApprovalError(RuntimeError):
    """Raised when a live Azure DI upload was requested without explicit approval."""


class AzureDISandboxInputError(ValueError):
    """Raised when sandbox input selection is invalid."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class SandboxOutputPaths:
    extraction_json: Path
    extraction_md: Path
    quality_json: Path
    quality_md: Path
    duplicate_json: Path
    duplicate_md: Path
    manual_review_queue_json: Path
    manual_review_queue_md: Path
    mapping_handoff_json: Path
    mapping_handoff_md: Path
    summary_json: Path
    summary_md: Path


def output_paths_from_prefix(output_prefix: str | Path | None = None) -> SandboxOutputPaths:
    prefix = Path(output_prefix) if output_prefix else DEFAULT_OUTPUT_PREFIX
    return SandboxOutputPaths(
        extraction_json=Path(f"{prefix}_extraction_v2_report_13x.json"),
        extraction_md=Path(f"{prefix}_extraction_v2_report_13x.md"),
        quality_json=Path(f"{prefix}_candidate_quality_13x.json"),
        quality_md=Path(f"{prefix}_candidate_quality_13x.md"),
        duplicate_json=Path(f"{prefix}_duplicate_conflict_13x.json"),
        duplicate_md=Path(f"{prefix}_duplicate_conflict_13x.md"),
        manual_review_queue_json=Path(f"{prefix}_manual_review_queue_13x.json"),
        manual_review_queue_md=Path(f"{prefix}_manual_review_queue_13x.md"),
        mapping_handoff_json=Path(f"{prefix}_mapping_handoff_13x.json"),
        mapping_handoff_md=Path(f"{prefix}_mapping_handoff_13x.md"),
        summary_json=Path(f"{prefix}_summary_13x.json"),
        summary_md=Path(f"{prefix}_summary_13x.md"),
    )


def no_side_effect_metadata() -> dict[str, Any]:
    return {
        "feature": "13X",
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
        "semantic_matcher_called": False,
        "xbrl_generated": False,
        "arelle_validation_run": False,
        "live_huggingface_calls_made": False,
        "live_openai_calls_made": False,
        "reference_xml_sent_to_provider": False,
        "reference_xml_sent_to_model": False,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _pdf_input(pdf: str | Path | None, case_dir: str | Path | None) -> tuple[Path, str | None]:
    if bool(pdf) == bool(case_dir):
        raise AzureDISandboxInputError("Provide exactly one of --pdf or --case-dir.")
    if pdf:
        path = Path(pdf)
        if not path.exists() or not path.is_file():
            raise AzureDISandboxInputError(f"PDF input does not exist: {path}")
        if path.suffix.lower() != ".pdf":
            raise AzureDISandboxInputError("Azure DI sandbox accepts PDF input only.")
        return path, None

    directory = Path(str(case_dir))
    if not directory.exists() or not directory.is_dir():
        raise AzureDISandboxInputError(f"Case directory does not exist: {directory}")
    pdfs = sorted(item for item in directory.iterdir() if item.is_file() and item.suffix.lower() == ".pdf")
    if not pdfs:
        raise AzureDISandboxInputError(f"Case directory has no PDF files: {directory}")
    if len(pdfs) > 1:
        raise AzureDISandboxInputError(f"Case directory has multiple PDF files; use --pdf explicitly: {directory}")
    return pdfs[0], directory.name


def _pages_option(pages: str | None, max_pages: int | None) -> str | None:
    if pages:
        return pages
    if max_pages:
        if max_pages < 1:
            raise AzureDISandboxInputError("--max-pages must be greater than zero.")
        return f"1-{max_pages}"
    return None


def _endpoint_host(endpoint: str | None) -> str | None:
    if not endpoint:
        return None
    parsed = urlparse(endpoint)
    return parsed.netloc or parsed.path or None


def _row_counts(candidates: list[dict[str, Any]]) -> Counter[str]:
    return Counter(str(candidate.get("row_type") or "unknown") for candidate in candidates)


def _candidate_counts(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    counts = _row_counts(candidates)
    return {
        "total_candidates": len(candidates),
        "numeric_candidate_count": counts.get("numeric_fact", 0),
        "comparative_numeric_candidate_count": counts.get("comparative_numeric_fact", 0),
        "subtotal_or_total_candidate_count": counts.get("subtotal_or_total", 0),
        "text_block_candidate_count": counts.get("text_block", 0),
        "heading_candidate_count": counts.get("heading", 0),
        "metadata_candidate_count": counts.get("metadata", 0),
        "unknown_candidate_count": counts.get("unknown", 0),
        "row_type_counts": dict(sorted(counts.items())),
    }


def build_dry_run_plan(
    *,
    pdf: str | Path | None = None,
    case_dir: str | Path | None = None,
    run_id: str | None = None,
    output_prefix: str | Path | None = None,
    skip_quality_gates: bool = False,
    pages: str | None = None,
    max_pages: int | None = None,
) -> dict[str, Any]:
    pdf_path, case_id = _pdf_input(pdf, case_dir)
    selected_pages = _pages_option(pages, max_pages)
    paths = output_paths_from_prefix(output_prefix)
    return {
        "run_metadata": {
            **no_side_effect_metadata(),
            "generated_at": utc_now_iso(),
            "run_id": run_id,
            "script": "scripts/run_azure_di_extraction_v2_sandbox.py",
            "report_type": "azure_di_sandbox_dry_run_plan",
            "dry_run": True,
            "live_external_provider_call": False,
            "approval_flag_used": False,
            "source_method": SOURCE_METHOD,
        },
        "input": {
            "pdf_path": str(pdf_path),
            "case_id": case_id,
            "pages": selected_pages,
            "skip_quality_gates": bool(skip_quality_gates),
        },
        "would_write_reports": {
            name: str(getattr(paths, name))
            for name in paths.__dataclass_fields__
        },
        "would_call_azure_document_intelligence": False,
        "approval_required_for_live_run": True,
        "approval_message": APPROVAL_MESSAGE,
    }


def build_sandbox_extraction_report(
    *,
    pdf_path: Path,
    case_id: str,
    azure_result: dict[str, Any],
    candidates: list[dict[str, Any]],
    provider: AzureDocumentIntelligenceProvider,
    run_id: str | None,
    output_path: Path,
    started_at: str,
    total_runtime_seconds: float,
    approval_flag_used: bool,
    pages_option: str | None,
) -> dict[str, Any]:
    case = {
        "case_id": case_id,
        "case_dir": str(pdf_path.parent),
        "pdf_path": str(pdf_path),
        "reference_available": False,
        "reference_path": None,
        "reference_type": None,
    }
    case_report = build_case_report(case=case, azure_result=azure_result, candidates=candidates)
    counts = _candidate_counts(candidates)
    pages = int(azure_result.get("pages_count") or 0)
    runtime = round(float(total_runtime_seconds), 3)
    return {
        "run_metadata": {
            **no_side_effect_metadata(),
            "generated_at": utc_now_iso(),
            "started_at": started_at,
            "run_id": run_id,
            "script": "scripts/run_azure_di_extraction_v2_sandbox.py",
            "report_type": "azure_di_sandbox_extraction_v2",
            "provider": SOURCE_METHOD,
            "source_method": SOURCE_METHOD,
            "model_id": provider.model_id,
            "endpoint_host": _endpoint_host(provider.endpoint),
            "pages_option": pages_option,
            "output_path": str(output_path),
            "live_external_provider_call": True,
            "external_provider_calls": True,
            "live_model_calls": True,
            "approval_flag_used": bool(approval_flag_used),
            "huggingface_used": False,
            "openai_used": False,
        },
        "pipeline_name": "Azure DI-first Extraction v2 Sandbox",
        "input": {
            "pdf_path": str(pdf_path),
            "case_id": case_id,
        },
        "aggregate_metrics": {
            "total_cases_processed": 1,
            "total_pdfs_processed": 1,
            "pages_processed": pages,
            "azure_di_pages_processed": pages,
            "estimated_pages_billable": pages,
            "tables_detected": len(azure_result.get("tables") or []),
            "azure_di_tables_detected": len(azure_result.get("tables") or []),
            "paragraphs_detected": len(azure_result.get("paragraphs") or []),
            "content_characters": int(azure_result.get("content_length") or 0),
            "azure_di_characters_detected": int(azure_result.get("content_length") or 0),
            "runtime_seconds": runtime,
            "total_runtime_seconds": runtime,
            "average_seconds_per_page": round(runtime / pages, 3) if pages else None,
            "source_method": SOURCE_METHOD,
            **counts,
            "total_candidate_rows": counts["total_candidates"],
            "numeric_fact_count": counts["numeric_candidate_count"],
            "comparative_numeric_fact_count": counts["comparative_numeric_candidate_count"],
            "subtotal_or_total_count": counts["subtotal_or_total_candidate_count"],
            "text_block_count": counts["text_block_candidate_count"],
            "heading_count": counts["heading_candidate_count"],
            "metadata_count": counts["metadata_candidate_count"],
            "unknown_count": counts["unknown_candidate_count"],
        },
        "case_reports": [case_report],
        "sample_candidates": candidates[:25],
        "warnings": list(azure_result.get("warnings") or []),
        "errors": list(azure_result.get("errors") or []),
        "cost_runtime": {
            "pages_sent_to_azure_di": pages,
            "estimated_billable_pages": pages,
            "runtime_seconds": runtime,
            "average_seconds_per_page": round(runtime / pages, 3) if pages else None,
            "model_id": provider.model_id,
            "endpoint_host": _endpoint_host(provider.endpoint),
            "dollar_cost_estimated": False,
            "cost_tracking_instructions": [
                "Azure Portal -> Document Intelligence resource -> Monitoring -> Metrics -> Processed Pages",
                "Azure Portal -> Cost Management + Billing -> Cost Analysis",
            ],
        },
        "limitations": [
            "Sandbox report only; no production cutover.",
            "Azure DI prebuilt-layout is the primary extraction direction for this sandbox path, not validated production behavior.",
            "Reference XML is not sent to Azure DI or any model.",
            "No DB mutation, API/UI implementation, Hugging Face/OpenAI call, semantic matcher call, XBRL generation, or Arelle validation is performed.",
        ],
    }


def render_extraction_markdown(report: dict[str, Any]) -> str:
    metadata = report.get("run_metadata", {})
    aggregate = report.get("aggregate_metrics", {})
    cost = report.get("cost_runtime", {})
    lines = [
        "# Azure DI-first Extraction v2 Sandbox - Feature #13X",
        "",
        "## Summary",
        "",
        f"- Provider: {metadata.get('provider')}",
        f"- Model ID: {metadata.get('model_id')}",
        f"- PDF: {report.get('input', {}).get('pdf_path')}",
        f"- Case ID: {report.get('input', {}).get('case_id')}",
        f"- Pages processed: {aggregate.get('pages_processed', 0)}",
        f"- Tables detected: {aggregate.get('tables_detected', 0)}",
        f"- Paragraphs detected: {aggregate.get('paragraphs_detected', 0)}",
        f"- Content characters: {aggregate.get('content_characters', 0)}",
        f"- Total candidates: {aggregate.get('total_candidates', 0)}",
        f"- Numeric candidates: {aggregate.get('numeric_candidate_count', 0)}",
        f"- Comparative numeric candidates: {aggregate.get('comparative_numeric_candidate_count', 0)}",
        f"- Text blocks: {aggregate.get('text_block_candidate_count', 0)}",
        f"- Runtime seconds: {aggregate.get('runtime_seconds')}",
        f"- Average seconds/page: {aggregate.get('average_seconds_per_page')}",
        f"- Approval flag used: {metadata.get('approval_flag_used')}",
        f"- Database mutated: {metadata.get('database_mutated')}",
        f"- Production behavior changed: {metadata.get('production_behavior_changed')}",
        f"- Reference XML sent to provider: {metadata.get('reference_xml_sent_to_provider')}",
        "",
        "## Cost Runtime",
        "",
        f"- Pages sent to Azure DI: {cost.get('pages_sent_to_azure_di', 0)}",
        f"- Estimated billable pages: {cost.get('estimated_billable_pages', 0)}",
        f"- Dollar cost estimated: {cost.get('dollar_cost_estimated')}",
        "",
        "## Cost Tracking",
        "",
    ]
    lines.extend(f"- {item}" for item in cost.get("cost_tracking_instructions", []))
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.get("limitations", []))
    lines.append("")
    return "\n".join(lines)


def _empty_reference_report() -> dict[str, Any]:
    return {"run_metadata": {"database_mutated": False}, "case_reports": [], "aggregate_metrics": {}}


def _empty_comparison_report() -> dict[str, Any]:
    return {"run_metadata": {"database_mutated": False}, "per_case": [], "aggregate_metrics": {"missing_text_block_cases": []}}


def _retag(report: dict[str, Any], *, report_type: str, output_path: Path) -> dict[str, Any]:
    metadata = dict(report.get("run_metadata") or {})
    metadata.update(
        {
            **{key: value for key, value in no_side_effect_metadata().items() if key not in {"generated_at"}},
            "feature": "13X",
            "report_type": report_type,
            "output_path": str(output_path),
            "source_pipeline": "azure_di_sandbox",
        }
    )
    report["run_metadata"] = metadata
    return report


def _limitation_report(stage: str, error: Exception, output_path: Path) -> dict[str, Any]:
    return {
        "run_metadata": {
            **no_side_effect_metadata(),
            "generated_at": utc_now_iso(),
            "feature": "13X",
            "report_type": f"azure_di_sandbox_{stage}_limitation",
            "output_path": str(output_path),
        },
        "status": "limitation",
        "stage": stage,
        "limitation": f"{stage} stage could not consume the Azure DI sandbox report: {type(error).__name__}: {error}",
        "database_mutated": False,
        "production_behavior_changed": False,
    }


def build_quality_gate_reports(
    extraction_report: dict[str, Any],
    *,
    paths: SandboxOutputPaths,
    comparison_report: dict[str, Any] | None = None,
    reference_report: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    try:
        quality_report, readiness_report = analyze_candidate_quality_reports(
            v2_report=extraction_report,
            comparison_report=comparison_report or _empty_comparison_report(),
            reference_report=reference_report or _empty_reference_report(),
            input_paths={"v2_report": str(paths.extraction_json)},
        )
        _retag(quality_report, report_type="azure_di_sandbox_candidate_quality", output_path=paths.quality_json)
        _retag(readiness_report, report_type="azure_di_sandbox_mapping_readiness", output_path=paths.quality_json)

        duplicate_report, cleaned_report, readiness_after = resolve_extraction_v2_duplicates(
            v2_report=extraction_report,
            quality_report=quality_report,
            readiness_report=readiness_report,
            comparison_report=comparison_report or _empty_comparison_report(),
            reference_report=reference_report or _empty_reference_report(),
            input_paths={
                "v2_report": str(paths.extraction_json),
                "quality_report": str(paths.quality_json),
                "readiness_report": "in_memory_azure_di_sandbox_readiness",
            },
            output_paths={
                "duplicate": str(paths.duplicate_json),
                "cleaned": "in_memory_azure_di_sandbox_cleaned_candidates",
                "readiness_after": "in_memory_azure_di_sandbox_readiness_after",
            },
        )
        _retag(duplicate_report, report_type="azure_di_sandbox_duplicate_conflict", output_path=paths.duplicate_json)
        _retag(cleaned_report, report_type="azure_di_sandbox_cleaned_candidates", output_path=paths.duplicate_json)
        _retag(readiness_after, report_type="azure_di_sandbox_mapping_readiness_after_duplicates", output_path=paths.duplicate_json)

        policy_report, gate_report, queue_report = build_manual_review_policy_reports(
            cleaned_report=cleaned_report,
            duplicate_report=duplicate_report,
            readiness_report=readiness_after,
            quality_report=quality_report,
            reference_report=reference_report or _empty_reference_report(),
            input_paths={
                "cleaned_candidates": "in_memory_azure_di_sandbox_cleaned_candidates",
                "duplicate_report": str(paths.duplicate_json),
                "readiness_report": "in_memory_azure_di_sandbox_readiness_after",
                "quality_report": str(paths.quality_json),
            },
            output_paths={
                "policy": "in_memory_azure_di_sandbox_manual_review_policy",
                "gate": "in_memory_azure_di_sandbox_mapping_gate",
                "queue": str(paths.manual_review_queue_json),
            },
        )
        _retag(policy_report, report_type="azure_di_sandbox_manual_review_policy", output_path=paths.manual_review_queue_json)
        _retag(gate_report, report_type="azure_di_sandbox_mapping_candidate_gate", output_path=paths.manual_review_queue_json)
        _retag(queue_report, report_type="azure_di_sandbox_manual_review_queue", output_path=paths.manual_review_queue_json)

        handoff_report, validation_report, contract_report = build_mapping_handoff_reports(
            cleaned_report=cleaned_report,
            mapping_gate_report=gate_report,
            manual_review_queue=queue_report,
            data_contract={},
            ui_api_plan={},
            input_paths={
                "cleaned_candidates": "in_memory_azure_di_sandbox_cleaned_candidates",
                "mapping_gate_report": "in_memory_azure_di_sandbox_mapping_gate",
                "manual_review_queue": str(paths.manual_review_queue_json),
            },
        )
        _retag(handoff_report, report_type="azure_di_sandbox_mapping_handoff", output_path=paths.mapping_handoff_json)
        _retag(validation_report, report_type="azure_di_sandbox_mapping_handoff_validation", output_path=paths.mapping_handoff_json)
        _retag(contract_report, report_type="azure_di_sandbox_mapping_handoff_contract", output_path=paths.mapping_handoff_json)
        return {
            "quality": quality_report,
            "readiness": readiness_report,
            "duplicate": duplicate_report,
            "cleaned": cleaned_report,
            "readiness_after": readiness_after,
            "policy": policy_report,
            "gate": gate_report,
            "queue": queue_report,
            "handoff": handoff_report,
            "handoff_validation": validation_report,
            "handoff_contract": contract_report,
        }
    except Exception as exc:
        return {
            "quality": _limitation_report("candidate_quality", exc, paths.quality_json),
            "duplicate": _limitation_report("duplicate_conflict", exc, paths.duplicate_json),
            "queue": _limitation_report("manual_review_queue", exc, paths.manual_review_queue_json),
            "handoff": _limitation_report("mapping_handoff", exc, paths.mapping_handoff_json),
        }


def _top_warnings(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter = Counter(warning for item in candidates for warning in (item.get("warnings") or []))
    return [{"warning": key, "count": value} for key, value in counter.most_common(10)]


def build_summary_report(
    *,
    extraction_report: dict[str, Any],
    gate_reports: dict[str, dict[str, Any]] | None,
    skip_quality_gates: bool,
    output_path: Path,
) -> dict[str, Any]:
    candidates = [item for case in extraction_report.get("case_reports", []) for item in case.get("candidates", [])]
    handoff = (gate_reports or {}).get("handoff") or {}
    queue = (gate_reports or {}).get("queue") or {}
    gate = (gate_reports or {}).get("gate") or {}
    gate_counts = gate.get("aggregate_gate_counts") or {}
    handoff_count = int(handoff.get("total_handoff_candidates") or 0)
    manual_review_count = int(queue.get("queue_item_count") or 0)
    blocked_context_count = int(gate_counts.get("blocked_from_mapping") or 0) + int(gate_counts.get("reference_only_or_context") or 0)
    limitation_reports = [
        report for report in (gate_reports or {}).values()
        if report.get("status") == "limitation"
    ]
    ready_for_mapping_candidate_generation = bool(handoff_count) and not limitation_reports
    recommended_next = (
        "Feature #13Y - Continue mapping candidate generation using Azure DI sandbox handoff candidates."
        if ready_for_mapping_candidate_generation
        else "Feature #13Y - Azure DI table/text-block normalization before mapping."
    )
    return {
        "run_metadata": {
            **no_side_effect_metadata(),
            "generated_at": utc_now_iso(),
            "feature": "13X",
            "report_type": "azure_di_sandbox_summary",
            "output_path": str(output_path),
        },
        "input_reports": {
            "extraction_report": extraction_report.get("run_metadata", {}).get("output_path"),
        },
        "summary": {
            "total_azure_di_candidates": len(candidates),
            "total_mapping_handoff_eligible_candidates": handoff_count,
            "manual_review_count": manual_review_count,
            "blocked_context_only_count": blocked_context_count,
            "top_warnings": _top_warnings(candidates),
            "quality_gates_skipped": bool(skip_quality_gates),
            "quality_gate_limitations": [item.get("limitation") for item in limitation_reports],
            "ready_for_mapping_candidate_generation": ready_for_mapping_candidate_generation,
            "recommended_next_feature": recommended_next,
        },
        "non_goals_confirmed": no_side_effect_metadata(),
    }


def render_summary_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# Azure DI-first Sandbox Summary - Feature #13X",
        "",
        "## Summary",
        "",
        f"- Azure DI candidates: {summary.get('total_azure_di_candidates', 0)}",
        f"- Mapping handoff eligible: {summary.get('total_mapping_handoff_eligible_candidates', 0)}",
        f"- Manual review count: {summary.get('manual_review_count', 0)}",
        f"- Blocked/context-only count: {summary.get('blocked_context_only_count', 0)}",
        f"- Quality gates skipped: {summary.get('quality_gates_skipped')}",
        f"- Ready for mapping-candidate generation: {summary.get('ready_for_mapping_candidate_generation')}",
        f"- Recommended next feature: {summary.get('recommended_next_feature')}",
        f"- Database mutated: {report.get('run_metadata', {}).get('database_mutated')}",
        f"- Production behavior changed: {report.get('run_metadata', {}).get('production_behavior_changed')}",
        "",
        "## Top Warnings",
        "",
    ]
    warnings = summary.get("top_warnings") or []
    lines.extend(f"- {item['warning']}: {item['count']}" for item in warnings) if warnings else lines.append("- None")
    limitations = summary.get("quality_gate_limitations") or []
    if limitations:
        lines.extend(["", "## Gate Limitations", ""])
        lines.extend(f"- {item}" for item in limitations)
    lines.append("")
    return "\n".join(lines)


def run_azure_di_sandbox(
    *,
    pdf: str | Path | None = None,
    case_dir: str | Path | None = None,
    run_id: str | None = None,
    output_prefix: str | Path | None = None,
    approve_azure_document_intelligence_upload: bool = False,
    dry_run: bool = False,
    skip_quality_gates: bool = False,
    pages: str | None = None,
    max_pages: int | None = None,
    provider: AzureDocumentIntelligenceProvider | None = None,
    provider_factory: Callable[[], AzureDocumentIntelligenceProvider] | None = None,
    progress: Callable[[str], None] | None = None,
    quality_gate_builder: Callable[..., dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    if dry_run:
        return build_dry_run_plan(
            pdf=pdf,
            case_dir=case_dir,
            run_id=run_id,
            output_prefix=output_prefix,
            skip_quality_gates=skip_quality_gates,
            pages=pages,
            max_pages=max_pages,
        )
    if not approve_azure_document_intelligence_upload:
        raise AzureDISandboxApprovalError(APPROVAL_MESSAGE)

    pdf_path, case_id = _pdf_input(pdf, case_dir)
    case_id = case_id or pdf_path.stem
    selected_pages = _pages_option(pages, max_pages)
    paths = output_paths_from_prefix(output_prefix)
    provider = provider or (provider_factory() if provider_factory else AzureDocumentIntelligenceProvider())
    started_at = utc_now_iso()
    started = time.monotonic()
    if progress:
        progress(f"[13X-AzureDI] analyzing {pdf_path}")
    azure_result = provider.analyze_pdf_path(pdf_path, pages=selected_pages)
    candidates = convert_azure_di_result_to_candidates(azure_result, case_id=case_id, source_pdf=str(pdf_path))
    extraction_report = build_sandbox_extraction_report(
        pdf_path=pdf_path,
        case_id=case_id,
        azure_result=azure_result,
        candidates=candidates,
        provider=provider,
        run_id=run_id,
        output_path=paths.extraction_json,
        started_at=started_at,
        total_runtime_seconds=time.monotonic() - started,
        approval_flag_used=True,
        pages_option=selected_pages,
    )
    _write_json(paths.extraction_json, extraction_report)
    _write_text(paths.extraction_md, render_extraction_markdown(extraction_report))

    gate_reports: dict[str, dict[str, Any]] = {}
    if skip_quality_gates:
        gate_reports = {
            "quality": {
                "run_metadata": {**no_side_effect_metadata(), "feature": "13X", "report_type": "azure_di_sandbox_candidate_quality_skipped"},
                "status": "skipped",
                "reason": "Quality gates were skipped by --skip-quality-gates.",
            }
        }
    else:
        builder = quality_gate_builder or build_quality_gate_reports
        gate_reports = builder(extraction_report, paths=paths)
        _write_json(paths.quality_json, gate_reports.get("quality", {}))
        _write_text(paths.quality_md, render_candidate_quality_markdown(gate_reports["quality"]) if gate_reports.get("quality", {}).get("status") != "limitation" else gate_reports["quality"].get("limitation", "Quality gate unavailable."))
        _write_json(paths.duplicate_json, gate_reports.get("duplicate", {}))
        _write_text(paths.duplicate_md, render_duplicate_conflict_markdown(gate_reports["duplicate"]) if gate_reports.get("duplicate", {}).get("status") != "limitation" else gate_reports["duplicate"].get("limitation", "Duplicate gate unavailable."))
        _write_json(paths.manual_review_queue_json, gate_reports.get("queue", {}))
        _write_text(paths.manual_review_queue_md, render_queue_markdown(gate_reports["queue"]) if gate_reports.get("queue", {}).get("status") != "limitation" else gate_reports["queue"].get("limitation", "Manual review gate unavailable."))
        _write_json(paths.mapping_handoff_json, gate_reports.get("handoff", {}))
        _write_text(paths.mapping_handoff_md, render_handoff_markdown(gate_reports["handoff"]) if gate_reports.get("handoff", {}).get("status") != "limitation" else gate_reports["handoff"].get("limitation", "Mapping handoff gate unavailable."))

    summary_report = build_summary_report(
        extraction_report=extraction_report,
        gate_reports=gate_reports,
        skip_quality_gates=skip_quality_gates,
        output_path=paths.summary_json,
    )
    _write_json(paths.summary_json, summary_report)
    _write_text(paths.summary_md, render_summary_markdown(summary_report))
    return {
        "dry_run": False,
        "paths": paths,
        "extraction_report": extraction_report,
        "gate_reports": gate_reports,
        "summary_report": summary_report,
    }
