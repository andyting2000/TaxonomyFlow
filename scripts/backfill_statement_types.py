import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from sqlalchemy import func, select, text, update

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import AsyncSessionLocal, ExtractedDataItem


@dataclass(frozen=True)
class BackfillCandidate:
    item_id: str
    page_id: str
    template_field_id: str
    resolved_statement_type: str
    extracted_label: Optional[str] = None


@dataclass(frozen=True)
class BackfillPlan:
    rows_scanned: int
    rows_eligible: int
    rows_resolvable: int
    rows_unresolved: int
    candidates: List[BackfillCandidate]


@dataclass(frozen=True)
class BackfillReport:
    rows_scanned: int
    rows_eligible: int
    rows_resolvable: int
    rows_updated: int
    rows_unresolved: int
    blank_count_before: int
    blank_count_after: int
    applied: bool
    displayed_candidate_limit: int
    displayed_candidates: List[BackfillCandidate]


def _is_blank_text(value: Any) -> bool:
    return not bool(str(value or "").strip())


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _blank_statement_type_condition():
    return func.coalesce(func.trim(ExtractedDataItem.statement_type), "") == ""


def _nonblank_template_field_condition():
    return func.coalesce(func.trim(ExtractedDataItem.template_field_id), "") != ""


def build_backfill_plan(
    *,
    rows_scanned: int,
    rows: Sequence[Any],
    statement_type_by_page_id: Mapping[str, str],
) -> BackfillPlan:
    candidates: List[BackfillCandidate] = []
    rows_eligible = 0
    rows_unresolved = 0

    for row in rows:
        statement_type = getattr(row, "statement_type", None)
        template_field_id = _normalize_text(getattr(row, "template_field_id", None))
        page_id = _normalize_text(getattr(row, "page_id", None))

        if not _is_blank_text(statement_type) or _is_blank_text(template_field_id):
            continue

        rows_eligible += 1
        resolved_statement_type = _normalize_text(
            statement_type_by_page_id.get(page_id)
        )
        if _is_blank_text(resolved_statement_type):
            rows_unresolved += 1
            continue

        candidates.append(
            BackfillCandidate(
                item_id=str(getattr(row, "id")),
                page_id=page_id,
                template_field_id=template_field_id,
                resolved_statement_type=resolved_statement_type,
                extracted_label=_normalize_text(getattr(row, "extracted_label", None)) or None,
            )
        )

    return BackfillPlan(
        rows_scanned=rows_scanned,
        rows_eligible=rows_eligible,
        rows_resolvable=len(candidates),
        rows_unresolved=rows_unresolved,
        candidates=candidates,
    )


async def _count_total_rows(session) -> int:
    result = await session.execute(
        select(func.count()).select_from(ExtractedDataItem)
    )
    return int(result.scalar_one())


async def _count_blank_statement_type_rows(session) -> int:
    result = await session.execute(
        select(func.count()).select_from(ExtractedDataItem).where(_blank_statement_type_condition())
    )
    return int(result.scalar_one())


async def _load_backfill_rows(session) -> List[Any]:
    result = await session.execute(
        select(
            ExtractedDataItem.id,
            ExtractedDataItem.page_id,
            ExtractedDataItem.template_field_id,
            ExtractedDataItem.statement_type,
            ExtractedDataItem.extracted_label,
        ).where(_blank_statement_type_condition(), _nonblank_template_field_condition())
    )
    return list(result.all())


async def _load_statement_type_by_page_id(session, page_ids: Sequence[str]) -> Dict[str, str]:
    unique_page_ids = [page_id for page_id in dict.fromkeys(
        _normalize_text(page_id) for page_id in page_ids
    ) if page_id]
    if not unique_page_ids:
        return {}

    result = await session.execute(
        select(
            ExtractedDataItem.page_id,
            ExtractedDataItem.statement_type,
        ).where(
            ExtractedDataItem.page_id.in_(unique_page_ids),
            func.coalesce(func.trim(ExtractedDataItem.statement_type), "") != "",
        )
    )

    statement_types_by_page: Dict[str, set[str]] = {}
    for page_id, statement_type in result.all():
        normalized_page_id = _normalize_text(page_id)
        normalized_statement_type = _normalize_text(statement_type)
        if not normalized_page_id or not normalized_statement_type:
            continue
        statement_types_by_page.setdefault(normalized_page_id, set()).add(normalized_statement_type)

    return {
        page_id: next(iter(statement_types))
        for page_id, statement_types in statement_types_by_page.items()
        if len(statement_types) == 1
    }


async def _apply_candidates(session, candidates: Sequence[BackfillCandidate]) -> int:
    updated_rows = 0
    for candidate in candidates:
        result = await session.execute(build_candidate_update_statement(candidate))
        updated_rows += int(result.rowcount or 0)

    return updated_rows


def build_candidate_update_statement(candidate: BackfillCandidate):
    return (
        update(ExtractedDataItem)
        .where(ExtractedDataItem.id == candidate.item_id)
        .where(_blank_statement_type_condition())
        .where(_nonblank_template_field_condition())
        .values(statement_type=candidate.resolved_statement_type)
    )


def render_report(report: BackfillReport) -> str:
    mode = "apply" if report.applied else "dry-run"
    lines = [
        "Statement type backfill",
        f"Mode: {mode}",
        "",
        f"rows_scanned: {report.rows_scanned}",
        f"rows_eligible: {report.rows_eligible}",
        f"rows_resolvable: {report.rows_resolvable}",
        f"rows_unresolved: {report.rows_unresolved}",
        f"rows_updated: {report.rows_updated}",
        f"statement_type_blank_before: {report.blank_count_before}",
        f"statement_type_blank_after: {report.blank_count_after}",
        f"blank_count_delta: {report.blank_count_before - report.blank_count_after}",
        "",
        f"displayed_candidate_limit: {report.displayed_candidate_limit}",
        f"displayed_candidate_count: {len(report.displayed_candidates)}",
    ]

    if report.displayed_candidates:
        lines.append("Candidate evidence:")
        for candidate in report.displayed_candidates:
            label_text = (
                f" extracted_label={candidate.extracted_label}"
                if candidate.extracted_label
                else ""
            )
            lines.append(
                "  - "
                f"item_id={candidate.item_id} "
                f"page_id={candidate.page_id} "
                f"template_field_id={candidate.template_field_id} "
                f"resolved_statement_type={candidate.resolved_statement_type}"
                f"{label_text}"
            )
        lines.append("")
    else:
        lines.extend([
            "Candidate evidence:",
            "  - none",
            "",
        ])

    lines.extend([
        "Note: dry-run is the default and does not modify rows.",
        "Note: only rows with blank/null statement_type and a template_field_id are considered.",
        "Note: apply mode re-checks blank statement_type and nonblank template_field_id for each candidate row before update.",
    ])
    return "\n".join(lines)


async def run_backfill(apply_changes: bool, displayed_candidate_limit: int = 25) -> BackfillReport:
    async with AsyncSessionLocal() as session:
        if not apply_changes:
            await session.execute(text("SET TRANSACTION READ ONLY"))

        total_rows = await _count_total_rows(session)
        blank_before = await _count_blank_statement_type_rows(session)
        rows = await _load_backfill_rows(session)
        statement_type_by_page_id = await _load_statement_type_by_page_id(
            session,
            [row.page_id for row in rows],
        )
        plan = build_backfill_plan(
            rows_scanned=total_rows,
            rows=rows,
            statement_type_by_page_id=statement_type_by_page_id,
        )

        rows_updated = 0
        blank_after = blank_before

        if apply_changes:
            rows_updated = await _apply_candidates(session, plan.candidates)
            await session.commit()
            blank_after = await _count_blank_statement_type_rows(session)
        else:
            await session.rollback()

        return BackfillReport(
            rows_scanned=plan.rows_scanned,
            rows_eligible=plan.rows_eligible,
            rows_resolvable=plan.rows_resolvable,
            rows_updated=rows_updated,
            rows_unresolved=plan.rows_unresolved,
            blank_count_before=blank_before,
            blank_count_after=blank_after,
            applied=apply_changes,
            displayed_candidate_limit=displayed_candidate_limit,
            displayed_candidates=plan.candidates[:displayed_candidate_limit],
        )


async def async_main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill blank extracted-data statement_type values from historical page state."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the backfill updates instead of running a dry-run preview.",
    )
    parser.add_argument(
        "--show-candidates",
        type=int,
        default=25,
        help="Maximum number of candidate rows to show in the report. Default: 25.",
    )
    args = parser.parse_args()

    report = await run_backfill(
        apply_changes=args.apply,
        displayed_candidate_limit=max(0, args.show_candidates),
    )
    print(render_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
