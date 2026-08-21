# services/calculation_validator.py
"""
Real-time calculation validation for extracted financial data
Integrates with taxonomy linkbase service to validate mathematical relationships
"""

import json
import logging
from typing import Dict, List, Optional, Tuple
from services.taxonomy_linkbase_service import get_taxonomy_service

logger = logging.getLogger(__name__)


class CalculationValidator:
    """
    Validates calculation relationships for extracted financial data
    Uses SSMxT 2022 taxonomy calculation linkbases
    """

    def __init__(self):
        self.taxonomy_service = get_taxonomy_service()
        self.statement_type_to_role = {
            'Statement of Financial Position': '200100',
            'Statement of Financial Position - Current/Non-current': '200100',
            'Statement of Financial Position - Liquidity': '200200',
            'Statement of Profit or Loss': '300100',
            'Statement of Profit or Loss - Function': '300100',
            'Statement of Profit or Loss - Nature': '300200',
            'Statement of Profit or Loss and Other Comprehensive Income': '400100',
            'Statement of Comprehensive Income': '400100',
            'Statement of Cash Flows': '500100',
            'Statement of Cash Flows - Direct': '500100',
            'Statement of Cash Flows - Indirect': '520000',
            'Statement of Changes in Equity': '610000',
        }

    def validate_extracted_items(
        self,
        items: List[Dict],
        statement_type: str
    ) -> Dict[str, any]:
        """
        Validate calculation relationships for a set of extracted items

        Args:
            items: List of extracted data items with 'label' and 'value'
            statement_type: Type of financial statement

        Returns:
            Dictionary with validation results:
            {
                'valid': bool,
                'warnings': List[str],
                'item_warnings': Dict[label, List[warnings]],
                'validated_count': int
            }
        """
        try:
            role_code = self.statement_type_to_role.get(statement_type)

            if not role_code:
                logger.debug(f"No role code mapping for statement type: {statement_type}")
                return {
                    'valid': True,
                    'warnings': [],
                    'item_warnings': {},
                    'validated_count': 0
                }

            # Get calculation linkbase for this statement
            calc_relationships = self.taxonomy_service.get_calculation_linkbase(role_code)

            if not calc_relationships:
                logger.debug(f"No calculation linkbase found for role: {role_code}")
                return {
                    'valid': True,
                    'warnings': [],
                    'item_warnings': {},
                    'validated_count': 0
                }

            # Parse numeric values from items
            item_values = {}
            for item in items:
                label = item.get('label', '').strip()
                value_str = str(item.get('value', '')).strip()

                # Try to extract numeric value
                numeric_value = self._extract_numeric_value(value_str)
                if numeric_value is not None:
                    item_values[label] = numeric_value

            if not item_values:
                return {
                    'valid': True,
                    'warnings': [],
                    'item_warnings': {},
                    'validated_count': 0
                }

            # Validate calculations
            warnings = []
            item_warnings = {}
            validated_count = 0

            # Group relationships by parent
            parent_children = {}
            for rel in calc_relationships:
                parent = rel.parent_tag
                if parent not in parent_children:
                    parent_children[parent] = []
                parent_children[parent].append((rel.child_tag, rel.weight))

            # Validate each parent-child relationship
            for parent_tag, children in parent_children.items():
                # Find parent value in extracted items (fuzzy matching)
                parent_value = self._find_value_by_tag(parent_tag, item_values)

                if parent_value is None:
                    continue  # Parent not found, skip validation

                # Calculate expected value from children
                calculated_sum = 0.0
                found_children = []
                missing_children = []

                for child_tag, weight in children:
                    child_value = self._find_value_by_tag(child_tag, item_values)
                    if child_value is not None:
                        calculated_sum += child_value * weight
                        found_children.append((child_tag, child_value, weight))
                    else:
                        missing_children.append(child_tag)

                # Only validate if we found at least some children
                if found_children:
                    tolerance = abs(parent_value) * 0.02  # 2% tolerance for rounding
                    tolerance = max(tolerance, 1.0)  # Minimum tolerance of 1

                    difference = abs(parent_value - calculated_sum)

                    if difference > tolerance:
                        # Calculation mismatch detected
                        warning_msg = (
                            f"Calculation warning for '{parent_tag}': "
                            f"Expected {calculated_sum:,.2f} (sum of {len(found_children)} components), "
                            f"got {parent_value:,.2f} (difference: {difference:,.2f})"
                        )
                        warnings.append(warning_msg)

                        # Add warning to parent item
                        parent_label = self._find_label_by_tag(parent_tag, items)
                        if parent_label:
                            if parent_label not in item_warnings:
                                item_warnings[parent_label] = []
                            item_warnings[parent_label].append({
                                'type': 'calculation_mismatch',
                                'message': warning_msg,
                                'expected': calculated_sum,
                                'actual': parent_value,
                                'difference': difference
                            })

                        validated_count += 1
                    else:
                        # Calculation is valid
                        validated_count += 1
                        logger.debug(
                            f"✅ Calculation valid for {parent_tag}: "
                            f"{parent_value:,.2f} ≈ {calculated_sum:,.2f}"
                        )

            return {
                'valid': len(warnings) == 0,
                'warnings': warnings,
                'item_warnings': item_warnings,
                'validated_count': validated_count
            }

        except Exception as e:
            logger.error(f"Error during calculation validation: {e}", exc_info=True)
            return {
                'valid': True,  # Don't fail processing on validation errors
                'warnings': [f"Validation error: {str(e)}"],
                'item_warnings': {},
                'validated_count': 0
            }

    def _extract_numeric_value(self, value_str: str) -> Optional[float]:
        """
        Extract numeric value from string, handling various formats

        Args:
            value_str: String containing numeric value

        Returns:
            Float value or None
        """
        if not value_str:
            return None

        # Remove common non-numeric characters
        cleaned = value_str.replace(',', '').replace(' ', '').strip()

        # Handle parentheses for negative values (accounting format)
        is_negative = cleaned.startswith('(') and cleaned.endswith(')')
        if is_negative:
            cleaned = cleaned[1:-1]

        # Remove currency symbols and other characters
        import re
        cleaned = re.sub(r'[^\d.-]', '', cleaned)

        if not cleaned or cleaned in ['-', '.', '-.']:
            return None

        try:
            value = float(cleaned)
            return -value if is_negative else value
        except (ValueError, TypeError):
            return None

    def _find_value_by_tag(self, tag: str, item_values: Dict[str, float]) -> Optional[float]:
        """
        Find value by XBRL tag using fuzzy matching on labels

        Args:
            tag: XBRL tag name (e.g., 'Assets', 'PropertyPlantAndEquipment')
            item_values: Dictionary of label -> value

        Returns:
            Numeric value or None
        """
        # Convert tag to searchable terms (e.g., 'PropertyPlantAndEquipment' -> 'property plant equipment')
        tag_terms = self._tag_to_search_terms(tag)

        # Try exact matches first
        for label, value in item_values.items():
            label_lower = label.lower()

            # Exact match
            if tag.lower() in label_lower or label_lower in tag.lower():
                return value

            # Term matching
            if any(term in label_lower for term in tag_terms):
                return value

        return None

    def _find_label_by_tag(self, tag: str, items: List[Dict]) -> Optional[str]:
        """Find original label by XBRL tag"""
        tag_terms = self._tag_to_search_terms(tag)

        for item in items:
            label = item.get('label', '').lower()
            if tag.lower() in label or any(term in label for term in tag_terms):
                return item.get('label')

        return None

    def _tag_to_search_terms(self, tag: str) -> List[str]:
        """
        Convert camelCase XBRL tag to searchable terms

        Example: 'PropertyPlantAndEquipment' -> ['property', 'plant', 'equipment']
        """
        import re

        # Split camelCase
        words = re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\W|$)|\d+', tag)

        # Convert to lowercase and filter out common words
        stop_words = {'and', 'or', 'the', 'a', 'an', 'of', 'in', 'on', 'at'}
        terms = [w.lower() for w in words if w.lower() not in stop_words and len(w) > 2]

        return terms


# Global instance
calculation_validator = CalculationValidator()
