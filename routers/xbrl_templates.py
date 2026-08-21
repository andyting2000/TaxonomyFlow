# routers/xbrl_templates.py
"""
XBRL Templates Router - API endpoints for accessing MPERS XBRL templates

Provides REST API access to template structures extracted from SSMxT taxonomy.
Replaces the old xml_template.py router with proper XBRL-compliant templates.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from pydantic import BaseModel
import logging

from database import get_db
from services.xbrl_template_service import get_xbrl_template_service
from security import require_admin_route_token

logger = logging.getLogger(__name__)
router = APIRouter()


# Pydantic models for responses
class ConceptResponse(BaseModel):
    """Single concept/field information"""
    id: str
    label: str
    namespace: str
    level: int
    parent: Optional[str]
    required: bool
    position: int

    class Config:
        from_attributes = True


class TemplateListItem(BaseModel):
    """Template summary for list view"""
    code: str
    description: str
    role_uri: str
    official_role_definition: str
    canonical_name: str
    user_display_name: str
    aliases: List[str]
    template_kind: str
    structural_role: str
    statement_family: str
    classification_enabled: bool
    mapping_enabled: bool
    source_taxonomy_version: str
    total_concepts: int
    required_count: int


class TemplateDetailResponse(BaseModel):
    """Full template structure"""
    code: str
    description: str
    role_uri: str
    official_role_definition: str
    role_id: str
    canonical_name: str
    user_display_name: str
    normalized_name: str
    aliases: List[str]
    template_kind: str
    structural_role: str
    statement_family: str
    classification_enabled: bool
    mapping_enabled: bool
    allows_multiple_source_sections: bool
    source_taxonomy_version: str
    semantic_inventory_version: str
    classification_metadata: dict
    compatibility: dict
    total_concepts: int
    required_count: int
    concepts: List[ConceptResponse]


class TemplateStatsResponse(BaseModel):
    """Template statistics"""
    total_templates: int
    total_concepts: int
    total_required: int
    total_optional: int


class ConceptSearchResult(BaseModel):
    """Concept search result with similarity score"""
    id: str
    label: str
    namespace: str
    required: bool
    similarity_score: float
    templates: List[str]  # Template codes that use this concept


@router.get("/", response_model=List[TemplateListItem])
async def list_templates():
    """
    Get list of all available XBRL MPERS templates

    Returns a summary of each template with code, description, and concept counts.
    """
    service = get_xbrl_template_service()

    templates = []
    for code in sorted(service.get_template_codes()):
        template = service.get_template(code)
        if template:
            templates.append(TemplateListItem(
                code=template['code'],
                description=template['description'],
                role_uri=template['role_uri'],
                official_role_definition=template['official_role_definition'],
                canonical_name=template['canonical_name'],
                user_display_name=template['user_display_name'],
                aliases=template['aliases'],
                template_kind=template['template_kind'],
                structural_role=template['structural_role'],
                statement_family=template['statement_family'],
                classification_enabled=template['classification_enabled'],
                mapping_enabled=template['mapping_enabled'],
                source_taxonomy_version=template['source_taxonomy_version'],
                total_concepts=template['total_concepts'],
                required_count=template['required_count']
            ))

    logger.info(f"📋 Listed {len(templates)} XBRL templates")

    return templates


@router.get("/stats", response_model=TemplateStatsResponse)
async def get_template_statistics():
    """
    Get overall statistics about XBRL templates

    Returns counts of templates, concepts, required vs optional fields, etc.
    """
    service = get_xbrl_template_service()
    stats = service.get_statistics()

    return TemplateStatsResponse(
        total_templates=stats['total_templates'],
        total_concepts=stats['total_concepts'],
        total_required=stats['total_required'],
        total_optional=stats['total_optional']
    )


@router.get("/registry")
async def get_template_group_registry():
    """Expose registry identity and code-less structural navigation metadata."""
    service = get_xbrl_template_service()
    return {
        **service.get_registry_metadata(),
        "expected_template_count": 24,
        "actual_template_count": len(service.get_template_codes()),
        "durable_identity_fields": ["code", "role_uri"],
        "structural_navigation_nodes": service.get_structural_navigation_nodes(),
    }


@router.get("/{template_code}", response_model=TemplateDetailResponse)
async def get_template(template_code: str):
    """
    Get complete template structure by code

    Args:
        template_code: 6-digit template code (e.g., "020000", "210000")

    Returns:
        Full template with all concepts, labels, and hierarchy
    """
    service = get_xbrl_template_service()
    template = service.get_template(template_code)

    if not template:
        raise HTTPException(
            status_code=404,
            detail=f"Template {template_code} not found"
        )

    # Convert concepts to response model
    concepts = [
        ConceptResponse(
            id=c['id'],
            label=c['label'],
            namespace=c['namespace'],
            level=c.get('level', 0),
            parent=c.get('parent'),
            required=c.get('required', False),
            position=c.get('position', 0)
        )
        for c in template.get('concepts', [])
    ]

    logger.info(f"📄 Retrieved template {template_code}: {template['description']}")

    return TemplateDetailResponse(
        code=template['code'],
        description=template['description'],
        role_uri=template['role_uri'],
        official_role_definition=template['official_role_definition'],
        role_id=template['role_id'],
        canonical_name=template['canonical_name'],
        user_display_name=template['user_display_name'],
        normalized_name=template['normalized_name'],
        aliases=template['aliases'],
        template_kind=template['template_kind'],
        structural_role=template['structural_role'],
        statement_family=template['statement_family'],
        classification_enabled=template['classification_enabled'],
        mapping_enabled=template['mapping_enabled'],
        allows_multiple_source_sections=template[
            'allows_multiple_source_sections'
        ],
        source_taxonomy_version=template['source_taxonomy_version'],
        semantic_inventory_version=template['semantic_inventory_version'],
        classification_metadata=template['classification_metadata'],
        compatibility=template['compatibility'],
        total_concepts=template['total_concepts'],
        required_count=template['required_count'],
        concepts=concepts
    )


@router.get("/{template_code}/concepts", response_model=List[ConceptResponse])
async def get_template_concepts(
    template_code: str,
    required_only: bool = Query(False, description="Return only required concepts")
):
    """
    Get concepts for a specific template

    Args:
        template_code: 6-digit template code
        required_only: If true, return only required concepts

    Returns:
        List of concepts with labels and metadata
    """
    service = get_xbrl_template_service()

    if required_only:
        concepts = service.get_required_concepts(template_code)
    else:
        concepts = service.get_template_concepts(template_code)

    if concepts is None:
        raise HTTPException(
            status_code=404,
            detail=f"Template {template_code} not found"
        )

    concept_responses = [
        ConceptResponse(
            id=c['id'],
            label=c['label'],
            namespace=c['namespace'],
            level=c.get('level', 0),
            parent=c.get('parent'),
            required=c.get('required', False),
            position=c.get('position', 0)
        )
        for c in concepts
    ]

    filter_desc = "required" if required_only else "all"
    logger.info(f"📋 Retrieved {len(concept_responses)} {filter_desc} concepts for template {template_code}")

    return concept_responses


@router.get("/{template_code}/data-entry")
async def get_template_for_data_entry(template_code: str):
    """
    Get template formatted for data entry form

    Returns template structure with placeholders for user input.
    Useful for building dynamic forms in the frontend.
    """
    service = get_xbrl_template_service()
    template = service.get_template(template_code)

    if not template:
        raise HTTPException(
            status_code=404,
            detail=f"Template {template_code} not found"
        )

    data_entry_fields = service.get_template_for_data_entry(template_code)

    return {
        "template_code": template_code,
        "template_description": template['description'],
        "total_fields": len(data_entry_fields),
        "required_fields": sum(1 for f in data_entry_fields if f['required']),
        "fields": data_entry_fields
    }


@router.post("/{template_code}/validate")
async def validate_template_data(
    template_code: str,
    provided_concepts: List[str]
):
    """
    Validate data completeness for a template

    Args:
        template_code: Template code
        provided_concepts: List of concept IDs that have been filled

    Returns:
        Validation result with missing required concepts
    """
    service = get_xbrl_template_service()
    template = service.get_template(template_code)

    if not template:
        raise HTTPException(
            status_code=404,
            detail=f"Template {template_code} not found"
        )

    validation_result = service.validate_data_completeness(
        template_code,
        provided_concepts
    )

    return {
        "template_code": template_code,
        "is_complete": validation_result['is_complete'],
        "completion_rate": validation_result['completion_rate'],
        "required_count": validation_result['required_count'],
        "provided_required_count": validation_result['provided_required_count'],
        "missing_required": validation_result['missing_required'],
        "missing_optional_count": len(validation_result['missing_optional'])
    }


@router.get("/search/concepts", response_model=List[ConceptSearchResult])
async def search_concepts(
    query: str = Query(..., min_length=2, description="Search query"),
    template_code: Optional[str] = Query(None, description="Filter by template code"),
    limit: int = Query(10, ge=1, le=50, description="Maximum results")
):
    """
    Search for concepts by label text

    Performs fuzzy matching on concept labels across all templates.

    Args:
        query: Search text
        template_code: Optional template code to filter results
        limit: Maximum number of results

    Returns:
        List of matching concepts with similarity scores
    """
    service = get_xbrl_template_service()

    matches = service.find_concept_by_label(query, template_code)

    # Limit results
    matches = matches[:limit]

    results = [
        ConceptSearchResult(
            id=m['id'],
            label=m['label'],
            namespace=m['namespace'],
            required=m.get('required', False),
            similarity_score=m['similarity_score'],
            templates=m.get('templates', [])
        )
        for m in matches
    ]

    logger.info(f"🔍 Concept search '{query}' returned {len(results)} results")

    return results


@router.get("/concept/{concept_id}")
async def get_concept_details(concept_id: str):
    """
    Get detailed information about a specific concept

    Args:
        concept_id: Full concept ID (e.g., "ssmt:DateOfFinancialStatements...")

    Returns:
        Concept details including which templates use it
    """
    service = get_xbrl_template_service()
    concept_info = service.get_concept_info(concept_id)

    if not concept_info:
        raise HTTPException(
            status_code=404,
            detail=f"Concept {concept_id} not found"
        )

    return {
        "id": concept_info['id'],
        "label": concept_info['label'],
        "namespace": concept_info['namespace'],
        "level": concept_info.get('level', 0),
        "parent": concept_info.get('parent'),
        "required": concept_info.get('required', False),
        "used_in_templates": concept_info.get('templates', [])
    }


@router.post("/export/csv", dependencies=[Depends(require_admin_route_token)])
async def export_templates_to_csv():
    """
    Export all templates to CSV file

    Generates a CSV file with all templates and concepts for offline reference.
    """
    service = get_xbrl_template_service()

    output_path = "xbrl_templates_export.csv"
    service.export_template_to_csv(output_path)

    return {
        "success": True,
        "file_path": output_path,
        "message": f"Exported {len(service.templates)} templates to CSV"
    }
