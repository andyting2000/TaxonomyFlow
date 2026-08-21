# services/xbrl_template_service.py
"""
XBRL Template Service - Manages MPERS XBRL templates extracted from SSMxT taxonomy

Provides access to template structures, concepts, and required field information
based on official MBRS/MPERS taxonomy linkbases.

This replaces the old xml_template_service.py with proper XBRL-compliant templates.
"""

import json
import re
import copy
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from services.template_group_registry import (
    DEFAULT_REGISTRY_PATH,
    DEFAULT_RUNTIME_INVENTORY_PATH,
    TemplateGroupRegistryError,
    load_template_group_registry,
    resolve_template_group_label,
    validate_registry_against_sources,
)

logger = logging.getLogger(__name__)

BIOLOGICAL_ASSET_CONCEPT_LOCAL_NAMES = {
    "CurrentBiologicalAssets",
    "NoncurrentBiologicalAssets",
}

BIOLOGICAL_ASSET_EVIDENCE_TERMS = (
    "biological asset",
    "biological assets",
    "livestock",
    "cattle",
    "crop",
    "crops",
    "agricultural produce",
    "bearer plant",
    "plantation",
    "agriculture",
    "agricultural",
    "aquaculture",
)

BIOLOGICAL_ASSET_NEGATIVE_EVIDENCE_TERMS = (
    "non biological",
    "non-biological",
)

RECEIVABLES_CONCEPT_LOCAL_NAMES = {
    "TradeAndOtherCurrentReceivables",
}

RECEIVABLES_EVIDENCE_TERMS = (
    "trade receivables",
    "trade and other receivables",
    "trade and other current receivables",
    "other receivables",
    "other debtor",
    "other debtors",
    "accounts receivable",
    "account receivable",
    "receivables",
    "receivable",
    "amount due from",
    "amounts due from",
    "due from",
    "debtor",
    "debtors",
)

RECEIVABLES_DETAIL_LABEL_TERMS = (
    "sdn bhd",
    "sdn. bhd",
    "berhad",
    " bhd",
    "bhd.",
    "ltd",
    "ltd.",
    "limited",
    "pte ltd",
    "corporation",
    "corp",
)


def _concept_local_name(concept_id: Optional[str]) -> str:
    return str(concept_id or "").strip().split(":")[-1]


def _normalized_label(label: Optional[str]) -> str:
    normalized = re.sub(r"[^a-z0-9&().'\- ]+", " ", str(label or "").lower())
    return re.sub(r"\s+", " ", normalized).strip()


def is_biological_asset_concept(concept_id: Optional[str]) -> bool:
    """Return True for the guarded FS-MPERS biological-asset concepts."""
    return _concept_local_name(concept_id) in BIOLOGICAL_ASSET_CONCEPT_LOCAL_NAMES


def label_supports_biological_asset_mapping(label: Optional[str]) -> bool:
    """Check whether source text gives direct biological/agricultural evidence."""
    normalized = re.sub(r"\s+", " ", str(label or "").lower()).strip()
    if not normalized:
        return False

    if any(term in normalized for term in BIOLOGICAL_ASSET_NEGATIVE_EVIDENCE_TERMS):
        return False

    return any(term in normalized for term in BIOLOGICAL_ASSET_EVIDENCE_TERMS)


def biological_asset_guardrail_allows(
    concept_id: Optional[str],
    source_label: Optional[str],
) -> bool:
    """Allow non-biological concepts; require direct evidence for biological assets."""
    if not is_biological_asset_concept(concept_id):
        return True
    return label_supports_biological_asset_mapping(source_label)


def is_trade_and_other_current_receivables_concept(concept_id: Optional[str]) -> bool:
    """Return True for the guarded receivables summary concept."""
    return _concept_local_name(concept_id) in RECEIVABLES_CONCEPT_LOCAL_NAMES


def label_supports_receivables_mapping(label: Optional[str]) -> bool:
    """Check whether source text explicitly supports receivables mapping."""
    normalized = _normalized_label(label)
    if not normalized:
        return False
    return any(term in normalized for term in RECEIVABLES_EVIDENCE_TERMS)


def label_looks_like_receivables_detail_row(label: Optional[str]) -> bool:
    """Return True for company/customer-like detail labels needing manual policy."""
    normalized = f" {_normalized_label(label)} "
    if not normalized.strip():
        return False
    return any(term in normalized for term in RECEIVABLES_DETAIL_LABEL_TERMS)


def receivables_guardrail_allows(
    concept_id: Optional[str],
    source_label: Optional[str],
) -> bool:
    """Require explicit receivables evidence for automatic receivables mapping."""
    if not is_trade_and_other_current_receivables_concept(concept_id):
        return True
    return label_supports_receivables_mapping(source_label)


def automatic_mapping_guardrail_allows(
    concept_id: Optional[str],
    source_label: Optional[str],
) -> bool:
    """Apply narrow concept-specific automatic mapping guardrails."""
    return (
        biological_asset_guardrail_allows(concept_id, source_label)
        and receivables_guardrail_allows(concept_id, source_label)
    )


def automatic_mapping_guardrail_reason(
    concept_id: Optional[str],
    source_label: Optional[str],
) -> Optional[str]:
    """Return a stable reason code when an automatic mapping is blocked."""
    if not biological_asset_guardrail_allows(concept_id, source_label):
        return "biological_asset_guardrail"
    if not receivables_guardrail_allows(concept_id, source_label):
        return "receivables_detail_guardrail"
    return None


class XBRLTemplateService:
    """
    Service to manage XBRL MPERS template structure from extracted taxonomy
    """

    def __init__(
        self,
        template_file: str = "mpers_templates.json",
        registry_file: Optional[str] = None,
        validate_registry: Optional[bool] = None,
    ):
        self.template_file = template_file
        template_path = Path(template_file).resolve()
        self.registry_file = (
            Path(registry_file).resolve()
            if registry_file
            else DEFAULT_REGISTRY_PATH
        )
        self.uses_canonical_registry = (
            validate_registry
            if validate_registry is not None
            else template_path == DEFAULT_RUNTIME_INVENTORY_PATH.resolve()
        )
        self.templates: Dict[str, Dict] = {}
        self.all_concepts: Dict[str, Dict] = {}  # concept_id -> concept_info
        # concept_id -> [template_codes]
        self.templates_by_concept: Dict[str, List[str]] = {}
        self.required_concepts: set = set()
        self.namespaces: Dict[str, str] = {}
        self.template_group_registry: Dict[str, Dict] = {}
        self.registry_metadata: Dict[str, str] = {}
        self.structural_navigation_nodes: List[Dict] = []

        self.load_templates()

    def load_templates(self) -> bool:
        """Load XBRL templates from JSON file"""
        template_path = Path(self.template_file)

        if not template_path.exists():
            logger.error(f"XBRL template file not found: {self.template_file}")
            logger.info(
                f"Run: python scripts/extract_xbrl_templates.py SSMxT_2022v1.zip")
            return False

        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Load metadata
            metadata = data.get('_metadata', {})
            self.namespaces = metadata.get('namespaces', {})

            # Load templates
            self.templates = data.get('templates', {})
            if self.uses_canonical_registry:
                registry = load_template_group_registry(
                    self.registry_file,
                    validate_sources=self.registry_file == DEFAULT_REGISTRY_PATH,
                )
                validation = validate_registry_against_sources(
                    registry,
                    runtime_inventory=data,
                )
                if not validation["passed"]:
                    raise TemplateGroupRegistryError(
                        "; ".join(validation["errors"])
                    )
                self._apply_canonical_registry(registry)

            # Build helper indexes
            self._build_indexes()

            logger.info(
                f"✅ Loaded {len(self.templates)} XBRL templates with "
                f"{len(self.all_concepts)} unique concepts "
                f"({len(self.required_concepts)} required)"
            )

            # Log template summary
            for code in sorted(self.templates.keys()):
                template = self.templates[code]
                logger.info(
                    f"  • {code}: {template['description'][:50]} - "
                    f"{template['total_concepts']} concepts"
                )

            return True

        except TemplateGroupRegistryError:
            logger.exception(
                "Canonical template-group registry validation failed closed"
            )
            raise
        except Exception as e:
            logger.error(f"Error loading XBRL templates: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _apply_canonical_registry(self, registry: Dict) -> None:
        """Overlay validated semantics without copying concept membership.

        ``description`` remains the historical API field but now carries the
        canonical user display label. Official taxonomy semantics and legacy
        lookup aliases are exposed in separate fields.
        """
        self.template_group_registry = {
            record["code"]: copy.deepcopy(record)
            for record in registry["template_groups"]
        }
        self.registry_metadata = copy.deepcopy(
            registry.get("_registry_metadata") or {}
        )
        self.registry_metadata.update(
            {
                "registry_id": registry["registry_id"],
                "semantic_inventory_version": registry[
                    "semantic_inventory_version"
                ],
                "source_taxonomy_version": registry[
                    "source_taxonomy_version"
                ],
            }
        )
        self.structural_navigation_nodes = copy.deepcopy(
            registry["structural_navigation_nodes"]
        )

        for code, template in self.templates.items():
            record = self.template_group_registry[code]
            template["legacy_description"] = record[
                "current_runtime_description"
            ]
            template["description"] = record["user_display_name"]
            for field in (
                "template_group_id",
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
                "classification_metadata",
                "compatibility",
                "presentation_linkbase_references",
                "calculation_linkbase_references",
            ):
                template[field] = copy.deepcopy(record[field])
            template["registry_id"] = registry["registry_id"]
            template["semantic_inventory_version"] = registry[
                "semantic_inventory_version"
            ]
            template["semantic_inventory_sha256"] = self.registry_metadata[
                "semantic_inventory_sha256"
            ]

    def _build_indexes(self):
        """Build helper indexes for quick lookup"""
        self.all_concepts = {}
        self.templates_by_concept = {}
        self.required_concepts = set()

        for template_code, template_data in self.templates.items():
            for concept in template_data.get('concepts', []):
                concept_id = concept['id']

                # Add to all concepts
                if concept_id not in self.all_concepts:
                    self.all_concepts[concept_id] = concept.copy()
                    self.all_concepts[concept_id]['templates'] = []

                # Track which templates use this concept
                self.all_concepts[concept_id]['templates'].append(
                    template_code)

                # Track templates by concept
                if concept_id not in self.templates_by_concept:
                    self.templates_by_concept[concept_id] = []
                self.templates_by_concept[concept_id].append(template_code)

                # Track required concepts
                if concept.get('required', False):
                    self.required_concepts.add(concept_id)

    def get_template_codes(self) -> List[str]:
        """Get list of all available template codes"""
        return list(self.templates.keys())

    def get_template(self, code: str) -> Optional[Dict]:
        """Get complete template structure by code"""
        return self.templates.get(code)

    def get_template_description(self, code: str) -> Optional[str]:
        """Get template description"""
        template = self.templates.get(code)
        return template['description'] if template else None

    def get_template_group_registry_record(self, code: str) -> Optional[Dict]:
        """Return an isolated canonical record for a durable template code."""
        record = self.template_group_registry.get(str(code or ""))
        return copy.deepcopy(record) if record else None

    def get_registry_metadata(self) -> Dict:
        """Return registry identity and hashes without exposing mutable state."""
        return copy.deepcopy(self.registry_metadata)

    def get_structural_navigation_nodes(self) -> List[Dict]:
        """Return code-less navigation nodes kept outside the 24-role inventory."""
        return copy.deepcopy(self.structural_navigation_nodes)

    def resolve_legacy_template_label(self, label: str) -> Optional[str]:
        """Resolve a legacy label for grouping only, never mapping mutation."""
        if not self.uses_canonical_registry:
            return None
        return resolve_template_group_label(label)

    def get_template_concepts(self, code: str) -> List[Dict]:
        """Get all concepts for a specific template"""
        template = self.templates.get(code)
        return template.get('concepts', []) if template else []

    def get_required_concepts(self, code: str) -> List[Dict]:
        """Get only required concepts for a specific template"""
        concepts = self.get_template_concepts(code)
        return [c for c in concepts if c.get('required', False)]

    def get_concept_info(self, concept_id: str) -> Optional[Dict]:
        """Get information about a specific concept"""
        return self.all_concepts.get(concept_id)

    def get_embedding_source_concepts(self) -> List[Dict]:
        """Return stable, read-only concept records suitable for shadow embeddings."""
        records = []

        for template_code in sorted(self.templates.keys()):
            template = self.templates[template_code]
            statement_description = template.get("description", template_code)
            for concept in template.get("concepts", []):
                concept_id = concept.get("id", "")
                concept_label = concept.get("label", "")
                source_id = f"{template_code}:{concept_id}"
                aliases = concept.get("aliases") or []
                records.append(
                    {
                        "source_type": "template_service_concept",
                        "source_id": source_id,
                        "template_code": template_code,
                        "statement_description": statement_description,
                        "concept_id": concept_id,
                        "concept_label": concept_label,
                        "namespace": concept.get("namespace"),
                        "level": concept.get("level"),
                        "parent": concept.get("parent"),
                        "required": concept.get("required", False),
                        "position": concept.get("position", 0),
                        "aliases": aliases,
                    }
                )

        return records

    def find_concept_by_label(self, label: str, template_code: Optional[str] = None) -> List[Dict]:
        """
        Find concepts by label text (fuzzy search)

        Args:
            label: Label text to search for
            template_code: Optional template code to filter results

        Returns:
            List of matching concepts with similarity scores
        """
        from difflib import SequenceMatcher

        label_lower = label.lower().strip()
        matches = []

        # Search in specific template or all concepts
        if template_code:
            concepts_to_search = self.get_template_concepts(template_code)
        else:
            concepts_to_search = list(self.all_concepts.values())

        for concept in concepts_to_search:
            concept_label = concept['label'].lower().strip()

            # Calculate string similarity
            similarity = SequenceMatcher(
                None, label_lower, concept_label).ratio()

            # Word overlap bonus
            words_label = set(label_lower.split())
            words_concept = set(concept_label.split())

            if words_label and words_concept:
                overlap = len(words_label & words_concept)
                total = len(words_label | words_concept)
                word_score = overlap / total if total > 0 else 0

                # Weighted score
                combined_score = (similarity * 0.6) + (word_score * 0.4)
            else:
                combined_score = similarity

            # Required field bonus
            if concept.get('required', False):
                combined_score += 0.05

            if combined_score >= 0.3:  # Threshold
                matches.append({
                    **concept,
                    'similarity_score': combined_score
                })

        # Sort by score descending
        matches.sort(key=lambda x: x['similarity_score'], reverse=True)

        return matches

    async def find_matching_concept_hybrid(
        self,
        extracted_label: str,
        template_code: Optional[str] = None,
        db: Optional[AsyncSession] = None
    ) -> Tuple[Optional[str], float]:
        """
        Hybrid matching: string matching + semantic embeddings

        Args:
            extracted_label: Label extracted from PDF
            template_code: Template code to search within
            db: Database session for semantic search

        Returns:
            Tuple of (concept_id, confidence_score)
        """
        # Step 1: String-based matching
        string_matches = self.find_concept_by_label(
            extracted_label, template_code)

        if not string_matches:
            return None, 0.0

        # Step 2: Semantic matching (if database available)
        semantic_matches = {}

        if db is not None:
            try:
                from services.semantic_matcher import semantic_matcher
                from sqlalchemy import text

                if semantic_matcher.is_available():
                    # Generate embedding for extracted label
                    query_embedding = await semantic_matcher.encode_text(extracted_label)

                    if query_embedding and len(query_embedding) == 1752:
                        # Get concept IDs to search
                        concept_ids = [m['id']
                                       for m in string_matches[:20]]  # Top 20

                        # Search taxonomy tags (XBRL tags match concept IDs)
                        sql = text("""
                            SELECT
                                xbrl_tag,
                                1 - (embedding <=> CAST(:query_embedding AS vector)) as similarity
                            FROM mbrs_taxonomy_tags
                            WHERE embedding IS NOT NULL
                                AND xbrl_tag = ANY(:concept_ids)
                            ORDER BY embedding <=> CAST(:query_embedding AS vector)
                            LIMIT 5
                        """)

                        embedding_literal = '[' + \
                            ','.join(map(str, query_embedding)) + ']'

                        result = await db.execute(sql, {
                            "query_embedding": embedding_literal,
                            "concept_ids": concept_ids
                        })

                        rows = result.fetchall()

                        for row in rows:
                            concept_id = row[0]
                            similarity = float(row[1])
                            semantic_matches[concept_id] = similarity

            except Exception as e:
                logger.debug(f"Semantic matching not available: {e}")

        # Step 3: Combine scores
        combined_scores = {}

        for match in string_matches[:20]:
            concept_id = match['id']
            string_score = match['similarity_score']
            semantic_score = semantic_matches.get(concept_id, 0.0)

            if semantic_score > 0:
                # Weighted combination
                combined_score = (string_score * 0.3) + (semantic_score * 0.7)
            else:
                # String only
                combined_score = string_score

            combined_scores[concept_id] = combined_score

        # Find best match
        if not combined_scores:
            return None, 0.0

        best_concept_id = max(combined_scores, key=combined_scores.get)
        best_score = combined_scores[best_concept_id]

        blocked_reason = automatic_mapping_guardrail_reason(best_concept_id, extracted_label)
        if blocked_reason:
            logger.info(
                "Blocked automatic template match for label '%s' to %s by %s; leaving unmatched for manual review",
                extracted_label[:100],
                best_concept_id,
                blocked_reason,
            )
            return None, 0.0

        logger.debug(
            f"Matched '{extracted_label[:50]}' → {best_concept_id} "
            f"(score: {best_score:.2f})"
        )

        return best_concept_id, best_score

    def get_template_for_data_entry(self, template_code: str) -> List[Dict]:
        """
        Get template structure formatted for data entry form

        Returns a list of fields with labels, XBRL tags, and required flags
        """
        concepts = self.get_template_concepts(template_code)

        template_fields = []
        for concept in concepts:
            template_fields.append({
                'concept_id': concept['id'],
                'label': concept['label'],
                'namespace': concept['namespace'],
                'level': concept.get('level', 0),
                'parent': concept.get('parent'),
                'required': concept.get('required', False),
                'position': concept.get('position', 0),
                'value': None,  # Placeholder for user input
                'data_type': 'string',  # Can be enhanced later
                'editable': True
            })

        return template_fields

    def validate_data_completeness(self, template_code: str, provided_concepts: List[str]) -> Dict:
        """
        Validate if all required concepts are provided

        Args:
            template_code: Template code
            provided_concepts: List of concept IDs that have values

        Returns:
            Validation result with missing required concepts
        """
        all_concepts = self.get_template_concepts(template_code)
        required = [c['id'] for c in all_concepts if c.get('required', False)]
        provided_set = set(provided_concepts)

        missing_required = [c for c in required if c not in provided_set]
        missing_optional = [
            c['id'] for c in all_concepts
            if not c.get('required', False) and c['id'] not in provided_set
        ]

        return {
            'is_complete': len(missing_required) == 0,
            'missing_required': missing_required,
            'missing_optional': missing_optional,
            'completion_rate': len(provided_set) / len(all_concepts) if all_concepts else 0,
            'required_count': len(required),
            'provided_required_count': len([c for c in required if c in provided_set])
        }

    def get_statistics(self) -> Dict:
        """Get statistics about loaded templates"""
        template_stats = {}

        for code, template in self.templates.items():
            template_stats[code] = {
                'description': template['description'],
                'total_concepts': template['total_concepts'],
                'required_concepts': template['required_count'],
                'optional_concepts': template['total_concepts'] - template['required_count']
            }

        return {
            'total_templates': len(self.templates),
            'total_concepts': len(self.all_concepts),
            'total_required': len(self.required_concepts),
            'total_optional': len(self.all_concepts) - len(self.required_concepts),
            'templates': template_stats,
            'namespaces': self.namespaces
        }

    def export_template_to_csv(self, output_file: str):
        """Export all templates to CSV for reference"""
        import csv

        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Template Code', 'Template Description', 'Position',
                'Concept ID', 'Label', 'Namespace', 'Required', 'Level', 'Parent'
            ])

            for code in sorted(self.templates.keys()):
                template = self.templates[code]
                for concept in template.get('concepts', []):
                    writer.writerow([
                        code,
                        template['description'],
                        concept.get('position', 0),
                        concept['id'],
                        concept['label'],
                        concept['namespace'],
                        'Yes' if concept.get('required', False) else 'No',
                        concept.get('level', 0),
                        concept.get('parent', '')
                    ])

        logger.info(f"✅ Exported templates to {output_file}")


# Global instance
xbrl_template_service = XBRLTemplateService()


def get_xbrl_template_service() -> XBRLTemplateService:
    """Get the global XBRL template service instance"""
    return xbrl_template_service


def reload_templates():
    """Reload templates from file"""
    return xbrl_template_service.load_templates()
