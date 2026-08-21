# services/taxonomy_linkbase_service.py
"""
Taxonomy Linkbase Service - Stub Implementation
This is a temporary stub until the full linkbase parser is implemented.
"""

import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class CalculationRelationship:
    """Represents a calculation relationship in the taxonomy"""
    def __init__(self, parent_tag: str, child_tag: str, weight: float = 1.0):
        self.parent_tag = parent_tag
        self.child_tag = child_tag
        self.weight = weight


class TaxonomyLinkbaseService:
    """
    Service to parse and access XBRL taxonomy linkbases

    Current implementation is a stub that returns empty results.
    TODO: Implement full linkbase parsing from taxonomy/SSMxT_2022v1.0/
    """

    def __init__(self):
        logger.info("⚠️ TaxonomyLinkbaseService initialized (stub mode - calculation validation disabled)")

    def get_calculation_linkbase(self, role_code: str) -> List[CalculationRelationship]:
        """
        Get calculation relationships for a specific role

        Args:
            role_code: Role code (e.g., '200100', '300100')

        Returns:
            List of calculation relationships (currently empty)
        """
        # TODO: Parse calculation linkbase XML files
        # For now, return empty to disable validation
        return []

    def get_presentation_linkbase(self, role_code: str) -> Dict:
        """
        Get presentation structure for a specific role

        Args:
            role_code: Role code

        Returns:
            Presentation structure (currently empty)
        """
        # TODO: Parse presentation linkbase XML files
        return {}


# Global instance
_taxonomy_service = None


def get_taxonomy_service() -> TaxonomyLinkbaseService:
    """Get or create the global taxonomy linkbase service instance"""
    global _taxonomy_service
    if _taxonomy_service is None:
        _taxonomy_service = TaxonomyLinkbaseService()
    return _taxonomy_service
