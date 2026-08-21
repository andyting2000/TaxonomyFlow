"""Run the benchmark-only Industrial Extraction Pipeline v2 skeleton."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.discover_benchmark_cases import discover_benchmark_cases
from services.extraction_v2_pipeline import (
    ExtractionV2Pipeline,
    benchmark_case_from_manifest,
    build_report,
    default_output_path,
    render_markdown,
)


REPORTS_DIR = PROJECT_ROOT / "reports"
DEFAULT_CHECKPOINT_DIR = REPORTS_DIR / "checkpoints"
LOG_PREFIX = "[13Q-pre]"
PRIVATE_PDF_OPENAI_APPROVAL_REQUIRED_MESSAGE = (
    "OpenAI fallback would transmit benchmark PDF page images. "
    "Re-run with --approve-private-pdf-openai only if approved."
)
CHECKPOINT_FLAG_NAMES = {
    "cases_dir",
    "case",
    "all",
    "limit_pages",
    "use_vision_fallback",
    "vision_provider",
    "vision_max_pages",
    "vision_page_mode",
    "use_openai",
    "no_openai",
    "openai_max_pages",
    "openai_page_mode",
}
CLI_OPTION_DESTS = {
    "--cases-dir": "cases_dir",
    "--case": "case",
    "--all": "all",
    "--limit-pages": "limit_pages",
    "--use-vision-fallback": "use_vision_fallback",
    "--vision-provider": "vision_provider",
    "--vision-max-pages": "vision_max_pages",
    "--vision-page-mode": "vision_page_mode",
    "--use-openai": "use_openai",
    "--no-openai": "no_openai",
    "--openai-max-pages": "openai_max_pages",
    "--openai-page-mode": "openai_page_mode",
    "--progress": "progress",
    "--quiet": "quiet",
    "--verbose": "verbose",
    "--progress-every-pages": "progress_every_pages",
    "--checkpoint-dir": "checkpoint_dir",
    "--checkpoint-every-pages": "checkpoint_every_pages",
    "--disable-checkpoint": "disable_checkpoint",
    "--run-id": "run_id",
    "--output-json": "output_json",
    "--output-md": "output_md",
}
RESUME_SAFE_OVERRIDES = {
    "vision_max_pages",
    "progress",
    "quiet",
    "verbose",
    "progress_every_pages",
    "checkpoint_dir",
    "checkpoint_every_pages",
    "disable_checkpoint",
    "run_id",
    "output_json",
    "output_md",
}


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(message: str, *, quiet: bool = False) -> None:
    if not quiet:
        print(f"{LOG_PREFIX} {message}", flush=True)


def load_or_discover_manifest(cases_dir: Path, manifest_path: Path) -> dict:
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = discover_benchmark_cases(cases_dir)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    return manifest


def select_ready_cases(manifest: dict, requested_case: str | None, run_all: bool) -> list[dict]:
    ready_cases = [case for case in manifest.get("cases", []) if case.get("status") == "ready"]
    if requested_case:
        return [case for case in ready_cases if case.get("case_id") == requested_case]
    if run_all or not requested_case:
        return ready_cases
    return []


def validate_private_pdf_openai_approval(use_openai: bool, approved: bool) -> tuple[bool, str | None]:
    if use_openai and not approved:
        return False, PRIVATE_PDF_OPENAI_APPROVAL_REQUIRED_MESSAGE
    return True, None


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    temp_path.replace(path)


def load_checkpoint(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_completed_pages(value: Any) -> dict[str, set[int]]:
    result: dict[str, set[int]] = {}
    if not isinstance(value, dict):
        return result
    for case_id, pages in value.items():
        result[str(case_id)] = {int(page) for page in pages or []}
    return result


def explicit_cli_dests(argv: list[str] | None) -> set[str]:
    values = list(sys.argv[1:] if argv is None else argv)
    return {dest for arg, dest in CLI_OPTION_DESTS.items() if arg in values}


def checkpoint_vision_attempt_count(checkpoint: dict[str, Any] | None) -> int:
    if not checkpoint:
        return 0
    metrics = checkpoint.get("partial_vision_metrics") or {}
    try:
        attempted = int(metrics.get("attempted") or 0)
    except (TypeError, ValueError):
        attempted = 0
    if attempted > 0:
        return attempted
    completed_pages = normalize_completed_pages(checkpoint.get("completed_vision_pages"))
    page_count = sum(len(pages) for pages in completed_pages.values())
    if page_count:
        return page_count
    identifiers = checkpoint.get("completed_page_identifiers") or []
    return sum(1 for item in identifiers if isinstance(item, dict) and str(item.get("stage") or "").endswith("_vision_fallback"))


def checkpoint_vision_max_pages(checkpoint: dict[str, Any] | None) -> int | None:
    if not checkpoint:
        return None
    flags = checkpoint.get("flags") or {}
    value = flags.get("vision_max_pages")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def dedupe_candidate_dicts(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    deduped: list[dict[str, Any]] = []
    for candidate in candidates:
        identity = (
            candidate.get("case_id"),
            candidate.get("page_number"),
            candidate.get("extraction_method"),
            candidate.get("row_type"),
            candidate.get("label"),
            candidate.get("value"),
            candidate.get("previous_value"),
            candidate.get("text") or candidate.get("source_snippet"),
        )
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(candidate)
    return deduped


def flags_snapshot(args: argparse.Namespace, *, use_openai: bool) -> dict[str, Any]:
    return {
        "cases_dir": str(args.cases_dir),
        "case": args.case,
        "all": bool(args.all),
        "limit_pages": args.limit_pages,
        "use_vision_fallback": bool(args.use_vision_fallback),
        "vision_provider": args.vision_provider,
        "vision_max_pages": args.vision_max_pages,
        "vision_page_mode": args.vision_page_mode,
        "use_openai": bool(use_openai),
        "no_openai": bool(args.no_openai),
        "openai_max_pages": args.openai_max_pages,
        "openai_page_mode": args.openai_page_mode,
        "progress": bool(args.progress and not args.quiet),
        "quiet": bool(args.quiet),
        "verbose": bool(args.verbose),
        "progress_every_pages": args.progress_every_pages,
        "checkpoint_every_pages": args.checkpoint_every_pages,
        "checkpoint_disabled": bool(args.disable_checkpoint),
    }


def apply_checkpoint_flags(
    args: argparse.Namespace,
    checkpoint: dict[str, Any],
    *,
    explicit_dests: set[str] | None = None,
) -> None:
    flags = checkpoint.get("flags") or {}
    explicit_dests = explicit_dests or set()
    for name in CHECKPOINT_FLAG_NAMES:
        if name not in flags:
            continue
        if name in RESUME_SAFE_OVERRIDES and name in explicit_dests:
            continue
        value = flags[name]
        if name == "cases_dir":
            setattr(args, name, Path(value))
        else:
            setattr(args, name, value)


def new_checkpoint_state(
    *,
    run_id: str,
    started_at: str,
    cases_dir: Path,
    selected_cases: list[dict[str, Any]],
    flags: dict[str, Any],
    checkpoint_path: Path | None,
    resumed_from_checkpoint: bool,
    resume_path: Path | None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "started_at": started_at,
        "updated_at": started_at,
        "cases_dir": str(cases_dir),
        "selected_cases": selected_cases,
        "completed_cases": [],
        "completed_vision_pages": {},
        "completed_page_identifiers": [],
        "vision_page_status": {},
        "partial_candidates_by_case": {},
        "partial_case_reports": {},
        "partial_vision_metrics": {
            "attempted": 0,
            "succeeded": 0,
            "failed": 0,
            "skipped": 0,
            "max_limit_reached": 0,
            "hf_raw_response_preview_count": 0,
            "hf_parser_recovered_candidates": 0,
            "hf_parser_failed_pages": 0,
            "hf_empty_candidate_pages": 0,
            "hf_no_relevant_content_pages": 0,
            "hf_parser_failure_reasons": {},
        },
        "partial_vision_diagnostics": [],
        "failures": [],
        "warnings": [],
        "flags": flags,
        "checkpoint_path": str(checkpoint_path) if checkpoint_path else None,
        "resumed_from_checkpoint": resumed_from_checkpoint,
        "resume_source_checkpoint": str(resume_path) if resume_path else None,
        "interrupted": False,
    }


def checkpoint_path_for(checkpoint_dir: Path, run_id: str) -> Path:
    return checkpoint_dir / f"extraction_v2_checkpoint_{run_id}.json"


class BenchmarkProgress:
    def __init__(
        self,
        *,
        state: dict[str, Any],
        checkpoint_path: Path | None,
        checkpoint_enabled: bool,
        checkpoint_every_pages: int,
        progress_enabled: bool,
        quiet: bool,
        verbose: bool,
        progress_every_pages: int,
    ) -> None:
        self.state = state
        self.checkpoint_path = checkpoint_path
        self.checkpoint_enabled = checkpoint_enabled
        self.checkpoint_every_pages = max(checkpoint_every_pages, 1)
        self.progress_enabled = progress_enabled and not quiet
        self.quiet = quiet
        self.verbose = verbose
        self.progress_every_pages = max(progress_every_pages, 1)
        self.pages_since_checkpoint = 0
        self.counters = Counter()

    def write_checkpoint(self, *, interrupted: bool = False, force: bool = False) -> None:
        if not self.checkpoint_enabled or not self.checkpoint_path:
            return
        if not force and self.pages_since_checkpoint < self.checkpoint_every_pages:
            return
        self.state["updated_at"] = iso_now()
        self.state["interrupted"] = bool(interrupted)
        write_json_atomic(self.checkpoint_path, self.state)
        self.pages_since_checkpoint = 0

    def handle_event(self, event: dict[str, Any]) -> None:
        event_name = event.get("event")
        case_id = str(event.get("case_id") or "")
        if event_name == "case_start":
            log(
                f"Case {case_id}: {Path(str(event.get('source_pdf') or '')).name} pages={event.get('total_pages', '?')}",
                quiet=not self.progress_enabled,
            )
            return
        if event_name == "native_page_complete":
            page = int(event.get("page_number") or 0)
            total = event.get("total_pages") or "?"
            native_count = int(event.get("native_candidate_count") or 0)
            self.counters["pages_processed"] += 1
            self.counters["native_candidates"] += native_count
            page_status = self.state.setdefault("vision_page_status", {}).setdefault(case_id, {}).setdefault(str(page), {})
            fallback_eligible = False
            if self.state["flags"].get("use_vision_fallback"):
                if self.state["flags"].get("vision_page_mode") == "all":
                    fallback_eligible = True
                elif (
                    int(event.get("native_text_length") or 0) == 0
                    or int(event.get("native_candidate_count") or 0) == 0
                    or int(event.get("native_numeric_or_text_count") or 0) == 0
                ):
                    fallback_eligible = True
            page_status.update(
                {
                    "case_id": case_id,
                    "page_number": page,
                    "native_candidate_count": native_count,
                    "fallback_eligible": fallback_eligible,
                    "fallback_attempted": bool(page_status.get("fallback_attempted", False)),
                    "candidate_count": int(page_status.get("candidate_count") or native_count),
                    "updated_at": iso_now(),
                }
            )
            if page % self.progress_every_pages == 0:
                log(
                    f"Case {case_id} page {page}/{total}: native candidates={native_count}, "
                    f"vision fallback={'enabled' if self.state['flags'].get('use_vision_fallback') else 'skipped'}",
                    quiet=not self.progress_enabled,
                )
            return
        if event_name == "vision_page_start":
            provider = str(event.get("provider") or "huggingface")
            self.counters[f"{provider}_attempted"] += 1
            log(
                f"Case {case_id} page {event.get('page_number')}/{event.get('total_pages', '?')}: "
                f"{provider_label(provider)} vision fallback attempting...",
                quiet=not self.progress_enabled,
            )
            return
        if event_name == "vision_page_skipped":
            provider = str(event.get("provider") or "huggingface")
            page = int(event.get("page_number") or 0)
            reason = str(event.get("reason") or "unknown")
            self.counters[f"{provider}_skipped"] += 1
            self.state["partial_vision_metrics"]["skipped"] += 1
            if reason == "max_limit_reached":
                self.state["partial_vision_metrics"]["max_limit_reached"] = int(
                    self.state["partial_vision_metrics"].get("max_limit_reached") or 0
                ) + 1
            page_status = self.state.setdefault("vision_page_status", {}).setdefault(case_id, {}).setdefault(str(page), {})
            page_status.update(
                {
                    "case_id": case_id,
                    "page_number": page,
                    "fallback_eligible": True,
                    "fallback_attempted": reason in {"resume_completed", "already_attempted"},
                    "fallback_skipped_reason": reason,
                    "updated_at": iso_now(),
                }
            )
            log(
                f"Case {case_id} page {page}: {provider_label(provider)} vision skipped ({reason})",
                quiet=not self.progress_enabled,
            )
            return
        if event_name != "vision_page_complete":
            return

        page = int(event.get("page_number") or 0)
        provider = str(event.get("provider") or "huggingface")
        succeeded = bool(event.get("succeeded"))
        candidates = [candidate for candidate in (event.get("candidates") or []) if isinstance(candidate, dict)]
        elapsed = float(event.get("elapsed_seconds") or 0)
        metrics = self.state["partial_vision_metrics"]
        metrics["attempted"] += 1
        if succeeded:
            metrics["succeeded"] += 1
            self.counters[f"{provider}_succeeded"] += 1
        else:
            metrics["failed"] += 1
            self.counters[f"{provider}_failed"] += 1
        diagnostics = event.get("diagnostics") if isinstance(event.get("diagnostics"), dict) else {}
        parser_failure_reason = diagnostics.get("parser_failure_reason")
        if provider == "huggingface" and diagnostics:
            if diagnostics.get("raw_response_preview"):
                metrics["hf_raw_response_preview_count"] = int(metrics.get("hf_raw_response_preview_count") or 0) + 1
            metrics["hf_parser_recovered_candidates"] = int(metrics.get("hf_parser_recovered_candidates") or 0) + int(
                diagnostics.get("normalized_candidate_count") or 0
            )
            if parser_failure_reason in {
                "output_not_json",
                "json_parsed_but_no_candidates_key",
                "qwen_items_parsed_no_candidates_after_normalization",
                "no_model_output",
            }:
                metrics["hf_parser_failed_pages"] = int(metrics.get("hf_parser_failed_pages") or 0) + 1
            if parser_failure_reason == "empty_candidates_returned":
                metrics["hf_empty_candidate_pages"] = int(metrics.get("hf_empty_candidate_pages") or 0) + 1
            if parser_failure_reason == "no_relevant_content_detected":
                metrics["hf_no_relevant_content_pages"] = int(metrics.get("hf_no_relevant_content_pages") or 0) + 1
            if parser_failure_reason:
                reasons = dict(metrics.get("hf_parser_failure_reasons") or {})
                reasons[parser_failure_reason] = int(reasons.get(parser_failure_reason) or 0) + 1
                metrics["hf_parser_failure_reasons"] = reasons
            self.state.setdefault("partial_vision_diagnostics", []).append(
                {
                    "case_id": case_id,
                    "page_number": page,
                    "provider": provider,
                    "succeeded": succeeded,
                    "candidate_count": len(candidates),
                    "diagnostics": diagnostics,
                }
            )
        self.counters[f"{provider}_candidates"] += len(candidates)
        page_status = self.state.setdefault("vision_page_status", {}).setdefault(case_id, {}).setdefault(str(page), {})
        page_status.update(
            {
                "case_id": case_id,
                "page_number": page,
                "fallback_eligible": True,
                "fallback_attempted": True,
                "fallback_succeeded": succeeded,
                "fallback_failed": not succeeded,
                "fallback_failure_reason": event.get("failure_reason"),
                "candidate_count": len(candidates),
                "extraction_method": f"{provider}_vision_fallback",
                "updated_at": iso_now(),
            }
        )
        completed_pages = self.state.setdefault("completed_vision_pages", {}).setdefault(case_id, [])
        if page not in completed_pages:
            completed_pages.append(page)
        self.state.setdefault("completed_page_identifiers", []).append(
            {"case_id": case_id, "page_number": page, "stage": f"{provider}_vision_fallback"}
        )
        partial_candidates = self.state.setdefault("partial_candidates_by_case", {}).setdefault(case_id, [])
        partial_candidates.extend(candidates)
        self.state["partial_candidates_by_case"][case_id] = dedupe_candidate_dicts(partial_candidates)
        if event.get("warnings") and self.verbose:
            self.state.setdefault("warnings", []).extend(str(item) for item in event.get("warnings") or [])
        outcome = "succeeded" if succeeded else "failed"
        detail = f", failure={event.get('failure_reason')}" if event.get("failure_reason") else ""
        log(
            f"Case {case_id} page {page}/{event.get('total_pages', '?')}: "
            f"{provider_label(provider)} vision {outcome} in {elapsed:.1f}s, candidates={len(candidates)}{detail}",
            quiet=not self.progress_enabled,
        )
        if self.verbose and diagnostics.get("raw_response_preview"):
            preview = str(diagnostics.get("raw_response_preview") or "").replace("\n", " ")[:160]
            log(f"Case {case_id} page {page}: raw response preview={preview}", quiet=not self.progress_enabled)
        self.pages_since_checkpoint += 1
        self.write_checkpoint(force=False)
        self.print_totals()

    def print_totals(self) -> None:
        if not self.progress_enabled:
            return
        log(
            "Progress: "
            f"pages={self.counters['pages_processed']}, "
            f"hf_attempted={self.counters['huggingface_attempted']}, "
            f"hf_succeeded={self.counters['huggingface_succeeded']}, "
            f"hf_failed={self.counters['huggingface_failed']}, "
            f"native_candidates={self.counters['native_candidates']}, "
            f"hf_candidates={self.counters['huggingface_candidates']}",
            quiet=False,
        )


def provider_label(provider: str) -> str:
    return "Hugging Face" if provider == "huggingface" else provider


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Extraction Pipeline v2 against benchmark_cases.")
    parser.add_argument("--cases-dir", type=Path, default=PROJECT_ROOT / "benchmark_cases")
    parser.add_argument("--case")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--limit-pages", type=int)
    parser.add_argument("--use-vision-fallback", action="store_true", help="Opt in to live vision fallback. Default is off.")
    parser.add_argument("--vision-provider", choices=["huggingface"], default="huggingface")
    parser.add_argument("--vision-max-pages", type=int)
    parser.add_argument(
        "--vision-page-mode",
        choices=["failed-native-only", "all"],
        default="failed-native-only",
    )
    parser.add_argument("--use-openai", action="store_true", help="Deprecated legacy flag; use Hugging Face --use-vision-fallback instead.")
    parser.add_argument("--no-openai", action="store_true", help="Legacy compatibility flag. Default path makes no OpenAI calls.")
    parser.add_argument(
        "--approve-private-pdf-openai",
        action="store_true",
        help="Acknowledge that benchmark PDF page images may be sent to OpenAI when --use-openai is enabled.",
    )
    parser.add_argument("--openai-max-pages", type=int, help="Deprecated legacy OpenAI option.")
    parser.add_argument(
        "--openai-page-mode",
        choices=["failed-native-only", "all"],
        default="failed-native-only",
        help="Deprecated legacy OpenAI option.",
    )
    parser.add_argument("--progress", action="store_true", default=True, help="Show live benchmark progress. Default is on.")
    parser.add_argument("--quiet", action="store_true", help="Suppress normal progress output.")
    parser.add_argument("--verbose", action="store_true", help="Include detailed failure/debug snippets.")
    parser.add_argument("--progress-every-pages", type=int, default=1)
    parser.add_argument("--checkpoint-dir", type=Path, default=DEFAULT_CHECKPOINT_DIR)
    parser.add_argument("--checkpoint-every-pages", type=int, default=1)
    parser.add_argument("--disable-checkpoint", action="store_true")
    parser.add_argument("--resume-from-checkpoint", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-md", type=Path)
    parser.add_argument("--manifest-json", type=Path, default=REPORTS_DIR / "benchmark_cases_manifest.json")
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def case_failure_report(case_data: dict[str, Any], exc: Exception) -> dict[str, Any]:
    return {
        "case_id": case_data.get("case_id"),
        "case_dir": case_data.get("case_dir"),
        "source_pdf": case_data.get("pdf_path"),
        "reference_available": bool(case_data.get("reference_available")),
        "reference_path": case_data.get("reference_path"),
        "reference_type": case_data.get("reference_type"),
        "status": "error",
        "stages": [],
        "pages_analyzed": 0,
        "candidate_count": 0,
        "native_candidate_count": 0,
        "huggingface_candidate_count": 0,
        "openai_candidate_count": 0,
        "row_type_counts": {},
        "warning_counts": {"case_failed": 1},
        "warnings": [f"Case failed without stopping the run: {exc}"],
        "candidates": [],
    }


async def async_main(argv: list[str] | None = None) -> int:
    explicit_dests = explicit_cli_dests(argv)
    args = parse_args(argv)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    started_monotonic = time.monotonic()
    started_at = iso_now()
    resumed_from_checkpoint = bool(args.resume_from_checkpoint)
    resume_state: dict[str, Any] | None = None
    if args.resume_from_checkpoint:
        resume_state = load_checkpoint(args.resume_from_checkpoint)
        apply_checkpoint_flags(args, resume_state, explicit_dests=explicit_dests)

    use_openai = bool(args.use_openai and not args.no_openai)
    approved, message = validate_private_pdf_openai_approval(use_openai, args.approve_private_pdf_openai)
    if not approved:
        print(message, file=sys.stderr)
        return 2

    manifest = load_or_discover_manifest(args.cases_dir, args.manifest_json)
    selected_cases = list((resume_state or {}).get("selected_cases") or select_ready_cases(manifest, args.case, args.all))
    run_id = args.run_id or (resume_state or {}).get("run_id") or utc_timestamp()
    checkpoint_enabled = not args.disable_checkpoint
    checkpoint_path = checkpoint_path_for(args.checkpoint_dir, run_id) if checkpoint_enabled else None
    flags = flags_snapshot(args, use_openai=use_openai)
    state = new_checkpoint_state(
        run_id=run_id,
        started_at=(resume_state or {}).get("started_at") or started_at,
        cases_dir=args.cases_dir,
        selected_cases=selected_cases,
        flags=flags,
        checkpoint_path=checkpoint_path,
        resumed_from_checkpoint=resumed_from_checkpoint,
        resume_path=args.resume_from_checkpoint,
    )
    if resume_state:
        state["completed_cases"] = list(resume_state.get("completed_cases") or [])
        state["completed_vision_pages"] = {
            case_id: sorted(pages)
            for case_id, pages in normalize_completed_pages(resume_state.get("completed_vision_pages")).items()
        }
        state["completed_page_identifiers"] = list(resume_state.get("completed_page_identifiers") or [])
        state["vision_page_status"] = dict(resume_state.get("vision_page_status") or {})
        state["partial_candidates_by_case"] = dict(resume_state.get("partial_candidates_by_case") or {})
        state["partial_case_reports"] = dict(resume_state.get("partial_case_reports") or {})
        resumed_metrics = dict(resume_state.get("partial_vision_metrics") or {})
        state["partial_vision_metrics"].update(resumed_metrics)
        state["partial_vision_diagnostics"] = list(resume_state.get("partial_vision_diagnostics") or [])
        state["failures"] = list(resume_state.get("failures") or [])
        state["warnings"] = list(resume_state.get("warnings") or [])

    progress = BenchmarkProgress(
        state=state,
        checkpoint_path=checkpoint_path,
        checkpoint_enabled=checkpoint_enabled,
        checkpoint_every_pages=args.checkpoint_every_pages,
        progress_enabled=bool(args.progress),
        quiet=bool(args.quiet),
        verbose=bool(args.verbose),
        progress_every_pages=args.progress_every_pages,
    )
    progress.write_checkpoint(force=True)
    log(f"Benchmark started at {state['started_at']} run_id={run_id}", quiet=args.quiet)
    log(f"Cases discovered={len(manifest.get('cases', []))}, selected={len(selected_cases)}", quiet=args.quiet)
    log(
        "Flags: "
        f"use_vision_fallback={bool(args.use_vision_fallback)}, "
        f"vision_provider={args.vision_provider}, "
        f"vision_page_mode={args.vision_page_mode}, "
        f"vision_max_pages={args.vision_max_pages}",
        quiet=args.quiet,
    )
    if checkpoint_path:
        log(f"Checkpoint path: {checkpoint_path}", quiet=args.quiet)
    checkpoint_max_pages = checkpoint_vision_max_pages(resume_state)
    previous_vision_pages_attempted = checkpoint_vision_attempt_count(resume_state)
    if resumed_from_checkpoint:
        log(f"Resuming from checkpoint: {args.resume_from_checkpoint}", quiet=args.quiet)
        log(
            "Resume flags: "
            f"checkpoint vision_max_pages={checkpoint_max_pages}, "
            f"effective vision_max_pages={args.vision_max_pages}",
            quiet=args.quiet,
        )
        log(f"Resume state: already attempted fallback pages={previous_vision_pages_attempted}", quiet=args.quiet)
        if (
            args.use_vision_fallback
            and args.vision_max_pages is not None
            and previous_vision_pages_attempted >= args.vision_max_pages
        ):
            log(
                "Effective vision max pages has already been reached by checkpoint; "
                "no additional fallback pages will be attempted.",
                quiet=args.quiet,
            )

    completed_cases = set(str(case_id) for case_id in state.get("completed_cases") or [])
    completed_vision_pages = normalize_completed_pages(state.get("completed_vision_pages"))
    case_reports_by_id = dict(state.get("partial_case_reports") or {})
    cases_skipped_because_fully_resolved = 0
    cases_partially_resumed = 0
    resume_can_attempt_more = not (
        resumed_from_checkpoint
        and args.use_vision_fallback
        and args.vision_max_pages is not None
        and previous_vision_pages_attempted >= args.vision_max_pages
    )
    pipeline = ExtractionV2Pipeline(
        use_vision_fallback=bool(args.use_vision_fallback),
        vision_provider=args.vision_provider,
        vision_max_pages=args.vision_max_pages,
        vision_page_mode=args.vision_page_mode,
        use_openai=use_openai,
        openai_max_pages=args.openai_max_pages,
        openai_page_mode=args.openai_page_mode,
        progress_callback=progress.handle_event,
        completed_vision_pages=completed_vision_pages,
        previous_vision_pages_attempted=previous_vision_pages_attempted,
    )
    try:
        for case_data in selected_cases:
            case_id = str(case_data.get("case_id") or "")
            if case_id in completed_cases and (not args.use_vision_fallback or not resume_can_attempt_more):
                cases_skipped_because_fully_resolved += 1
                log(f"Case {case_id}: skipped, already complete in checkpoint", quiet=args.quiet)
                continue
            if resumed_from_checkpoint and case_id in completed_cases:
                cases_partially_resumed += 1
                log(f"Case {case_id}: partially resolved in checkpoint; checking unattempted fallback pages", quiet=args.quiet)
            elif resumed_from_checkpoint:
                log(f"Case {case_id}: not previously processed; starting", quiet=args.quiet)
            log(f"Case {case_id}: starting {Path(str(case_data.get('pdf_path') or '')).name}", quiet=args.quiet)
            try:
                case_report = await pipeline.run_case(
                    benchmark_case_from_manifest(case_data),
                    limit_pages=args.limit_pages,
                    initial_candidates=(state.get("partial_candidates_by_case") or {}).get(case_id) or [],
                    completed_vision_pages=completed_vision_pages.get(case_id, set()),
                )
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                state.setdefault("failures", []).append({"case_id": case_id, "error": str(exc)})
                if args.verbose:
                    log(f"Case {case_id}: failed with {type(exc).__name__}: {exc}", quiet=args.quiet)
                case_report = case_failure_report(case_data, exc)
            case_reports_by_id[case_id] = case_report
            state.setdefault("partial_case_reports", {})[case_id] = case_report
            if case_id not in completed_cases:
                state.setdefault("completed_cases", []).append(case_id)
                completed_cases.add(case_id)
            progress.write_checkpoint(force=True)
            log(
                f"Case {case_id}: complete candidates={case_report.get('candidate_count', 0)} "
                f"hf_candidates={case_report.get('huggingface_candidate_count', 0)}",
                quiet=args.quiet,
            )
    except KeyboardInterrupt:
        progress.write_checkpoint(interrupted=True, force=True)
        log("Interrupted by Ctrl+C. Completed progress was saved to checkpoint.", quiet=args.quiet)
        if checkpoint_path:
            log(f"Checkpoint path: {checkpoint_path}", quiet=args.quiet)
        return 130

    case_reports = [
        case_reports_by_id[str(case.get("case_id") or "")]
        for case in selected_cases
        if str(case.get("case_id") or "") in case_reports_by_id
    ]
    output_json = args.output_json or default_output_path(REPORTS_DIR)
    output_md = args.output_md or output_json.with_suffix(".md")
    duration_seconds = round(time.monotonic() - started_monotonic, 3)
    total_vision_pages_attempted = int(getattr(pipeline, "_vision_pages_attempted_total", previous_vision_pages_attempted))
    additional_vision_pages_attempted = max(total_vision_pages_attempted - previous_vision_pages_attempted, 0)
    report = build_report(
        case_reports,
        cases_dir=str(args.cases_dir),
        output_json=output_json,
        limit_pages=args.limit_pages,
        use_openai=use_openai,
        use_vision_fallback=bool(args.use_vision_fallback),
        vision_provider=args.vision_provider,
        vision_page_mode=args.vision_page_mode if args.use_vision_fallback else None,
        vision_max_pages=args.vision_max_pages if args.use_vision_fallback else None,
        openai_page_mode=args.openai_page_mode if use_openai else None,
        openai_max_pages=args.openai_max_pages if use_openai else None,
        private_pdf_openai_approved=bool(use_openai and args.approve_private_pdf_openai),
        run_id=run_id,
        interrupted=False,
        resumed_from_checkpoint=resumed_from_checkpoint,
        checkpoint_path=str(checkpoint_path) if checkpoint_path else None,
        duration_seconds=duration_seconds,
        flags=flags,
        checkpoint_vision_max_pages=checkpoint_max_pages,
        effective_vision_max_pages=args.vision_max_pages if args.use_vision_fallback else None,
        previous_vision_pages_attempted=previous_vision_pages_attempted,
        additional_vision_pages_attempted=additional_vision_pages_attempted,
        total_vision_pages_attempted=total_vision_pages_attempted,
        cases_skipped_because_fully_resolved=cases_skipped_because_fully_resolved,
        cases_partially_resumed=cases_partially_resumed,
    )
    output_json.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    output_md.write_text(render_markdown(report), encoding="utf-8")
    state["interrupted"] = False
    state["final_report_json"] = str(output_json)
    state["final_report_md"] = str(output_md)
    progress.write_checkpoint(force=True)

    log(f"Extraction v2 report: {output_json}", quiet=args.quiet)
    log(f"Markdown summary: {output_md}", quiet=args.quiet)
    log(f"Cases processed: {report['aggregate_metrics']['total_cases_processed']}", quiet=args.quiet)
    log(f"Candidate rows: {report['aggregate_metrics']['total_candidate_rows']}", quiet=args.quiet)
    log(f"Hugging Face candidates: {report['aggregate_metrics'].get('huggingface_candidate_count', 0)}", quiet=args.quiet)
    log(f"OpenAI candidates: {report['aggregate_metrics'].get('openai_candidate_count', 0)}", quiet=args.quiet)
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
