"""Canonical MPERS template-group registry and deterministic reconciliation.

Authority order is deliberate and must remain:

1. bundled official taxonomy role URI and role definition;
2. bundled presentation-role structure;
3. canonical repository metadata derived from that taxonomy;
4. user-friendly display labels;
5. compatibility aliases.

Display labels and aliases must never override official taxonomy semantics.
The extracted ``mpers_templates.json`` remains the source for the exact runtime
membership and concept payload; this registry is the versioned semantic layer.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import xml.etree.ElementTree as ElementTree
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY_PATH = (
    PROJECT_ROOT / "taxonomy" / "template_group_registry_mpers_2022_v1.json"
)
DEFAULT_RUNTIME_INVENTORY_PATH = PROJECT_ROOT / "mpers_templates.json"
DEFAULT_ROLE_XSD_PATH = (
    PROJECT_ROOT
    / "taxonomy"
    / "SSMxT_2022v1.0"
    / "rep"
    / "ssm"
    / "ca-2016"
    / "fs"
    / "mpers"
    / "rol_ssmt-fs-mpers_2022-12-31.xsd"
)

EXPECTED_TEMPLATE_COUNT = 24
EXPECTED_TAXONOMY_VERSION = "SSMxT_2022v1.0"
EXPECTED_REGISTRY_ID = "template_group_registry_mpers_2022_v1"

TEMPLATE_KINDS = {
    "primary_statement",
    "note_list",
    "note_disclosure",
    "report",
    "declaration",
    "other",
}
STRUCTURAL_ROLES = {
    "leaf_template",
    "navigation_role",
    "container_candidate",
}
DISCREPANCY_CLASSIFICATIONS = {
    "exact_match",
    "wording_difference_only",
    "user_friendly_alias",
    "materially_incorrect_name",
    "ambiguous_semantics",
    "missing_metadata",
    "structural_container_conflict",
}

REQUIRED_RECORD_FIELDS = {
    "template_group_id",
    "code",
    "role_uri",
    "official_role_definition",
    "role_id",
    "canonical_name",
    "user_display_name",
    "normalized_name",
    "template_kind",
    "structural_role",
    "statement_family",
    "aliases",
    "classification_enabled",
    "mapping_enabled",
    "allows_multiple_source_sections",
    "source_taxonomy_version",
    "current_runtime_name",
    "current_runtime_description",
    "raw_extracted_description",
    "existing_ui_label",
    "existing_navigation_label",
    "discrepancy_classification",
    "presentation_linkbase_references",
    "calculation_linkbase_references",
    "concept_membership",
    "classification_metadata",
    "provenance",
    "compatibility",
}

LINK_NAMESPACE = "http://www.xbrl.org/2003/linkbase"
XLINK_NAMESPACE = "http://www.w3.org/1999/xlink"


class TemplateGroupRegistryError(ValueError):
    """Raised when canonical registry validation fails closed."""


def _read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise TemplateGroupRegistryError(f"Expected JSON object at {path}")
    return data


def _normalize_label(value: Any) -> str:
    text = str(value or "").strip().lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def ordered_concept_ids_sha256(concepts: Iterable[Mapping[str, Any]]) -> str:
    """Hash ordered concept IDs without copying the taxonomy concept inventory."""
    payload = "\n".join(str(concept.get("id") or "") for concept in concepts)
    return _sha256_bytes(payload.encode("utf-8"))


def semantic_inventory_sha256(registry: Mapping[str, Any]) -> str:
    """Hash only canonical semantic fields, excluding audit prose and file layout."""
    semantic_records = []
    for record in sorted(
        registry.get("template_groups", []),
        key=lambda item: str(item.get("code") or ""),
    ):
        semantic_records.append(
            {
                "template_group_id": record.get("template_group_id"),
                "code": record.get("code"),
                "role_uri": record.get("role_uri"),
                "official_role_definition": record.get("official_role_definition"),
                "role_id": record.get("role_id"),
                "canonical_name": record.get("canonical_name"),
                "user_display_name": record.get("user_display_name"),
                "normalized_name": record.get("normalized_name"),
                "template_kind": record.get("template_kind"),
                "structural_role": record.get("structural_role"),
                "statement_family": record.get("statement_family"),
                "aliases": record.get("aliases"),
                "classification_enabled": record.get("classification_enabled"),
                "mapping_enabled": record.get("mapping_enabled"),
                "allows_multiple_source_sections": record.get(
                    "allows_multiple_source_sections"
                ),
                "source_taxonomy_version": record.get("source_taxonomy_version"),
                "classification_metadata": record.get("classification_metadata"),
                "compatibility": record.get("compatibility"),
            }
        )
    payload = {
        "registry_id": registry.get("registry_id"),
        "semantic_inventory_version": registry.get("semantic_inventory_version"),
        "source_taxonomy_version": registry.get("source_taxonomy_version"),
        "authority_order": registry.get("authority_order"),
        "durable_identity_fields": registry.get("durable_identity_fields"),
        "structural_navigation_nodes": registry.get("structural_navigation_nodes"),
        "template_groups": semantic_records,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def registry_file_sha256(path: Path = DEFAULT_REGISTRY_PATH) -> str:
    return _sha256_bytes(path.read_bytes())


def validate_registry_structure(registry: Mapping[str, Any]) -> List[str]:
    """Return deterministic structural errors without consulting other files."""
    errors: List[str] = []
    if registry.get("registry_id") != EXPECTED_REGISTRY_ID:
        errors.append(
            f"registry_id must be {EXPECTED_REGISTRY_ID!r}, "
            f"got {registry.get('registry_id')!r}"
        )
    if registry.get("source_taxonomy_version") != EXPECTED_TAXONOMY_VERSION:
        errors.append(
            f"source_taxonomy_version must be {EXPECTED_TAXONOMY_VERSION!r}"
        )
    if registry.get("expected_template_count") != EXPECTED_TEMPLATE_COUNT:
        errors.append(
            f"expected_template_count must be {EXPECTED_TEMPLATE_COUNT}"
        )

    authority_ranks = [
        item.get("rank") for item in registry.get("authority_order", [])
        if isinstance(item, dict)
    ]
    if authority_ranks != [1, 2, 3, 4, 5]:
        errors.append("authority_order must contain ranks 1 through 5 in order")
    if registry.get("durable_identity_fields") != ["code", "role_uri"]:
        errors.append("durable_identity_fields must be ['code', 'role_uri']")

    records = registry.get("template_groups")
    if not isinstance(records, list):
        return errors + ["template_groups must be a list"]
    if len(records) != EXPECTED_TEMPLATE_COUNT:
        errors.append(
            f"template_groups must contain exactly {EXPECTED_TEMPLATE_COUNT} records; "
            f"got {len(records)}"
        )

    code_counts = Counter(str(record.get("code") or "") for record in records)
    role_counts = Counter(str(record.get("role_uri") or "") for record in records)
    normalized_counts = Counter(
        str(record.get("normalized_name") or "") for record in records
    )
    for code, count in sorted(code_counts.items()):
        if not code or count != 1:
            errors.append(f"template code {code!r} occurs {count} times")
    for role_uri, count in sorted(role_counts.items()):
        if not role_uri or count != 1:
            errors.append(f"role URI {role_uri!r} occurs {count} times")
    for normalized_name, count in sorted(normalized_counts.items()):
        if not normalized_name or count != 1:
            errors.append(
                f"normalized name {normalized_name!r} occurs {count} times"
            )

    label_owners: Dict[str, str] = {}
    for index, record in enumerate(records):
        code = str(record.get("code") or f"index:{index}")
        missing = sorted(REQUIRED_RECORD_FIELDS - set(record))
        if missing:
            errors.append(f"{code}: missing fields {', '.join(missing)}")
        if record.get("template_group_id") != record.get("code"):
            errors.append(f"{code}: template_group_id must equal code")
        if not re.fullmatch(r"\d{6}", str(record.get("code") or "")):
            errors.append(f"{code}: code must be exactly six digits")
        if record.get("template_kind") not in TEMPLATE_KINDS:
            errors.append(f"{code}: invalid template_kind")
        if record.get("structural_role") not in STRUCTURAL_ROLES:
            errors.append(f"{code}: invalid structural_role")
        if (
            record.get("discrepancy_classification")
            not in DISCREPANCY_CLASSIFICATIONS
        ):
            errors.append(f"{code}: invalid discrepancy_classification")
        if record.get("source_taxonomy_version") != EXPECTED_TAXONOMY_VERSION:
            errors.append(f"{code}: source taxonomy version mismatch")
        if not isinstance(record.get("aliases"), list):
            errors.append(f"{code}: aliases must be a list")
        if not isinstance(record.get("classification_enabled"), bool):
            errors.append(f"{code}: classification_enabled must be boolean")
        if not isinstance(record.get("mapping_enabled"), bool):
            errors.append(f"{code}: mapping_enabled must be boolean")
        if not isinstance(record.get("allows_multiple_source_sections"), bool):
            errors.append(
                f"{code}: allows_multiple_source_sections must be boolean"
            )

        membership = record.get("concept_membership") or {}
        if not isinstance(membership.get("concept_count"), int):
            errors.append(f"{code}: concept_count must be an integer")
        if not re.fullmatch(
            r"[0-9a-f]{64}",
            str(membership.get("ordered_concept_ids_sha256") or ""),
        ):
            errors.append(f"{code}: ordered concept hash is invalid")

        classification = record.get("classification_metadata") or {}
        required_classification_fields = {
            "expected_source_section_types",
            "positive_title_indicators",
            "exclusion_indicators",
            "narrative_container_behavior",
            "primary_deterministic_classification_allowed",
            "note_subsection_classification_allowed",
            "multiple_assignments_allowed",
        }
        missing_classification = required_classification_fields - set(classification)
        if missing_classification:
            errors.append(
                f"{code}: missing classification metadata "
                f"{', '.join(sorted(missing_classification))}"
            )

        compatibility = record.get("compatibility") or {}
        if compatibility.get("durable_identifiers") != ["code", "role_uri"]:
            errors.append(f"{code}: compatibility durable identifiers mismatch")
        if not isinstance(compatibility.get("legacy_name_aliases"), list):
            errors.append(f"{code}: legacy_name_aliases must be a list")

        labels = [
            record.get("canonical_name"),
            record.get("user_display_name"),
            *(record.get("aliases") or []),
        ]
        for label in labels:
            normalized = _normalize_label(label)
            if not normalized:
                errors.append(f"{code}: blank canonical/display/alias label")
                continue
            owner = label_owners.get(normalized)
            if owner and owner != code:
                errors.append(
                    f"{code}: label {label!r} conflicts with template {owner}"
                )
            label_owners[normalized] = code

    notes_nodes = [
        node
        for node in registry.get("structural_navigation_nodes", [])
        if node.get("id") == "notes_container"
    ]
    if len(notes_nodes) != 1:
        errors.append("exactly one notes_container structural node is required")
    elif (
        notes_nodes[0].get("taxonomy_template_group") is not False
        or notes_nodes[0].get("template_code") is not None
        or notes_nodes[0].get("role_uri") is not None
        or notes_nodes[0].get("classification_outcome") != "container_only"
    ):
        errors.append("notes_container must be code-less and container_only")

    records_by_code = {
        str(record.get("code") or ""): record
        for record in records
    }
    expected_meanings = {
        "730000": "notes - list of notes",
        "740000": "notes - issued capital",
        "750000": "notes - related party transactions",
    }
    for code, expected_name in expected_meanings.items():
        record = records_by_code.get(code) or {}
        if _normalize_label(record.get("canonical_name")) != _normalize_label(
            expected_name
        ):
            errors.append(f"{code}: canonical meaning must be {expected_name!r}")
    if (records_by_code.get("730000") or {}).get("structural_role") != "leaf_template":
        errors.append("730000 must remain a taxonomy leaf_template, not the Notes parent")

    return errors


def load_official_role_types(
    role_xsd_path: Path = DEFAULT_ROLE_XSD_PATH,
) -> Dict[str, Dict[str, Any]]:
    """Load bundled role types keyed by role URI.

    The bundled file is trusted repository input. ``ElementTree`` does not
    resolve external entities here, and no network-aware parser is used.
    """
    root = ElementTree.parse(role_xsd_path).getroot()
    roles: Dict[str, Dict[str, Any]] = {}
    role_tag = f"{{{LINK_NAMESPACE}}}roleType"
    definition_tag = f"{{{LINK_NAMESPACE}}}definition"
    used_on_tag = f"{{{LINK_NAMESPACE}}}usedOn"
    for element in root.iter(role_tag):
        role_uri = str(element.attrib.get("roleURI") or "")
        if not role_uri:
            continue
        definition = element.find(definition_tag)
        roles[role_uri] = {
            "role_id": element.attrib.get("id"),
            "definition": (definition.text or "").strip()
            if definition is not None
            else "",
            "used_on": [
                (used_on.text or "").strip()
                for used_on in element.findall(used_on_tag)
            ],
        }
    return roles


def _linkbase_role(path: Path, link_type: str) -> Optional[str]:
    root = ElementTree.parse(path).getroot()
    tag = f"{{{LINK_NAMESPACE}}}{link_type}"
    role_attribute = f"{{{XLINK_NAMESPACE}}}role"
    link = next(root.iter(tag), None)
    if link is None:
        return None
    return link.attrib.get(role_attribute)


def validate_registry_against_sources(
    registry: Mapping[str, Any],
    *,
    runtime_inventory: Optional[Mapping[str, Any]] = None,
    project_root: Path = PROJECT_ROOT,
    role_xsd_path: Path = DEFAULT_ROLE_XSD_PATH,
) -> Dict[str, Any]:
    """Reconcile registry, bundled roles/linkbases, and runtime inventory."""
    errors = validate_registry_structure(registry)
    checks: List[Dict[str, Any]] = []
    runtime = (
        dict(runtime_inventory)
        if runtime_inventory is not None
        else _read_json(DEFAULT_RUNTIME_INVENTORY_PATH)
    )
    runtime_templates = runtime.get("templates") or {}
    records = registry.get("template_groups") or []
    records_by_code = {str(record.get("code") or ""): record for record in records}

    runtime_codes = set(runtime_templates)
    registry_codes = set(records_by_code)
    code_sets_match = runtime_codes == registry_codes
    checks.append(
        {
            "check": "code_set_equality",
            "passed": code_sets_match,
            "runtime_count": len(runtime_codes),
            "registry_count": len(registry_codes),
            "missing_from_registry": sorted(runtime_codes - registry_codes),
            "extra_in_registry": sorted(registry_codes - runtime_codes),
        }
    )
    if not code_sets_match:
        errors.append("runtime and canonical code sets differ")

    official_roles = load_official_role_types(role_xsd_path)
    for code in sorted(registry_codes):
        record = records_by_code[code]
        template = runtime_templates.get(code) or {}

        role_uri_matches = template.get("role_uri") == record.get("role_uri")
        checks.append(
            {
                "check": "runtime_role_uri",
                "code": code,
                "passed": role_uri_matches,
            }
        )
        if not role_uri_matches:
            errors.append(f"{code}: runtime role URI does not match registry")

        role = official_roles.get(str(record.get("role_uri") or ""))
        official_matches = bool(
            role
            and role.get("role_id") == record.get("role_id")
            and role.get("definition") == record.get("official_role_definition")
        )
        checks.append(
            {
                "check": "official_role_definition",
                "code": code,
                "passed": official_matches,
            }
        )
        if not official_matches:
            errors.append(f"{code}: bundled role ID/definition does not match registry")

        concepts = template.get("concepts") or []
        membership = record.get("concept_membership") or {}
        concept_count_matches = (
            len(concepts) == membership.get("concept_count")
            and template.get("total_concepts") == membership.get("concept_count")
        )
        concept_hash_matches = (
            ordered_concept_ids_sha256(concepts)
            == membership.get("ordered_concept_ids_sha256")
        )
        checks.append(
            {
                "check": "concept_membership",
                "code": code,
                "passed": concept_count_matches and concept_hash_matches,
                "concept_count": len(concepts),
            }
        )
        if not concept_count_matches:
            errors.append(f"{code}: concept count does not match registry")
        if not concept_hash_matches:
            errors.append(f"{code}: ordered concept membership hash mismatch")

        for key, link_type in (
            ("presentation_linkbase_references", "presentationLink"),
            ("calculation_linkbase_references", "calculationLink"),
        ):
            for reference in record.get(key) or []:
                path = project_root / str(reference.get("path") or "")
                if not path.is_file():
                    errors.append(f"{code}: missing linkbase {path}")
                    passed = False
                else:
                    actual_role = _linkbase_role(path, link_type)
                    passed = actual_role == reference.get("role_uri")
                    if not passed:
                        errors.append(
                            f"{code}: {path.name} role URI does not match registry"
                        )
                checks.append(
                    {
                        "check": key,
                        "code": code,
                        "path": str(reference.get("path") or ""),
                        "passed": passed,
                    }
                )

    metadata = runtime.get("_metadata") or {}
    extracted_from = str(metadata.get("extracted_from") or "")
    version_matches = (
        registry.get("source_taxonomy_version") == EXPECTED_TAXONOMY_VERSION
        and extracted_from.startswith("SSMxT_2022v1")
    )
    checks.append(
        {
            "check": "taxonomy_version_consistency",
            "passed": version_matches,
            "registry_version": registry.get("source_taxonomy_version"),
            "runtime_extracted_from": extracted_from,
        }
    )
    if not version_matches:
        errors.append("taxonomy version does not match runtime extraction metadata")

    unique_errors = list(dict.fromkeys(errors))
    return {
        "passed": not unique_errors,
        "errors": unique_errors,
        "checks": checks,
        "registry_id": registry.get("registry_id"),
        "semantic_inventory_version": registry.get("semantic_inventory_version"),
        "source_taxonomy_version": registry.get("source_taxonomy_version"),
        "template_count": len(records),
        "semantic_inventory_sha256": semantic_inventory_sha256(registry),
    }


@lru_cache(maxsize=4)
def _load_cached(path_text: str, validate_sources: bool) -> Dict[str, Any]:
    path = Path(path_text)
    registry = _read_json(path)
    structural_errors = validate_registry_structure(registry)
    if structural_errors:
        raise TemplateGroupRegistryError("; ".join(structural_errors))
    if validate_sources:
        result = validate_registry_against_sources(registry)
        if not result["passed"]:
            raise TemplateGroupRegistryError("; ".join(result["errors"]))
    registry["_registry_metadata"] = {
        "registry_path": str(path),
        "registry_file_sha256": registry_file_sha256(path),
        "semantic_inventory_sha256": semantic_inventory_sha256(registry),
    }
    return registry


def load_template_group_registry(
    path: Path = DEFAULT_REGISTRY_PATH,
    *,
    validate_sources: bool = True,
) -> Dict[str, Any]:
    """Return an isolated copy of the validated canonical registry."""
    return copy.deepcopy(_load_cached(str(path.resolve()), validate_sources))


def template_group_records(
    *,
    validate_sources: bool = True,
) -> List[Dict[str, Any]]:
    registry = load_template_group_registry(validate_sources=validate_sources)
    return list(registry["template_groups"])


def template_group_by_code(
    code: str,
    *,
    validate_sources: bool = True,
) -> Optional[Dict[str, Any]]:
    code_text = str(code or "")
    return next(
        (
            record
            for record in template_group_records(
                validate_sources=validate_sources
            )
            if record["code"] == code_text
        ),
        None,
    )


def template_group_display_name_map() -> Dict[str, str]:
    return {
        record["code"]: record["user_display_name"]
        for record in template_group_records()
    }


def template_group_statement_family_map() -> Dict[str, str]:
    return {
        record["code"]: record["statement_family"]
        for record in template_group_records()
    }


def structural_navigation_nodes() -> List[Dict[str, Any]]:
    registry = load_template_group_registry()
    return list(registry["structural_navigation_nodes"])


def resolve_template_group_label(label: str) -> Optional[str]:
    """Resolve canonical/display/legacy labels for grouping, never for mutation."""
    normalized = _normalize_label(label)
    if not normalized:
        return None
    matches = []
    for record in template_group_records():
        values = [
            record["code"],
            record["canonical_name"],
            record["user_display_name"],
            record["official_role_definition"],
            *record.get("aliases", []),
        ]
        if normalized in {_normalize_label(value) for value in values}:
            matches.append(record["code"])
    if len(matches) > 1:
        raise TemplateGroupRegistryError(
            f"Ambiguous template-group label {label!r}: {matches}"
        )
    return matches[0] if matches else None

