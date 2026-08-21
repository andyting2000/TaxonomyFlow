"""Safe, read-only parser for benchmark reference XML/XBRL files."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from lxml import etree

from services.reference_xbrl_schema import (
    ReferenceCaseReport,
    ReferenceFact,
    clean_text,
    is_text_block_candidate,
    looks_numeric,
    normalize_numeric_value,
)


XBRLI_NS = "http://www.xbrl.org/2003/instance"
LINK_NS = "http://www.xbrl.org/2003/linkbase"
XBRLDI_NS = "http://xbrl.org/2006/xbrldi"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
INFRA_NAMESPACES = {
    XBRLI_NS,
    LINK_NS,
    "http://www.w3.org/1999/xlink",
    "http://www.w3.org/2001/XMLSchema-instance",
}
FORBIDDEN_XML_DECL_RE = re.compile(rb"<!\s*(DOCTYPE|ENTITY)\b", re.IGNORECASE)


class ReferenceXBRLParseError(ValueError):
    """Raised when a reference file violates safe XML parsing constraints."""


def _safe_xml_parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=False,
        recover=False,
        remove_comments=False,
    )


def _read_xml_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    if FORBIDDEN_XML_DECL_RE.search(data[:8192]):
        raise ReferenceXBRLParseError("DOCTYPE and ENTITY declarations are not allowed in reference XML/XBRL")
    return data


def _qname(element: etree._Element) -> etree.QName:
    return etree.QName(element)


def _prefixed_name(element: etree._Element) -> str:
    qname = _qname(element)
    return f"{element.prefix}:{qname.localname}" if element.prefix else qname.localname


def _find_text(element: etree._Element, namespace: str, local_name: str) -> str | None:
    child = element.find(f".//{{{namespace}}}{local_name}")
    return clean_text(child.text) if child is not None else None


def _context_map(root: etree._Element) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    for context in root.findall(f".//{{{XBRLI_NS}}}context"):
        context_id = context.get("id")
        if not context_id:
            continue
        dimensions: list[dict[str, Any]] = []
        for member in context.findall(f".//{{{XBRLDI_NS}}}explicitMember"):
            dimensions.append(
                {
                    "type": "explicit",
                    "dimension": member.get("dimension"),
                    "member": clean_text(member.text),
                }
            )
        for member in context.findall(f".//{{{XBRLDI_NS}}}typedMember"):
            typed_child = next((child for child in member if isinstance(child.tag, str)), None)
            dimensions.append(
                {
                    "type": "typed",
                    "dimension": member.get("dimension"),
                    "member": _prefixed_name(typed_child) if typed_child is not None else None,
                    "value": clean_text(" ".join(member.itertext())),
                }
            )
        contexts[context_id] = {
            "id": context_id,
            "entity_identifier": _find_text(context, XBRLI_NS, "identifier"),
            "period_start": _find_text(context, XBRLI_NS, "startDate"),
            "period_end": _find_text(context, XBRLI_NS, "endDate"),
            "instant": _find_text(context, XBRLI_NS, "instant"),
            "dimensions": dimensions,
        }
    return contexts


def _unit_map(root: etree._Element) -> dict[str, dict[str, Any]]:
    units: dict[str, dict[str, Any]] = {}
    for unit in root.findall(f".//{{{XBRLI_NS}}}unit"):
        unit_id = unit.get("id")
        if not unit_id:
            continue
        measures = [clean_text(measure.text) for measure in unit.findall(f".//{{{XBRLI_NS}}}measure")]
        units[unit_id] = {
            "id": unit_id,
            "measures": [measure for measure in measures if measure],
        }
    return units


def _is_fact_element(element: etree._Element) -> bool:
    if not isinstance(element.tag, str):
        return False
    qname = _qname(element)
    if qname.namespace in INFRA_NAMESPACES:
        return False
    if element.get("contextRef") or element.get("unitRef"):
        return True
    return False


def _fact_value(element: etree._Element) -> str | None:
    if len(element):
        return clean_text(" ".join(element.itertext()))
    return clean_text(element.text)


def _is_nil(element: etree._Element) -> bool:
    value = element.get(f"{{{XSI_NS}}}nil") or element.get("nil")
    return str(value or "").strip().lower() in {"true", "1"}


def parse_reference_xbrl(case_id: str, reference_path: str | Path, reference_type: str | None = None) -> dict[str, Any]:
    """Parse one local reference XML/XBRL file and return a report dict."""
    path = Path(reference_path)
    warnings: list[str] = []
    if not path.exists():
        raise FileNotFoundError(f"Reference XML/XBRL not found: {path}")

    data = _read_xml_bytes(path)
    root = etree.fromstring(data, parser=_safe_xml_parser())
    contexts = _context_map(root)
    units = _unit_map(root)
    facts: list[ReferenceFact] = []

    for index, element in enumerate(root.iterchildren(), start=1):
        if not _is_fact_element(element):
            continue
        try:
            qname = _qname(element)
            value = _fact_value(element)
            context_ref = element.get("contextRef")
            unit_ref = element.get("unitRef")
            context = contexts.get(context_ref or "", {})
            nil_value = _is_nil(element)
            is_numeric = bool(unit_ref) or (not nil_value and looks_numeric(value))
            is_text_block = not nil_value and is_text_block_candidate(qname.localname, value)
            fact_warnings: list[str] = []
            if context_ref and context_ref not in contexts:
                fact_warnings.append("missing_context_ref")
            if unit_ref and unit_ref not in units:
                fact_warnings.append("missing_unit_ref")
            if not context_ref:
                fact_warnings.append("missing_context_ref")
            facts.append(
                ReferenceFact(
                    case_id=case_id,
                    reference_path=str(path),
                    fact_id=element.get("id") or f"{case_id}-fact-{index}",
                    concept_name=_prefixed_name(element),
                    namespace_uri=qname.namespace,
                    local_name=qname.localname,
                    qname=_prefixed_name(element),
                    context_ref=context_ref,
                    unit_ref=unit_ref,
                    decimals=element.get("decimals"),
                    precision=element.get("precision"),
                    value=value,
                    normalized_value=normalize_numeric_value(value) if is_numeric else None,
                    is_numeric=is_numeric,
                    is_text_block=is_text_block,
                    is_nil=nil_value,
                    period_start=context.get("period_start"),
                    period_end=context.get("period_end"),
                    instant=context.get("instant"),
                    entity_identifier=context.get("entity_identifier"),
                    dimensions=list(context.get("dimensions") or []),
                    source_line_or_position=element.sourceline,
                    warnings=fact_warnings,
                )
            )
        except Exception as exc:
            warnings.append(f"Skipped odd fact near line {getattr(element, 'sourceline', None)}: {exc}")

    fact_dicts = [fact.to_dict() for fact in facts]
    facts_by_namespace = Counter(fact.namespace_uri or "unknown" for fact in facts)
    facts_by_context = Counter(fact.context_ref or "missing" for fact in facts)
    text_fact_count = sum(1 for fact in facts if not fact.is_numeric and not fact.is_nil)
    report = ReferenceCaseReport(
        case_id=case_id,
        reference_path=str(path),
        reference_type=reference_type or path.suffix.lower().lstrip("."),
        total_facts=len(facts),
        numeric_fact_count=sum(1 for fact in facts if fact.is_numeric and not fact.is_nil),
        text_fact_count=text_fact_count,
        text_block_count=sum(1 for fact in facts if fact.is_text_block and not fact.is_nil),
        nil_fact_count=sum(1 for fact in facts if fact.is_nil),
        contexts_count=len(contexts),
        units_count=len(units),
        concepts_count=len({fact.qname for fact in facts}),
        facts_by_namespace=dict(sorted(facts_by_namespace.items())),
        facts_by_context=dict(sorted(facts_by_context.items())),
        parse_warnings=warnings,
        facts=fact_dicts,
        sample_facts=fact_dicts[:20],
    )
    return report.to_dict()
