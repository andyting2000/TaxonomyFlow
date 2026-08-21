"""Discover local benchmark PDF/reference pairs without standardized filenames."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = PROJECT_ROOT / "reports"
PDF_EXTENSIONS = {".pdf"}
REFERENCE_EXTENSIONS = {".xml", ".xbrl", ".html"}
STRONG_REFERENCE_EXTENSIONS = {".xml", ".xbrl"}
STATUS_ORDER = (
    "ambiguous_pdf",
    "missing_pdf",
    "ambiguous_reference",
    "missing_reference",
    "ready",
)


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _reference_type(path: Path | None) -> str | None:
    if path is None:
        return None
    suffix = path.suffix.lower()
    if suffix == ".xbrl":
        return "xbrl"
    if suffix == ".xml":
        return "xml"
    if suffix == ".html":
        return "html_warning"
    return None


def _inventory(files: Sequence[Path]) -> list[dict[str, Any]]:
    return [
        {
            "name": path.name,
            "path": _display_path(path),
            "extension": path.suffix.lower(),
            "size_bytes": path.stat().st_size if path.exists() else None,
        }
        for path in sorted(files, key=lambda item: item.name.lower())
    ]


def discover_case(case_dir: Path) -> dict[str, Any]:
    files = [path for path in case_dir.iterdir() if path.is_file()]
    pdfs = [path for path in files if path.suffix.lower() in PDF_EXTENSIONS]
    references = [path for path in files if path.suffix.lower() in REFERENCE_EXTENSIONS]
    unexpected = [
        path
        for path in files
        if path.suffix.lower() not in PDF_EXTENSIONS
        and path.suffix.lower() not in REFERENCE_EXTENSIONS
        and path.name.lower() != "metadata.json"
    ]
    warnings: list[str] = []

    if len(pdfs) > 1:
        status = "ambiguous_pdf"
    elif not pdfs:
        status = "missing_pdf"
    elif len(references) > 1:
        status = "ambiguous_reference"
    elif not references:
        status = "missing_reference"
    else:
        status = "ready"

    if any(path.suffix.lower() == ".html" for path in references):
        warnings.append("HTML reference file discovered; verify it is true reference XBRL/XML, not a browser-rendered document.")
    if unexpected:
        warnings.append("Unexpected files present in case folder.")

    selected_pdf = pdfs[0] if len(pdfs) == 1 else None
    selected_reference = references[0] if len(references) == 1 else None
    metadata_path = case_dir / "metadata.json"
    metadata = None
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            warnings.append(f"metadata.json could not be parsed and was ignored: {exc}")

    return {
        "case_id": case_dir.name,
        "case_dir": _display_path(case_dir),
        "pdf_path": _display_path(selected_pdf) if selected_pdf else None,
        "reference_path": _display_path(selected_reference) if selected_reference else None,
        "reference_type": _reference_type(selected_reference),
        "reference_available": selected_reference is not None and selected_reference.suffix.lower() in STRONG_REFERENCE_EXTENSIONS,
        "status": status,
        "warnings": warnings,
        "file_inventory": _inventory(files),
        "pdf_files": [_display_path(path) for path in sorted(pdfs, key=lambda item: item.name.lower())],
        "reference_files": [_display_path(path) for path in sorted(references, key=lambda item: item.name.lower())],
        "unexpected_files": [_display_path(path) for path in sorted(unexpected, key=lambda item: item.name.lower())],
        "metadata": metadata,
        "metadata_required": False,
    }


def discover_benchmark_cases(cases_dir: Path) -> dict[str, Any]:
    case_dirs = [
        path
        for path in sorted(cases_dir.iterdir(), key=lambda item: item.name.lower())
        if path.is_dir()
    ] if cases_dir.exists() else []
    cases = [discover_case(case_dir) for case_dir in case_dirs]
    status_counts = Counter(case["status"] for case in cases)
    root_files = [path for path in cases_dir.iterdir() if path.is_file()] if cases_dir.exists() else []
    return {
        "run_metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "script": "scripts/discover_benchmark_cases.py",
            "read_only": True,
            "database_mutated": False,
            "production_behavior_changed": False,
            "cases_dir": _display_path(cases_dir),
            "metadata_json_required": False,
        },
        "cases_dir": _display_path(cases_dir),
        "case_count": len(cases),
        "ready_count": status_counts.get("ready", 0),
        "status_counts": dict(sorted(status_counts.items())),
        "cases": cases,
        "root_file_inventory": _inventory(root_files),
        "schema_note": "Each immediate subfolder is one case. Filenames are not standardized; discovery uses file extensions.",
    }


def render_console_summary(manifest: dict[str, Any]) -> str:
    lines = [
        f"Benchmark cases: {manifest['case_count']}",
        f"Ready cases: {manifest['ready_count']}",
    ]
    for status in STATUS_ORDER:
        count = manifest.get("status_counts", {}).get(status, 0)
        if count:
            lines.append(f"{status}: {count}")
    for case in manifest.get("cases", []):
        warnings = "; ".join(case.get("warnings") or [])
        suffix = f" ({warnings})" if warnings else ""
        lines.append(f"- {case['case_id']}: {case['status']}{suffix}")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover benchmark case folders.")
    parser.add_argument("--cases-dir", type=Path, default=PROJECT_ROOT / "benchmark_cases")
    parser.add_argument("--output-json", type=Path, default=REPORTS_DIR / "benchmark_cases_manifest.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    manifest = discover_benchmark_cases(args.cases_dir)
    args.output_json.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(render_console_summary(manifest))
    print(f"Manifest: {args.output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
