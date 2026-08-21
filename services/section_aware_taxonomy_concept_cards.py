"""Deterministic, local-only SSM MPERS concept cards for Feature #19C."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
import re
from typing import Any, Iterable, Mapping
import xml.etree.ElementTree as ET

from schemas import TaxonomyConceptCard
from services.taxonomy_concept_metadata import CURATED_ALIASES_BY_QNAME
from services.template_group_registry import (
    DEFAULT_REGISTRY_PATH,
    load_template_group_registry,
    semantic_inventory_sha256,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE_PATH = PROJECT_ROOT / "mpers_templates.json"
CONCEPT_CARD_VERSION = "19C-concept-card-v2"
XSD_NAMESPACE = "http://www.w3.org/2001/XMLSchema"
XBRLI_NAMESPACE = "http://www.xbrl.org/2003/instance"
PREFIX_SCHEMA_PATHS = {
    "ifrs-smes": PROJECT_ROOT
    / "taxonomy/SSMxT_2022v1.0/def/ext/ifrs_for_smes/ifrs_for_smes-cor_2022-03-24.xsd",
    "ssmt": PROJECT_ROOT
    / "taxonomy/SSMxT_2022v1.0/def/ic/cor-ca2016/ssmt-cor/ssmt-cor_2022-12-31.xsd",
    "ssmt-mpers": PROJECT_ROOT
    / "taxonomy/SSMxT_2022v1.0/def/ic/cor-ca2016/ssmt-mpers-cor/ssmt-mpers-cor_2022-12-31.xsd",
    "ssmt-mfrs": PROJECT_ROOT
    / "taxonomy/SSMxT_2022v1.0/def/ic/cor-ca2016/ssmt-mfrs-cor/ssmt-mfrs-cor_2022-12-31.xsd",
}


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def normalize_concept_label(value: Any) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value or ""))
    return " ".join(re.sub(r"[^a-zA-Z0-9]+", " ", text).lower().split())


def _local_name(qname: str) -> str:
    return qname.split(":", 1)[-1]


def _prefix(qname: str) -> str:
    return qname.split(":", 1)[0] if ":" in qname else ""


def _bool_attribute(value: Any) -> bool | None:
    if value is None:
        return None
    return str(value).strip().lower() in {"1", "true"}


@lru_cache(maxsize=8)
def _schema_metadata(path_text: str, prefix: str) -> dict[str, dict[str, Any]]:
    path = Path(path_text)
    if not path.is_file():
        return {}
    root = ET.parse(path).getroot()
    target_namespace = root.attrib.get("targetNamespace")
    records: dict[str, dict[str, Any]] = {}
    for element in root.findall(f"{{{XSD_NAMESPACE}}}element"):
        name = str(element.attrib.get("name") or "").strip()
        if not name:
            continue
        qname = f"{prefix}:{name}"
        records[qname] = {
            "namespace": target_namespace,
            "datatype": element.attrib.get("type"),
            "period_type": element.attrib.get(f"{{{XBRLI_NAMESPACE}}}periodType"),
            "balance": element.attrib.get(f"{{{XBRLI_NAMESPACE}}}balance"),
            "abstract": bool(_bool_attribute(element.attrib.get("abstract"))),
            "nillable": _bool_attribute(element.attrib.get("nillable")),
            "substitution_group": element.attrib.get("substitutionGroup"),
            "schema_path": _display_path(path),
        }
    return records


def _all_schema_metadata() -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for prefix, path in PREFIX_SCHEMA_PATHS.items():
        metadata.update(_schema_metadata(str(path.resolve()), prefix))
    return metadata


def _aliases(qname: str, label: str) -> list[str]:
    variants = {
        normalize_concept_label(label),
        normalize_concept_label(_local_name(qname)),
        *(normalize_concept_label(item) for item in CURATED_ALIASES_BY_QNAME.get(qname, ())),
    }
    normalized_label = normalize_concept_label(label)
    return sorted(item for item in variants if item and item != normalized_label)


def _concept_path(
    qname: str,
    parents: Mapping[str, set[str]],
    *,
    max_depth: int = 16,
) -> list[str]:
    path = [qname]
    current = qname
    seen = {qname}
    while len(path) < max_depth:
        choices = sorted(parents.get(current) or [])
        if not choices or choices[0] in seen:
            break
        current = choices[0]
        seen.add(current)
        path.append(current)
    return list(reversed(path))


def _semantic_card_payload(card: TaxonomyConceptCard) -> dict[str, Any]:
    return {
        "qname": card.qname,
        "standard_label": card.standard_label,
        "datatype": card.datatype,
        "period_type": card.period_type,
        "balance": card.balance,
        "abstract": card.abstract,
        "nillable": card.nillable,
        "substitution_group": card.substitution_group,
        "template_group_ids": card.template_group_ids,
        "role_uris": card.role_uris,
        "parent_concepts": card.parent_concepts,
        "aliases": card.aliases,
    }


def concept_inventory_hash(cards: Iterable[TaxonomyConceptCard]) -> str:
    payload = [_semantic_card_payload(card) for card in sorted(cards, key=lambda item: item.qname)]
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@lru_cache(maxsize=4)
def _build_cached(template_path_text: str, registry_path_text: str) -> tuple[tuple[TaxonomyConceptCard, ...], dict[str, Any]]:
    template_path = Path(template_path_text)
    registry_path = Path(registry_path_text)
    template_payload = _read_json(template_path)
    templates = template_payload.get("templates")
    if not isinstance(templates, dict):
        raise ValueError("mpers_templates.json has no templates object")

    registry = load_template_group_registry(registry_path, validate_sources=True)
    group_records = {
        str(record["template_group_id"]): record
        for record in registry.get("template_groups") or []
    }
    schema_metadata = _all_schema_metadata()
    concepts: dict[str, dict[str, Any]] = {}
    parents: dict[str, set[str]] = {}
    children: dict[str, set[str]] = {}

    for code in sorted(templates):
        template = templates[code]
        group = group_records.get(str(code))
        if group is None:
            raise ValueError(f"Template {code} is absent from the canonical registry")
        if str(group.get("structural_role")) == "container_only":
            continue
        for position, raw_concept in enumerate(template.get("concepts") or []):
            if not isinstance(raw_concept, dict):
                continue
            qname = str(raw_concept.get("id") or "").strip()
            if not qname:
                continue
            record = concepts.setdefault(
                qname,
                {
                    "qname": qname,
                    "labels": [],
                    "template_group_ids": set(),
                    "role_uris": set(),
                    "statement_families": set(),
                    "positive_indicators": set(),
                    "exclusion_indicators": set(),
                    "positions": [],
                },
            )
            record["labels"].append(str(raw_concept.get("label") or _local_name(qname)))
            record["template_group_ids"].add(str(code))
            record["role_uris"].add(str(group.get("role_uri") or template.get("role_uri") or ""))
            record["statement_families"].add(str(group.get("statement_family") or ""))
            classification = group.get("classification_metadata") or {}
            record["positive_indicators"].update(classification.get("positive_title_indicators") or [])
            record["exclusion_indicators"].update(classification.get("exclusion_indicators") or [])
            record["positions"].append((str(code), int(raw_concept.get("position", position))))
            parent = str(raw_concept.get("parent") or "").strip()
            if parent:
                parents.setdefault(qname, set()).add(parent)
                children.setdefault(parent, set()).add(qname)

    cards: list[TaxonomyConceptCard] = []
    label_to_qnames: dict[str, set[str]] = {}
    for qname, record in concepts.items():
        label = sorted(set(record["labels"]), key=lambda value: (len(value), value))[0]
        label_to_qnames.setdefault(normalize_concept_label(label), set()).add(qname)
        metadata = schema_metadata.get(qname, {})
        prefix = _prefix(qname)
        cards.append(
            TaxonomyConceptCard(
                concept_id=qname,
                qname=qname,
                namespace=metadata.get("namespace") or prefix or None,
                local_name=_local_name(qname),
                standard_label=label,
                datatype=metadata.get("datatype"),
                period_type=metadata.get("period_type"),
                balance=metadata.get("balance"),
                abstract=bool(metadata.get("abstract", _local_name(qname).endswith("Abstract"))),
                nillable=metadata.get("nillable"),
                substitution_group=metadata.get("substitution_group"),
                template_group_ids=sorted(record["template_group_ids"]),
                template_codes=sorted(record["template_group_ids"]),
                role_uris=sorted(item for item in record["role_uris"] if item),
                statement_family=sorted(item for item in record["statement_families"] if item),
                concept_path=_concept_path(qname, parents),
                parent_concepts=sorted(parents.get(qname) or []),
                child_concepts=sorted(children.get(qname) or []),
                aliases=_aliases(qname, label),
                positive_indicators=sorted(str(item) for item in record["positive_indicators"] if str(item)),
                exclusion_indicators=sorted(str(item) for item in record["exclusion_indicators"] if str(item)),
                source_taxonomy_version=str(registry.get("source_taxonomy_version") or "SSMxT_2022v1.0"),
                provenance={
                    "concept_card_version": CONCEPT_CARD_VERSION,
                    "membership_source": _display_path(template_path),
                    "registry_source": _display_path(registry_path),
                    "schema_source": metadata.get("schema_path"),
                    "template_positions": sorted(record["positions"]),
                    "provider_calls": 0,
                    "benchmark_answers_used": False,
                },
            )
        )

    resolved_cards = []
    for card in cards:
        collisions = sorted(
            item
            for item in label_to_qnames.get(normalize_concept_label(card.standard_label), set())
            if item != card.qname
        )
        resolved_cards.append(card.model_copy(update={"do_not_confuse": collisions}))
    resolved_cards.sort(key=lambda item: item.qname)
    inventory_hash = concept_inventory_hash(resolved_cards)
    metadata = {
        "concept_card_version": CONCEPT_CARD_VERSION,
        "concept_inventory_hash": inventory_hash,
        "concept_count": len(resolved_cards),
        "registry_version": str(registry.get("semantic_inventory_version") or "mpers-2022-v1"),
        "registry_hash": semantic_inventory_sha256(registry),
        "taxonomy_version": str(registry.get("source_taxonomy_version") or "SSMxT_2022v1.0"),
        "template_membership_source": _display_path(template_path),
        "provider_calls": 0,
        "benchmark_answers_used": False,
    }
    return tuple(resolved_cards), metadata


def build_taxonomy_concept_inventory(
    template_path: str | Path = DEFAULT_TEMPLATE_PATH,
    registry_path: str | Path = DEFAULT_REGISTRY_PATH,
) -> tuple[list[TaxonomyConceptCard], dict[str, Any]]:
    cards, metadata = _build_cached(str(Path(template_path).resolve()), str(Path(registry_path).resolve()))
    return list(cards), dict(metadata)


def cards_for_template_groups(
    template_group_ids: Iterable[str],
    *,
    cards: Iterable[TaxonomyConceptCard] | None = None,
) -> list[TaxonomyConceptCard]:
    requested = {str(item) for item in template_group_ids if str(item)}
    if not requested:
        return []
    inventory = list(cards) if cards is not None else build_taxonomy_concept_inventory()[0]
    available_groups = {group for card in inventory for group in card.template_group_ids}
    unknown = requested - available_groups
    if unknown:
        raise ValueError(f"Unknown or non-mapping template groups: {sorted(unknown)}")
    return [
        card
        for card in inventory
        if requested.intersection(card.template_group_ids)
    ]
