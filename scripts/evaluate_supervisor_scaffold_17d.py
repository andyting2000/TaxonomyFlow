"""Generate local Supervisor review scaffold reports for #17D-A."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.supervisor_mapping_review import (  # noqa: E402
    assert_supervisor_payload_is_leakage_safe,
    build_supervisor_prompt,
    build_supervisor_review_payload,
    mock_supervisor_review,
    summarize_supervisor_review,
)


DEFAULT_PREDICTIONS_REPORT = PROJECT_ROOT / "reports" / "golden_mbrs_fewshot_qwen_predictions_17b.json"
DEFAULT_ERROR_REPORT = PROJECT_ROOT / "reports" / "golden_mbrs_fewshot_qwen_error_analysis_17b.json"
DEFAULT_PLAYBOOK_REPORT = PROJECT_ROOT / "reports" / "fs_mpers_concept_playbook_17d_pre.json"
DEFAULT_PAYLOAD_REPORT = PROJECT_ROOT / "reports" / "fs_mpers_rag_payload_examples_17d_pre.json"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _resolve(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate


def _display(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _mapper_suggestion(row: Mapping[str, Any]) -> Mapping[str, Any]:
    return row.get("fewshot_qwen_prediction") or row.get("qwen_prediction") or {}


def _safe_review_record(payload: Mapping[str, Any], review: Mapping[str, Any]) -> dict[str, Any]:
    mapper = payload.get("mapper_suggestion") or {}
    return {
        "row": dict(payload.get("row") or {}),
        "mapper_selection": {
            "status": mapper.get("status"),
            "selected_template_field_id": mapper.get("selected_template_field_id"),
            "selected_concept_qname": mapper.get("selected_concept_qname"),
            "confidence": mapper.get("confidence"),
            "confidence_tier": mapper.get("confidence_tier"),
            "reason": mapper.get("reason"),
        },
        "candidate_count": len(payload.get("candidate_concepts") or []),
        "retrieved_card_count": len(payload.get("retrieved_concept_cards") or []),
        "retrieved_fewshot_example_count": len(payload.get("retrieved_fewshot_examples") or []),
        "missing_concept_card_diagnostics": dict(payload.get("missing_concept_card_diagnostics") or {}),
        "supervisor_review": dict(review),
    }


def _examples(records: Sequence[Mapping[str, Any]], issue_type: str | None = None, *, decision: str | None = None, limit: int = 3) -> list[dict[str, Any]]:
    selected = []
    for record in records:
        review = record.get("supervisor_review") or {}
        if decision and review.get("review_decision") != decision:
            continue
        if issue_type and not any(issue.get("type") == issue_type for issue in review.get("issues") or []):
            continue
        selected.append(
            {
                "row": record.get("row"),
                "mapper_selection": record.get("mapper_selection"),
                "supervisor_review": review,
                "missing_concept_card_diagnostics": record.get("missing_concept_card_diagnostics"),
            }
        )
        if len(selected) >= limit:
            break
    return selected


def build_reports(
    *,
    golden_dir: str | Path,
    predictions_report_path: str | Path = DEFAULT_PREDICTIONS_REPORT,
    error_report_path: str | Path = DEFAULT_ERROR_REPORT,
    playbook_report_path: str | Path = DEFAULT_PLAYBOOK_REPORT,
    rag_payload_report_path: str | Path = DEFAULT_PAYLOAD_REPORT,
    mock: bool = True,
    report_only: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    predictions_path = _resolve(predictions_report_path)
    error_path = _resolve(error_report_path)
    playbook_path = _resolve(playbook_report_path)
    rag_payload_path = _resolve(rag_payload_report_path)
    predictions = _read_json(predictions_path)
    playbook = _read_json(playbook_path)
    rows = [row for row in predictions.get("strict_scoring_rows") or [] if isinstance(row, Mapping)]

    review_records: list[dict[str, Any]] = []
    payload_examples: list[dict[str, Any]] = []
    leakage_errors: list[str] = []
    reviews: list[dict[str, Any]] = []

    for row in rows:
        mapper = _mapper_suggestion(row)
        payload = build_supervisor_review_payload(
            row,
            mapper_suggestion=mapper,
            candidate_concepts=mapper.get("candidate_concepts") or [],
            playbook=playbook,
        )
        try:
            assert_supervisor_payload_is_leakage_safe(payload)
        except ValueError as exc:
            leakage_errors.append(str(exc))

        review = (
            {
                "review_decision": "needs_human_review",
                "risk_level": "medium",
                "reason": "Report-only mode did not run the deterministic mock reviewer.",
                "issues": [{"type": "other", "description": "report_only_mode"}],
                "recommended_action": "keep_for_human_review",
                "confidence_adjustment": "decrease",
                "safe_to_accept": False,
            }
            if report_only and not mock
            else mock_supervisor_review(payload)
        )
        reviews.append(review)
        review_records.append(_safe_review_record(payload, review))
        if len(payload_examples) < 8:
            payload_examples.append(
                {
                    "row": dict(payload.get("row") or {}),
                    "payload": payload,
                    "supervisor_prompt": build_supervisor_prompt(payload),
                    "mock_review": review,
                }
            )

    summary = summarize_supervisor_review(reviews)
    metadata = {
        "feature": "17D-A",
        "golden_dir": str(golden_dir),
        "source_reports": {
            "predictions": _display(predictions_path),
            "error_analysis": _display(error_path),
            "concept_playbook": _display(playbook_path),
            "rag_payload_examples": _display(rag_payload_path),
        },
        "mock_mode": bool(mock),
        "report_only": bool(report_only),
        "local_only": True,
        "external_llm_called": False,
        "auditor_xml_sent_externally": False,
        "parsed_xml_facts_sent_externally": False,
        "target_gold_answers_sent_externally": False,
        "database_mutated": False,
        "production_job_mutated": False,
        "confirmed_tag_id_automated": False,
        "xbrl_generated": False,
        "arelle_run": False,
        "azure_di_extraction_changed": False,
        "react_ui_changed": False,
    }
    scaffold = {
        "run_metadata": metadata,
        "summary": summary,
        "examples": {
            "broad_substitute_detection": _examples(review_records, "broad_substitute"),
            "missing_concept_card_diagnostics": _examples(review_records, "missing_concept_card"),
            "safe_accept": _examples(review_records, decision="agree"),
            "reject_or_human_review": _examples(
                [record for record in review_records if (record.get("supervisor_review") or {}).get("review_decision") != "agree"],
                limit=5,
            ),
        },
        "leakage_safety": {
            "payloads_checked": len(rows),
            "leakage_errors": leakage_errors,
            "external_llm_called": False,
            "auditor_source_included": False,
            "reference_fact_details_included": False,
            "target_answer_included": False,
            "scoring_labels_included": False,
        },
        "review_records": review_records,
    }
    payload_report = {
        "run_metadata": metadata,
        "payload_example_count": len(payload_examples),
        "payload_examples": payload_examples,
    }
    return scaffold, payload_report


def _markdown_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    output = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        output.append("| " + " | ".join(str(value).replace("|", "\\|") for value in row) + " |")
    return "\n".join(output)


def render_scaffold_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    risk_rows = [[key, value] for key, value in (summary.get("risk_level_counts") or {}).items()]
    issue_rows = [[key, value] for key, value in (summary.get("issue_type_counts") or {}).items()]
    return "\n\n".join(
        [
            "# Supervisor Mapping Review Scaffold #17D-A",
            f"- Total reviewed: `{summary.get('total_reviewed')}`",
            f"- Agree: `{summary.get('agree')}`",
            f"- Disagree: `{summary.get('disagree')}`",
            f"- Needs human review: `{summary.get('needs_human_review')}`",
            f"- Safe to accept: `{summary.get('safe_to_accept')}`",
            "## Risk Levels",
            _markdown_table(["Risk Level", "Count"], risk_rows),
            "## Issue Types",
            _markdown_table(["Issue Type", "Count"], issue_rows),
            "## Safety",
            f"- External LLM called: `{(report.get('run_metadata') or {}).get('external_llm_called')}`",
            f"- Leakage errors: `{len((report.get('leakage_safety') or {}).get('leakage_errors') or [])}`",
        ]
    ) + "\n"


def render_payload_markdown(report: Mapping[str, Any]) -> str:
    rows = []
    for example in report.get("payload_examples") or []:
        payload = example.get("payload") or {}
        review = example.get("mock_review") or {}
        rows.append(
            [
                (payload.get("row") or {}).get("label"),
                len(payload.get("candidate_concepts") or []),
                len(payload.get("retrieved_concept_cards") or []),
                review.get("review_decision"),
                review.get("risk_level"),
            ]
        )
    return "\n\n".join(
        [
            "# Supervisor Mapping Review Payload Examples #17D-A",
            _markdown_table(["Label", "Candidates", "Cards", "Mock Decision", "Risk"], rows),
        ]
    ) + "\n"


def write_reports(
    *,
    golden_dir: str | Path,
    reports_dir: str | Path = PROJECT_ROOT / "reports",
    mock: bool = True,
    report_only: bool = False,
) -> dict[str, Path]:
    reports_root = _resolve(reports_dir)
    scaffold, payloads = build_reports(golden_dir=golden_dir, mock=mock, report_only=report_only)
    paths = {
        "scaffold_json": reports_root / "supervisor_mapping_review_scaffold_17d.json",
        "scaffold_md": reports_root / "supervisor_mapping_review_scaffold_17d.md",
        "payload_examples_json": reports_root / "supervisor_mapping_review_payload_examples_17d.json",
        "payload_examples_md": reports_root / "supervisor_mapping_review_payload_examples_17d.md",
    }
    _write_json(paths["scaffold_json"], scaffold)
    paths["scaffold_md"].write_text(render_scaffold_markdown(scaffold), encoding="utf-8")
    _write_json(paths["payload_examples_json"], payloads)
    paths["payload_examples_md"].write_text(render_payload_markdown(payloads), encoding="utf-8")
    return paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate local Supervisor mapping review scaffold for #17D-A.")
    parser.add_argument("--golden-dir", default="benchmark_mbrs_pairs")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--mock", action="store_true", help="Run deterministic local mock reviewer.")
    parser.add_argument("--report-only", action="store_true", help="Generate report-only placeholder decisions without live LLM.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    use_mock = bool(args.mock or not args.report_only)
    paths = write_reports(
        golden_dir=args.golden_dir,
        reports_dir=args.reports_dir,
        mock=use_mock,
        report_only=bool(args.report_only),
    )
    scaffold = _read_json(paths["scaffold_json"])
    print("supervisor_scaffold_reports", json.dumps({key: str(value) for key, value in paths.items()}, sort_keys=True))
    print("supervisor_mock_summary", json.dumps(scaffold.get("summary") or {}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
