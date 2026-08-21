# services/xbrl_validator.py
"""
XBRL validation service to check if all required fields are filled before generation
"""
from typing import Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from database import FilingJob, FinancialStatementPage, ExtractedDataItem, XMLTemplateField
import logging

logger = logging.getLogger(__name__)


class XBRLValidator:
    """Validates that all required fields are filled before XBRL generation"""

    async def validate_job_for_xbrl(
        self,
        job_id: int,
        db: AsyncSession
    ) -> Dict:
        """
        Validate that a job has all required fields filled

        Returns:
            Dict with validation results:
            {
                'is_valid': bool,
                'errors': List[str],
                'warnings': List[str],
                'missing_required_fields': List[Dict],
                'statistics': Dict
            }
        """
        try:
            # Load job
            stmt = (
                select(FilingJob)
                .options(
                    selectinload(FilingJob.pages)
                    .selectinload(FinancialStatementPage.extracted_items)
                    .selectinload(ExtractedDataItem.confirmed_tag)
                )
                .where(FilingJob.id == job_id)
            )

            result = await db.execute(stmt)
            job = result.scalar_one_or_none()

            if not job:
                return {
                    'is_valid': False,
                    'errors': ['Filing job not found'],
                    'warnings': [],
                    'missing_required_fields': [],
                    'statistics': {}
                }

            errors = []
            warnings = []
            missing_fields = []

            # Check basic job information
            if not job.company_name:
                errors.append("Company name is required")

            if not job.registration_number:
                warnings.append("Registration number is recommended")

            if not job.financial_year_end:
                errors.append("Financial year end date is required")

            # Collect all extracted items
            all_items = []
            for page in job.pages:
                all_items.extend(page.extracted_items)

            if not all_items:
                fallback_items_stmt = (
                    select(ExtractedDataItem)
                    .join(FinancialStatementPage)
                    .where(FinancialStatementPage.job_id == job_id)
                )
                result = await db.execute(fallback_items_stmt)
                all_items = result.scalars().all()

            if not all_items:
                errors.append("No extracted data items found")
                return {
                    'is_valid': False,
                    'errors': errors,
                    'warnings': warnings,
                    'missing_required_fields': missing_fields,
                    'statistics': {
                        'total_items': 0,
                        'reviewed_items': 0,
                        'items_with_tags': 0,
                        'items_with_template_mappings': 0,
                        'items_with_mapping_evidence': 0,
                        'reviewed_mappable_items': 0
                    }
                }

            # Count statistics
            total_items = len(all_items)
            reviewed_items = sum(1 for item in all_items if item.is_reviewed)
            items_with_tags = sum(1 for item in all_items if item.confirmed_tag_id)
            items_with_template_mappings = sum(1 for item in all_items if item.template_field_id)
            items_with_mapping_evidence = sum(
                1
                for item in all_items
                if item.confirmed_tag_id or item.template_field_id
            )
            reviewed_mappable_items = sum(
                1
                for item in all_items
                if item.is_reviewed and (item.confirmed_tag_id or item.template_field_id)
            )
            items_with_values = sum(1 for item in all_items if item.extracted_value)

            # Get all required template fields for the statements in this job
            statement_types = set(item.statement_type for item in all_items if item.statement_type)

            if statement_types:
                required_fields_stmt = (
                    select(XMLTemplateField)
                    .where(
                        XMLTemplateField.required == True,
                        XMLTemplateField.statement_type.in_(statement_types)
                    )
                )

                result = await db.execute(required_fields_stmt)
                required_fields = result.scalars().all()

                # Check which required fields are missing
                filled_field_ids = set(
                    item.template_field_id
                    for item in all_items
                    if item.template_field_id and item.extracted_value
                )

                for req_field in required_fields:
                    if req_field.field_id not in filled_field_ids:
                        missing_fields.append({
                            'field_id': req_field.field_id,
                            'label': req_field.label,
                            'xbrl_tag': req_field.xbrl_tag,
                            'statement_type': req_field.statement_type,
                            'statement_code': req_field.statement_code
                        })

            # Add validation checks
            if reviewed_items == 0:
                warnings.append("No items have been reviewed yet")
            elif reviewed_items < total_items * 0.5:
                warnings.append(f"Only {reviewed_items}/{total_items} items have been reviewed (less than 50%)")

            if reviewed_mappable_items == 0:
                warnings.append("Extracted rows exist, but no reviewed mappable rows were found.")

            if items_with_tags == 0 and items_with_template_mappings > 0:
                warnings.append("Using template mappings. No manual taxonomy tags confirmed.")
            elif items_with_tags == 0:
                warnings.append("Some extracted rows are unmapped and were not included in the generated XBRL.")
            elif items_with_tags < total_items * 0.3:
                warnings.append(f"Only {items_with_tags}/{total_items} items have confirmed tags (less than 30%)")

            if items_with_mapping_evidence < total_items:
                unmapped_count = total_items - items_with_mapping_evidence
                warnings.append(f"{unmapped_count}/{total_items} extracted rows are unmapped and may not be included in generated XBRL.")

            if items_with_values < total_items * 0.5:
                warnings.append(f"Only {items_with_values}/{total_items} items have values filled")

            if missing_fields:
                errors.append(f"Missing {len(missing_fields)} required fields")

            # Determine if valid
            is_valid = len(errors) == 0

            statistics = {
                'total_items': total_items,
                'reviewed_items': reviewed_items,
                'items_with_tags': items_with_tags,
                'items_with_template_mappings': items_with_template_mappings,
                'items_with_mapping_evidence': items_with_mapping_evidence,
                'reviewed_mappable_items': reviewed_mappable_items,
                'items_with_values': items_with_values,
                'required_fields_count': len(required_fields) if statement_types else 0,
                'missing_required_fields_count': len(missing_fields),
                'statement_types': list(statement_types)
            }

            logger.info(f"Validation for job {job_id}: valid={is_valid}, errors={len(errors)}, warnings={len(warnings)}")

            return {
                'is_valid': is_valid,
                'errors': errors,
                'warnings': warnings,
                'missing_required_fields': missing_fields,
                'statistics': statistics
            }

        except Exception as e:
            logger.error(f"Error validating job {job_id}: {e}", exc_info=True)
            return {
                'is_valid': False,
                'errors': [f"Validation error: {str(e)}"],
                'warnings': [],
                'missing_required_fields': [],
                'statistics': {}
            }

    async def get_required_fields_for_statement(
        self,
        statement_code: str,
        db: AsyncSession
    ) -> List[Dict]:
        """Get all required fields for a specific statement type"""

        stmt = (
            select(XMLTemplateField)
            .where(
                XMLTemplateField.statement_code == statement_code,
                XMLTemplateField.required == True
            )
            .order_by(XMLTemplateField.position)
        )

        result = await db.execute(stmt)
        fields = result.scalars().all()

        return [
            {
                'field_id': field.field_id,
                'label': field.label,
                'xbrl_tag': field.xbrl_tag,
                'data_type': field.data_type,
                'position': field.position
            }
            for field in fields
        ]


# Global instance
xbrl_validator = XBRLValidator()
