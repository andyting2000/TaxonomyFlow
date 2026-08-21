"""Read-only audit of generated XBRL facts against extracted job rows."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from lxml import etree
from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database import AsyncSessionLocal, ExtractedDataItem, FilingJob, FinancialStatementPage
from file_safety import safe_filename_component
from scripts.extraction_metrics import NEGATIVE_VALUE_RE


XBRLI_NS = "http://www.xbrl.org/2003/instance"
LINK_NS = "http://www.xbrl.org/2003/linkbase"
XBRLDI_NS = "http://xbrl.org/2006/xbrldi"
DEFAULT_UPLOADS_XBRL_DIR = Path("uploads/xbrl")
DEFAULT_REPORTS_DIR = Path("reports")
STATIC_DOCUMENT_FACT_CONCEPTS = {
    "ssmt-dei:DescriptionOfPresentationCurrency",
    "ssmt-dei:LevelOfRoundingUsedInFinancialStatements",
    "ssmt-dei:NameAndVersionOfSoftwareUsedToGenerateXBRLFile",
    "ssmt-dei:TaxonomyVersion",
    "ssmt:DisclosureOnWhetherCompanysSharesAreTradedOnAnyOfficialStockExchange",
    "ssmt:DisclosureOfWhetherCompanyRegulatedByBankNegaraMalaysiaAtFinancialYearEnd",
    "ssmt:DateOfFinancialStatementsApprovedByBoardOfDirectors",
    "ssmt:DisclosureOfDirectorsReportExplanatory",
}
SAMPLE_LIMIT = 50


@dataclass(frozen=True)
class ExpectedFact:
    item_id: str
    page_id: str | None
    page_number: int | None
    extracted_label: str | None
    extracted_value: str | None
    statement_type: str | None
    template_field_id: str | None
    confirmed_tag_id: int | None
    concept_source: str
    concept: str
    context_ref: str
    unit_ref: str
    value: str
    value_year: int | None
    source_value_column: str
    signed_value_suspicious: bool

    @property
    def match_key(self) -> tuple[str, str, str, str]:
        return (self.concept, self.context_ref, self.unit_ref, self.value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "page_id": self.page_id,
            "page_number": self.page_number,
            "extracted_label": self.extracted_label,
            "extracted_value": self.extracted_value,
            "statement_type": self.statement_type,
            "template_field_id": self.template_field_id,
            "confirmed_tag_id": self.confirmed_tag_id,
            "concept_source": self.concept_source,
            "concept": self.concept,
            "context_ref": self.context_ref,
            "unit_ref": self.unit_ref,
            "value": self.value,
            "value_year": self.value_year,
            "source_value_column": self.source_value_column,
            "signed_value_suspicious": self.signed_value_suspicious,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit generated XBRL facts against extracted rows for a job."
    )
    parser.add_argument("--job-id", type=int, required=True, help="Filing job ID to audit.")
    parser.add_argument(
        "--xbrl-path",
        type=Path,
        help="Optional generated XBRL path. Defaults to the generator naming convention.",
    )
    parser.add_argument("--json", action="store_true", help="Print the full report JSON.")
    return parser.parse_args()


def _qname_parts(element: etree._Element) -> tuple[str | None, str]:
    qname = etree.QName(element)
    return qname.namespace, qname.localname


def _prefix_for_namespace(nsmap: dict[str | None, str], namespace: str | None) -> str | None:
    if not namespace:
        return None
    for prefix, uri in nsmap.items():
        if uri == namespace:
            return prefix
    return None


def _concept_name(nsmap: dict[str | None, str], namespace: str | None, local_name: str) -> str:
    prefix = _prefix_for_namespace(nsmap, namespace)
    return f"{prefix}:{local_name}" if prefix else local_name


def _is_fact_element(element: etree._Element) -> bool:
    namespace, local_name = _qname_parts(element)
    if namespace == XBRLI_NS and local_name in {"context", "unit"}:
        return False
    if namespace == LINK_NS and local_name == "schemaRef":
        return False
    return True


def parse_xbrl_instance(xbrl_path: Path) -> dict[str, Any]:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    tree = etree.parse(str(xbrl_path), parser)
    root = tree.getroot()
    nsmap = dict(root.nsmap)
    facts: list[dict[str, Any]] = []

    for child in root:
        if not isinstance(child.tag, str) or not _is_fact_element(child):
            continue
        namespace, local_name = _qname_parts(child)
        concept = _concept_name(nsmap, namespace, local_name)
        value = (child.text or "").strip()
        facts.append(
            {
                "concept": concept,
                "namespace": namespace,
                "prefix": _prefix_for_namespace(nsmap, namespace),
                "local_name": local_name,
                "contextRef": child.get("contextRef"),
                "unitRef": child.get("unitRef"),
                "decimals": child.get("decimals"),
                "value": value,
                "is_numeric": _is_numeric(value),
            }
        )

    contexts = _summarize_contexts(root)
    units = _summarize_units(root)
    return {
        "facts": facts,
        "contexts": contexts,
        "units": units,
        "schema_refs": _schema_refs(root),
        "namespaces": {str(k): v for k, v in nsmap.items()},
    }


def _schema_refs(root: etree._Element) -> list[str]:
    schema_refs = []
    for child in root:
        if not isinstance(child.tag, str):
            continue
        namespace, local_name = _qname_parts(child)
        if namespace == LINK_NS and local_name == "schemaRef":
            href = child.get("{http://www.w3.org/1999/xlink}href") or child.get("href")
            if href:
                schema_refs.append(href)
    return schema_refs


def _summarize_contexts(root: etree._Element) -> dict[str, Any]:
    contexts = {}
    for context in root.findall(f"{{{XBRLI_NS}}}context"):
        context_id = context.get("id")
        if not context_id:
            continue
        period = context.find(f"{{{XBRLI_NS}}}period")
        period_type = "unknown"
        period_values: dict[str, str] = {}
        if period is not None:
            instant = period.find(f"{{{XBRLI_NS}}}instant")
            start = period.find(f"{{{XBRLI_NS}}}startDate")
            end = period.find(f"{{{XBRLI_NS}}}endDate")
            if instant is not None:
                period_type = "instant"
                period_values["instant"] = (instant.text or "").strip()
            elif start is not None or end is not None:
                period_type = "duration"
                period_values["startDate"] = (start.text or "").strip() if start is not None else ""
                period_values["endDate"] = (end.text or "").strip() if end is not None else ""
        dimensions = []
        for member in context.findall(f".//{{{XBRLDI_NS}}}explicitMember"):
            dimensions.append(
                {
                    "dimension": member.get("dimension"),
                    "member": (member.text or "").strip(),
                }
            )
        contexts[context_id] = {
            "period_type": period_type,
            "period": period_values,
            "dimension_count": len(dimensions),
            "dimensions": dimensions,
        }
    counts = Counter(value["period_type"] for value in contexts.values())
    return {
        "count": len(contexts),
        "ids": sorted(contexts),
        "period_type_counts": dict(sorted(counts.items())),
        "details": contexts,
    }


def _summarize_units(root: etree._Element) -> dict[str, Any]:
    units = {}
    for unit in root.findall(f"{{{XBRLI_NS}}}unit"):
        unit_id = unit.get("id")
        if not unit_id:
            continue
        measures = [
            (measure.text or "").strip()
            for measure in unit.findall(f".//{{{XBRLI_NS}}}measure")
        ]
        units[unit_id] = {"measures": measures}
    return {"count": len(units), "ids": sorted(units), "details": units}


def _is_numeric(value: str | None) -> bool:
    if value is None or value == "":
        return False
    try:
        Decimal(value.replace(",", ""))
        return True
    except InvalidOperation:
        return False


def _clean_numeric_value(raw_value: str | None) -> str | None:
    if not isinstance(raw_value, str):
        return None
    cleaned = raw_value.replace(",", "").replace(" ", "").strip()
    if not cleaned:
        return None
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]
    cleaned = re.sub(r"[^\d.-]", "", cleaned)
    if not cleaned or cleaned in ["-", ".", "-."]:
        return "0"
    try:
        float(cleaned)
    except Exception:
        return "0"
    return cleaned


def _has_suspicious_signed_raw_value(raw_value: str | None) -> bool:
    return bool(NEGATIVE_VALUE_RE.search(str(raw_value or "")))


def _period_type_for_item(item: ExtractedDataItem) -> str:
    if item.confirmed_tag and item.confirmed_tag.period_type:
        return item.confirmed_tag.period_type
    statement_type = (item.statement_type or "").lower()
    if any(term in statement_type for term in ["position", "balance", "assets", "liabilities"]):
        return "instant"
    return "duration"


def _context_ids_for_fye(financial_year_end: date) -> dict[str, str]:
    current_start = date(financial_year_end.year - 1, financial_year_end.month, financial_year_end.day)
    current_start = date.fromordinal(current_start.toordinal() + 1)
    current_end = financial_year_end
    prior_end = date(financial_year_end.year - 1, financial_year_end.month, financial_year_end.day)
    prior_start = date.fromordinal(date(financial_year_end.year - 2, financial_year_end.month, financial_year_end.day).toordinal() + 1)
    current_duration = f"fromto_{current_start.strftime('%Y%m%d')}_{current_end.strftime('%Y%m%d')}"
    current_instant = f"asof_{current_end.strftime('%Y%m%d')}"
    prior_duration = f"fromto_{prior_start.strftime('%Y%m%d')}_{prior_end.strftime('%Y%m%d')}"
    prior_instant = f"asof_{prior_end.strftime('%Y%m%d')}"
    return {
        "current_duration": current_duration,
        "current_instant": current_instant,
        "prior_duration": prior_duration,
        "prior_instant": prior_instant,
        "current_duration_separate": f"{current_duration}_SeparateMember",
        "current_instant_separate": f"{current_instant}_SeparateMember",
        "prior_instant_separate": f"{prior_instant}_SeparateMember",
    }


def _select_context_id(
    item: ExtractedDataItem,
    value_year: int | None,
    financial_year_end: date,
) -> str:
    period_type = _period_type_for_item(item)
    period_prefix = "current"
    if value_year is not None and value_year < financial_year_end.year:
        period_prefix = "prior"
    contexts = _context_ids_for_fye(financial_year_end)
    context_key = f"{period_prefix}_{period_type}_separate"
    if context_key not in contexts:
        context_key = f"{period_prefix}_{period_type}"
    return contexts.get(context_key, contexts["current_duration"])


def _concept_for_item(item: ExtractedDataItem) -> tuple[str | None, str | None]:
    if item.confirmed_tag:
        return f"{item.confirmed_tag.namespace}:{item.confirmed_tag.xbrl_tag}", "confirmed_tag"
    if item.template_field_id and ":" in item.template_field_id:
        return item.template_field_id, "template_field_id"
    return None, None


def expected_facts_for_job(job: FilingJob) -> list[ExpectedFact]:
    financial_year_end = _as_date(job.financial_year_end)
    expected: list[ExpectedFact] = []
    for page in sorted(job.pages, key=lambda candidate: candidate.page_number or 0):
        for item in sorted(page.extracted_items, key=lambda candidate: str(candidate.id)):
            if not item.is_reviewed or not (item.confirmed_tag or item.template_field_id):
                continue
            concept, concept_source = _concept_for_item(item)
            if not concept or not concept_source:
                continue
            current_value = _clean_numeric_value(item.extracted_value)
            if current_value is not None and item.financial_year:
                expected.append(
                    _expected_fact(
                        item=item,
                        page=page,
                        concept=concept,
                        concept_source=concept_source,
                        value=current_value,
                        value_year=item.financial_year,
                        source_value_column="extracted_value",
                        financial_year_end=financial_year_end,
                    )
                )
            prior_value = _clean_numeric_value(item.value_previous_year)
            if prior_value is not None and item.financial_year_previous:
                expected.append(
                    _expected_fact(
                        item=item,
                        page=page,
                        concept=concept,
                        concept_source=concept_source,
                        value=prior_value,
                        value_year=item.financial_year_previous,
                        source_value_column="value_previous_year",
                        financial_year_end=financial_year_end,
                    )
                )
    return expected


def _expected_fact(
    item: ExtractedDataItem,
    page: FinancialStatementPage,
    concept: str,
    concept_source: str,
    value: str,
    value_year: int | None,
    source_value_column: str,
    financial_year_end: date,
) -> ExpectedFact:
    raw_value = item.extracted_value if source_value_column == "extracted_value" else item.value_previous_year
    return ExpectedFact(
        item_id=str(item.id),
        page_id=str(page.id),
        page_number=page.page_number,
        extracted_label=item.extracted_label,
        extracted_value=raw_value,
        statement_type=item.statement_type,
        template_field_id=item.template_field_id,
        confirmed_tag_id=item.confirmed_tag_id,
        concept_source=concept_source,
        concept=concept,
        context_ref=_select_context_id(item, value_year, financial_year_end),
        unit_ref="MYR",
        value=value,
        value_year=value_year,
        source_value_column=source_value_column,
        signed_value_suspicious=_has_suspicious_signed_raw_value(raw_value),
    )


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise ValueError(f"Expected date/datetime financial year end, got {type(value)!r}")


def default_xbrl_path_for_job(job: FilingJob) -> Path:
    registration_number = safe_filename_component(job.registration_number, fallback="UNKNOWN")
    financial_year_end = _as_date(job.financial_year_end)
    return DEFAULT_UPLOADS_XBRL_DIR / f"SSM_FS-MPERS_{registration_number}_{financial_year_end.strftime('%Y%m%d')}.xbrl"


def summarize_facts(facts: list[dict[str, Any]]) -> dict[str, Any]:
    context_refs = [fact.get("contextRef") for fact in facts if fact.get("contextRef")]
    unit_refs = [fact.get("unitRef") for fact in facts if fact.get("unitRef")]
    duplicate_key_counts = Counter(
        (fact["concept"], fact.get("contextRef") or "", fact.get("unitRef") or "")
        for fact in facts
    )
    identical_key_counts = Counter(
        (
            fact["concept"],
            fact.get("contextRef") or "",
            fact.get("unitRef") or "",
            fact.get("value") or "",
        )
        for fact in facts
    )
    duplicate_groups = _counter_groups(duplicate_key_counts, ["concept", "contextRef", "unitRef"])
    identical_groups = _counter_groups(identical_key_counts, ["concept", "contextRef", "unitRef", "value"])
    numeric_without_unit = [
        fact
        for fact in facts
        if fact.get("is_numeric") and not fact.get("unitRef")
    ]
    negative_numeric = [
        fact
        for fact in facts
        if fact.get("is_numeric") and Decimal(str(fact["value"]).replace(",", "")) < 0
    ]
    return {
        "total_generated_facts": len(facts),
        "facts_by_namespace": dict(sorted(Counter(fact.get("namespace") or "" for fact in facts).items())),
        "facts_by_prefix": dict(sorted(Counter(fact.get("prefix") or "" for fact in facts).items())),
        "facts_by_concept": dict(sorted(Counter(fact["concept"] for fact in facts).items())),
        "facts_with_contextRef": len(context_refs),
        "facts_with_unitRef": len(unit_refs),
        "monetary_facts_without_unitRef": {
            "count": len(numeric_without_unit),
            "samples": numeric_without_unit[:SAMPLE_LIMIT],
        },
        "duplicate_concept_context_unit_facts": {
            "group_count": len(duplicate_groups),
            "groups": duplicate_groups[:SAMPLE_LIMIT],
        },
        "concepts_multiple_times_identical_value_context_unit": {
            "group_count": len(identical_groups),
            "groups": identical_groups[:SAMPLE_LIMIT],
        },
        "negative_numeric_facts": {
            "count": len(negative_numeric),
            "samples": negative_numeric[:SAMPLE_LIMIT],
        },
    }


def _counter_groups(counter: Counter, field_names: list[str]) -> list[dict[str, Any]]:
    groups = []
    for key, count in counter.items():
        if count <= 1:
            continue
        groups.append({**dict(zip(field_names, key)), "count": count})
    return sorted(groups, key=lambda group: (-group["count"], tuple(str(group[name]) for name in field_names)))


def compare_expected_to_generated(
    expected_facts: list[ExpectedFact],
    generated_facts: list[dict[str, Any]],
) -> dict[str, Any]:
    generated_counter = Counter(
        (
            fact["concept"],
            fact.get("contextRef") or "",
            fact.get("unitRef") or "",
            fact.get("value") or "",
        )
        for fact in generated_facts
    )
    represented = []
    not_represented = []
    for expected in expected_facts:
        if generated_counter[expected.match_key] > 0:
            generated_counter[expected.match_key] -= 1
            represented.append(expected)
        else:
            not_represented.append(expected)

    leftover_generated = []
    for key, count in generated_counter.items():
        if count <= 0:
            continue
        concept, context_ref, unit_ref, value = key
        traceability = (
            "static_document_fact"
            if concept in STATIC_DOCUMENT_FACT_CONCEPTS
            else "not_traceable_to_extracted_row"
        )
        leftover_generated.append(
            {
                "concept": concept,
                "contextRef": context_ref,
                "unitRef": unit_ref,
                "value": value,
                "count": count,
                "traceability": traceability,
            }
        )

    return {
        "expected_generated_fact_count": len(expected_facts),
        "represented_expected_fact_count": len(represented),
        "not_represented_expected_fact_count": len(not_represented),
        "representation_rate": round(len(represented) / len(expected_facts), 4) if expected_facts else None,
        "extracted_rows_not_represented_in_xbrl": {
            "count": len(not_represented),
            "samples": [fact.to_dict() for fact in not_represented[:SAMPLE_LIMIT]],
        },
        "xbrl_facts_not_traceable_to_extracted_rows": {
            "count": sum(item["count"] for item in leftover_generated),
            "groups": sorted(leftover_generated, key=lambda item: (-item["count"], item["concept"]))[:SAMPLE_LIMIT],
        },
    }


def summarize_expected_facts(expected_facts: list[ExpectedFact]) -> dict[str, Any]:
    by_item: defaultdict[str, list[ExpectedFact]] = defaultdict(list)
    for fact in expected_facts:
        by_item[fact.item_id].append(fact)
    duplicate_expected_keys = _counter_groups(
        Counter(fact.match_key for fact in expected_facts),
        ["concept", "contextRef", "unitRef", "value"],
    )
    suspicious = [fact for fact in expected_facts if fact.signed_value_suspicious]
    return {
        "extracted_rows_used_for_generation": len(by_item),
        "expected_generated_fact_count": len(expected_facts),
        "facts_by_concept_source": dict(sorted(Counter(fact.concept_source for fact in expected_facts).items())),
        "facts_by_concept": dict(sorted(Counter(fact.concept for fact in expected_facts).items())),
        "duplicate_expected_fact_keys": {
            "group_count": len(duplicate_expected_keys),
            "groups": duplicate_expected_keys[:SAMPLE_LIMIT],
        },
        "suspicious_signed_values_carried_into_xbrl": {
            "count": len(suspicious),
            "samples": [fact.to_dict() for fact in suspicious[:SAMPLE_LIMIT]],
        },
    }


def summarize_context_unit_usage(
    parsed_instance: dict[str, Any],
    generated_facts: list[dict[str, Any]],
) -> dict[str, Any]:
    context_counts = Counter(fact.get("contextRef") for fact in generated_facts if fact.get("contextRef"))
    unit_counts = Counter(fact.get("unitRef") for fact in generated_facts if fact.get("unitRef"))
    context_ids = set(parsed_instance["contexts"]["ids"])
    unit_ids = set(parsed_instance["units"]["ids"])
    return {
        "contexts": {
            **parsed_instance["contexts"],
            "used_by_facts": dict(sorted(context_counts.items())),
            "unused_contexts": sorted(context_ids - set(context_counts)),
            "missing_context_refs": sorted(set(context_counts) - context_ids),
        },
        "units": {
            **parsed_instance["units"],
            "used_by_facts": dict(sorted(unit_counts.items())),
            "unused_units": sorted(unit_ids - set(unit_counts)),
            "missing_unit_refs": sorted(set(unit_counts) - unit_ids),
        },
    }


def classify_findings(
    fact_summary: dict[str, Any],
    expected_summary: dict[str, Any],
    coverage: dict[str, Any],
    context_unit_summary: dict[str, Any],
    baseline_report: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    classifications = []
    if baseline_report and baseline_report.get("final_recommended_baseline_mode") == "instance_baseline":
        classifications.append(
            {
                "classification": "structural_pass",
                "severity": "info",
                "evidence": "Feature #11F instance_baseline returned Arelle return_code=0 for job 9.",
            }
        )

    if coverage["not_represented_expected_fact_count"] > 0:
        classifications.append(
            {
                "classification": "likely_generator_defect",
                "severity": "medium",
                "evidence": f"{coverage['not_represented_expected_fact_count']} expected extracted facts were not represented in XBRL.",
            }
        )

    non_static_leftovers = [
        group
        for group in coverage["xbrl_facts_not_traceable_to_extracted_rows"]["groups"]
        if group["traceability"] != "static_document_fact"
    ]
    if non_static_leftovers:
        classifications.append(
            {
                "classification": "likely_generator_defect",
                "severity": "medium",
                "evidence": f"{len(non_static_leftovers)} generated fact groups were not traceable to extracted rows or known static document facts.",
            }
        )

    if fact_summary["monetary_facts_without_unitRef"]["count"] > 0:
        classifications.append(
            {
                "classification": "likely_generator_defect",
                "severity": "high",
                "evidence": f"{fact_summary['monetary_facts_without_unitRef']['count']} numeric facts have no unitRef.",
            }
        )

    if context_unit_summary["contexts"]["missing_context_refs"] or context_unit_summary["units"]["missing_unit_refs"]:
        classifications.append(
            {
                "classification": "likely_generator_defect",
                "severity": "high",
                "evidence": "One or more generated facts reference missing contexts or units.",
            }
        )

    if fact_summary["duplicate_concept_context_unit_facts"]["group_count"] > 0:
        classifications.append(
            {
                "classification": "likely_mapping_defect",
                "severity": "medium",
                "evidence": f"{fact_summary['duplicate_concept_context_unit_facts']['group_count']} concept/context/unit duplicate groups exist.",
            }
        )

    if expected_summary["duplicate_expected_fact_keys"]["group_count"] > 0:
        classifications.append(
            {
                "classification": "likely_extraction_duplicate",
                "severity": "medium",
                "evidence": f"{expected_summary['duplicate_expected_fact_keys']['group_count']} duplicate extracted-row fact keys would produce identical XBRL facts.",
            }
        )

    if expected_summary["suspicious_signed_values_carried_into_xbrl"]["count"] > 0:
        classifications.append(
            {
                "classification": "needs_manual_review",
                "severity": "medium",
                "evidence": f"{expected_summary['suspicious_signed_values_carried_into_xbrl']['count']} suspicious signed extracted values are represented in generated facts.",
            }
        )

    classifications.append(
        {
            "classification": "not_detectable_by_instance_baseline",
            "severity": "info",
            "evidence": "instance_baseline proves structural loadability only; it does not validate full MBRS/FS-MPERS formula/table rules or semantic mapping correctness.",
        }
    )
    return classifications


async def load_job(job_id: int) -> FilingJob:
    async with AsyncSessionLocal() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        job = (
            await session.execute(
                select(FilingJob)
                .where(FilingJob.id == job_id)
                .options(
                    selectinload(FilingJob.pages)
                    .selectinload(FinancialStatementPage.extracted_items)
                    .selectinload(ExtractedDataItem.confirmed_tag)
                )
            )
        ).scalar_one_or_none()
        if job is None:
            raise ValueError(f"Job {job_id} not found")
        session.expunge_all()
        await session.rollback()
        return job


def load_baseline_report(job_id: int) -> dict[str, Any] | None:
    path = DEFAULT_REPORTS_DIR / f"arelle_validation_baseline_report_{job_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


async def build_report(job_id: int, xbrl_path: Path | None = None) -> dict[str, Any]:
    job = await load_job(job_id)
    resolved_xbrl_path = xbrl_path or default_xbrl_path_for_job(job)
    if not resolved_xbrl_path.exists():
        raise FileNotFoundError(f"Generated XBRL file not found: {resolved_xbrl_path}")

    parsed = parse_xbrl_instance(resolved_xbrl_path)
    generated_facts = parsed["facts"]
    expected_facts = expected_facts_for_job(job)
    fact_summary = summarize_facts(generated_facts)
    expected_summary = summarize_expected_facts(expected_facts)
    coverage = compare_expected_to_generated(expected_facts, generated_facts)
    context_unit_summary = summarize_context_unit_usage(parsed, generated_facts)
    baseline_report = load_baseline_report(job_id)

    return {
        "job": {
            "id": job.id,
            "status": job.status,
            "company_name": job.company_name,
            "registration_number": job.registration_number,
            "financial_year_end": _as_date(job.financial_year_end).isoformat(),
            "page_count": len(job.pages),
        },
        "xbrl_path": str(resolved_xbrl_path),
        "schema_refs": parsed["schema_refs"],
        "audit_scope": {
            "read_only": True,
            "generated_xbrl_modified": False,
            "database_modified": False,
            "baseline_context": "Feature #11G uses instance_baseline only for structural context; this audit does not claim full MBRS validation.",
        },
        "generated_facts": fact_summary,
        "extracted_rows": expected_summary,
        "coverage": coverage,
        "context_unit_summary": context_unit_summary,
        "classifications": classify_findings(
            fact_summary=fact_summary,
            expected_summary=expected_summary,
            coverage=coverage,
            context_unit_summary=context_unit_summary,
            baseline_report=baseline_report,
        ),
    }


def write_report(report: dict[str, Any], job_id: int) -> Path:
    DEFAULT_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = DEFAULT_REPORTS_DIR / f"generated_instance_audit_report_{job_id}.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return path


def print_summary(report: dict[str, Any], report_path: Path) -> None:
    generated = report["generated_facts"]
    coverage = report["coverage"]
    print(f"Generated instance audit report: {report_path}")
    print(f"Job ID: {report['job']['id']}")
    print(f"XBRL path: {report['xbrl_path']}")
    print(f"Generated facts: {generated['total_generated_facts']}")
    print(
        "Expected extracted facts represented: "
        f"{coverage['represented_expected_fact_count']}/"
        f"{coverage['expected_generated_fact_count']}"
    )
    print(
        "Duplicate concept/context/unit groups: "
        f"{generated['duplicate_concept_context_unit_facts']['group_count']}"
    )
    print(
        "Suspicious signed values carried into XBRL: "
        f"{report['extracted_rows']['suspicious_signed_values_carried_into_xbrl']['count']}"
    )


def main() -> int:
    args = parse_args()
    report = asyncio.run(build_report(args.job_id, args.xbrl_path))
    report_path = write_report(report, args.job_id)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_summary(report, report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
