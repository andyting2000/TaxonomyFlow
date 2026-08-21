# services/smart_ai_processor.py - MULTI-TEMPLATE SYSTEM
"""
Smart AI Processor with Multi-Template Two-Stage Extraction
Stage 1: Classify ALL statement types on page
Stage 2: Extract data using MULTIPLE template-guided prompts
Uses semantic matching for field mapping
"""

import fitz
import json
import base64
import os
import re
import asyncio
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from huggingface_hub import AsyncInferenceClient
from datetime import datetime, timezone

from config import settings
from database import FilingJob, FinancialStatementPage, ExtractedDataItem
from file_safety import assert_upload_child, resolve_upload_path
from schemas import ProcessingStatus, JobStatus, ProgressUpdate
from services.xbrl_template_service import (
    automatic_mapping_guardrail_reason,
    get_xbrl_template_service,
)
from services.stage1_classifier import statement_classifier
from services.prompts.stage2_prompt_builder import stage2_prompt_builder
from services.calculation_validator import calculation_validator

import logging

logger = logging.getLogger(__name__)
SIGNED_VALUE_RE = re.compile(r"(^|[^\d])- ?\d|\(\s*[\d,]+(?:\.\d+)?\s*\)")


class SmartAIProcessor:
    """
    Smart AI Processor with multi-template two-stage extraction and semantic matching
    """

    def __init__(self):
        self.provider = settings.model_provider
        self.text_client = AsyncInferenceClient(
            model=settings.ai_text_model_id,
            token=settings.model_api_token or settings.hugging_face_token,
        )
        self.vlm_client = AsyncInferenceClient(
            model=settings.ai_vlm_model_id,
            token=settings.model_api_token or settings.hugging_face_token,
        )
        self.progress_callbacks = []
        self._semantic_match_cache: Dict[Tuple[str, str], Dict[str, Any]] = {}

        # Enable PyMuPDF anti-aliasing for better rendering quality (CPU-only)
        # Anti-aliasing level 8 provides best quality for text rendering
        fitz.TOOLS.set_aa_level(8)

        logger.info(
            "✅ Smart AI Processor (Multi-Template Two-Stage) initialized with AA level 8")

    def add_progress_callback(self, callback):
        """Add a callback function for progress updates"""
        self.progress_callbacks.append(callback)

    def _get_template_statement_type(self, template: Dict, statement_code: str) -> str:
        """Return a stable statement label from current template metadata."""
        for key in ("description", "title", "statement_type"):
            value = template.get(key)
            if value and str(value).strip():
                return str(value).strip()

        code = template.get("code") or statement_code
        return str(code or "").strip()

    def _create_extracted_data_item(
        self,
        page_id: str,
        cleaned_item: Dict,
        template: Dict,
        statement_code: str,
    ) -> ExtractedDataItem:
        return ExtractedDataItem(
            page_id=page_id,
            extracted_label=cleaned_item['label'][:1000],
            extracted_value=str(cleaned_item['value'])[:5000],
            financial_year=cleaned_item.get('year'),
            statement_type=self._get_template_statement_type(
                template, statement_code),
        )

    def _normalize_metric_text(self, value: Any) -> str:
        return " ".join(str(value or "").strip().lower().split())

    def _get_item_metric_value(self, item: Any, *attribute_names: str) -> str:
        for attribute_name in attribute_names:
            if isinstance(item, dict):
                value = item.get(attribute_name)
            else:
                value = getattr(item, attribute_name, None)

            if value is not None:
                return str(value)

        return ""

    def _build_extraction_quality_summary(self, items: List[Any]) -> Dict[str, Any]:
        label_counter: Counter = Counter()
        label_value_counter: Counter = Counter()
        label_examples: Dict[str, str] = {}
        label_value_examples: Dict[str, Dict[str, str]] = {}

        rows_with_template_field_id = 0
        rows_with_blank_statement_type = 0
        suspicious_signed_value_count = 0
        reviewed_count = 0
        tagged_count = 0

        for item in items:
            label = self._get_item_metric_value(
                item, 'extracted_label', 'label')
            value = self._get_item_metric_value(
                item, 'extracted_value', 'value')
            previous_value = self._get_item_metric_value(
                item, 'value_previous_year', 'previous_value')
            statement_type = self._get_item_metric_value(
                item, 'statement_type')
            template_field_id = self._get_item_metric_value(
                item, 'template_field_id')

            if template_field_id.strip():
                rows_with_template_field_id += 1

            if not statement_type.strip():
                rows_with_blank_statement_type += 1

            normalized_label = self._normalize_metric_text(label)
            normalized_value = self._normalize_metric_text(value)
            if normalized_label:
                label_counter[normalized_label] += 1
                label_examples.setdefault(normalized_label, label.strip())

                combined_key = f"{normalized_label}|{normalized_value}"
                label_value_counter[combined_key] += 1
                label_value_examples.setdefault(
                    combined_key,
                    {'label': label.strip(), 'value': value.strip()}
                )

            if any(
                SIGNED_VALUE_RE.search(str(candidate or ""))
                for candidate in (value, previous_value)
            ):
                suspicious_signed_value_count += 1

            if bool(getattr(item, 'is_reviewed', False)):
                reviewed_count += 1

            if getattr(item, 'confirmed_tag_id', None) is not None:
                tagged_count += 1

        duplicate_label_candidates = [
            {'label': label_examples[key], 'count': count}
            for key, count in label_counter.items()
            if count > 1
        ]
        duplicate_label_value_candidates = [
            {**label_value_examples[key], 'count': count}
            for key, count in label_value_counter.items()
            if count > 1
        ]

        return {
            'total_extracted_rows': len(items),
            'rows_with_template_field_id': rows_with_template_field_id,
            'rows_without_template_field_id': len(items) - rows_with_template_field_id,
            'rows_with_blank_statement_type': rows_with_blank_statement_type,
            'duplicate_label_count': sum(count - 1 for count in label_counter.values() if count > 1),
            'duplicate_label_value_count': sum(count - 1 for count in label_value_counter.values() if count > 1),
            'duplicate_label_candidates': duplicate_label_candidates[:5],
            'duplicate_label_value_candidates': duplicate_label_value_candidates[:5],
            'suspicious_signed_value_count': suspicious_signed_value_count,
            'reviewed_count': reviewed_count,
            'tagged_count': tagged_count,
            'reviewed_or_tagged_count': sum(
                1 for item in items
                if bool(getattr(item, 'is_reviewed', False)) or getattr(item, 'confirmed_tag_id', None) is not None
            ),
        }

    def _log_extraction_quality_summary(
        self,
        *,
        job_id: int,
        page_num: int,
        items: List[Any],
        matched_count: int,
        validation_warnings_count: int,
        templates_used_count: int,
    ) -> Dict[str, Any]:
        summary = self._build_extraction_quality_summary(items)
        logger.info(
            "Extraction summary for job %s page %s: total_extracted_rows=%s rows_with_template_field_id=%s rows_without_template_field_id=%s rows_with_blank_statement_type=%s duplicate_label_count=%s duplicate_label_value_count=%s suspicious_signed_value_count=%s reviewed_count=%s tagged_count=%s reviewed_or_tagged_count=%s matched_count=%s validation_warnings=%s templates_used=%s",
            job_id,
            page_num + 1,
            summary['total_extracted_rows'],
            summary['rows_with_template_field_id'],
            summary['rows_without_template_field_id'],
            summary['rows_with_blank_statement_type'],
            summary['duplicate_label_count'],
            summary['duplicate_label_value_count'],
            summary['suspicious_signed_value_count'],
            summary['reviewed_count'],
            summary['tagged_count'],
            summary['reviewed_or_tagged_count'],
            matched_count,
            validation_warnings_count,
            templates_used_count,
        )

        if summary['duplicate_label_candidates'] or summary['duplicate_label_value_candidates']:
            logger.warning(
                "Duplicate extraction candidates for job %s page %s: duplicate_label_candidates=%s duplicate_label_value_candidates=%s",
                job_id,
                page_num + 1,
                summary['duplicate_label_candidates'],
                summary['duplicate_label_value_candidates'],
            )

        return summary

    def _preprocess_image_for_vlm(self, image_path: str):
        """
        CPU-only image preprocessing to improve VLM accuracy
        Uses Pillow for all operations - NO GPU/CUDA required

        Improvements:
        - Contrast enhancement for better text visibility
        - Sharpness enhancement for clearer text edges
        - Brightness normalization for consistent lighting

        Args:
            image_path: Path to the rendered PDF page image

        Returns:
            Preprocessed PIL Image
        """
        from PIL import Image, ImageEnhance, ImageOps
        import numpy as np

        try:
            # Load image
            img = Image.open(image_path)

            # Convert to RGB if needed
            if img.mode != 'RGB':
                img = img.convert('RGB')

            # 1. Auto-contrast adjustment for better visibility
            # This normalizes the brightness/contrast distribution
            img = ImageOps.autocontrast(img, cutoff=1)

            # 2. Enhance contrast (CPU-only operation)
            # Factor > 1.0 increases contrast
            contrast_enhancer = ImageEnhance.Contrast(img)
            img = contrast_enhancer.enhance(1.2)  # 20% contrast boost

            # 3. Enhance sharpness for clearer text (CPU-only)
            # Factor > 1.0 increases sharpness
            sharpness_enhancer = ImageEnhance.Sharpness(img)
            img = sharpness_enhancer.enhance(1.3)  # 30% sharpness boost

            # 4. Slight brightness adjustment if image is too dark
            # Detect average brightness and normalize if needed
            np_img = np.array(img)
            avg_brightness = np_img.mean()

            if avg_brightness < 128:  # Image is darker than mid-gray
                # Boost brightness slightly
                brightness_enhancer = ImageEnhance.Brightness(img)
                brightness_factor = 1.0 + (128 - avg_brightness) / 256 * 0.3
                img = brightness_enhancer.enhance(min(brightness_factor, 1.3))

            logger.debug(
                f"Preprocessed image: avg_brightness={avg_brightness:.1f}")

            return img

        except Exception as e:
            logger.warning(f"Preprocessing failed, using original image: {e}")
            # Fallback to original image if preprocessing fails
            return Image.open(image_path)

    async def _update_progress(self, job_id: int, progress: float, status: JobStatus, message: str = None, **kwargs):
        """Update progress and notify callbacks"""
        progress_int = int(round(progress))

        progress_update = ProgressUpdate(
            job_id=job_id,
            progress=progress_int,
            status=status,
            message=message,
            **kwargs
        )

        # Store in Redis for cross-process access
        try:
            from services.redis_status_tracker import redis_status_tracker
            if redis_status_tracker.initialized:
                await redis_status_tracker.update_progress(progress_update)
        except Exception as e:
            logger.debug(f"Redis progress update skipped: {e}")

        # Notify callbacks (for in-process tracking)
        for callback in self.progress_callbacks:
            try:
                await callback(progress_update)
            except Exception as e:
                logger.warning(f"Progress callback failed: {e}")

    async def process_pdf(self, job_id: int, db: AsyncSession) -> ProcessingStatus:
        """
        Main PDF processing with MULTI-TEMPLATE TWO-STAGE approach + semantic matching
        """
        start_time = datetime.now(timezone.utc)

        try:
            # Get job
            result = await db.execute(select(FilingJob).where(FilingJob.id == job_id))
            job = result.scalar_one_or_none()

            if not job:
                return ProcessingStatus(
                    job_id=job_id,
                    status=JobStatus.ERROR,
                    error="Job not found"
                )

            # Get all needed attributes from the job object BEFORE the loop
            job_company_name = job.company_name
            job_source_pdf_path = str(assert_upload_child(
                job.source_pdf_path, "pdfs"))
            logger.info(
                f"🚀 Starting multi-template two-stage processing for job: {job_company_name}")

            # Update status to processing
            job.status = JobStatus.PROCESSING
            await db.commit()
            await self._update_progress(job_id, 0, JobStatus.PROCESSING, "Starting multi-template processing...")

            # Open PDF only after confirming the persisted path stays under uploads/pdfs.
            doc = fitz.open(job_source_pdf_path)
            total_pages = len(doc)
            if total_pages <= 0:
                raise ValueError("PDF has no pages")
            if total_pages > settings.max_pdf_pages:
                raise ValueError(
                    f"PDF has {total_pages} pages; maximum is {settings.max_pdf_pages}"
                )

            logger.info(f"📄 Processing PDF with {total_pages} pages")
            await self._update_progress(
                job_id, 0, JobStatus.PROCESSING,
                f"Found {total_pages} pages to process",
                total_pages=total_pages
            )

            # Process all pages with multi-template two-stage approach
            total_extracted_items = 0
            total_matched_items = 0
            total_duplicate_label_count = 0
            total_duplicate_label_value_count = 0
            total_blank_statement_type_rows = 0
            total_template_backed_rows = 0
            total_suspicious_signed_value_count = 0
            total_reviewed_count = 0
            total_tagged_count = 0
            total_reviewed_or_tagged_count = 0
            failed_pages = 0

            for page_num in range(total_pages):
                try:
                    # Pass job_id (the primitive int) which is safe
                    page_stats = await self._process_page_multi_template(
                        doc, job_id, page_num, db
                    )

                    # Update progress AFTER completing the page (0-100% based on pages)
                    pages_completed = page_num + 1
                    completed_progress = int(
                        (pages_completed / total_pages) * 100)

                    await self._update_progress(
                        job_id, completed_progress, JobStatus.PROCESSING,
                        f"Completed page {pages_completed} of {total_pages}",
                        current_page=pages_completed,
                        total_pages=total_pages
                    )

                    logger.info(
                        f"📄 Page {pages_completed}/{total_pages} complete ({completed_progress}%)")

                    if page_stats['extracted'] > 0:
                        total_extracted_items += page_stats['extracted']
                        total_matched_items += page_stats['matched']
                        extraction_summary = page_stats.get(
                            'extraction_summary', {})
                        total_duplicate_label_count += extraction_summary.get(
                            'duplicate_label_count', 0)
                        total_duplicate_label_value_count += extraction_summary.get(
                            'duplicate_label_value_count', 0)
                        total_blank_statement_type_rows += extraction_summary.get(
                            'rows_with_blank_statement_type', 0)
                        total_template_backed_rows += extraction_summary.get(
                            'rows_with_template_field_id', 0)
                        total_suspicious_signed_value_count += extraction_summary.get(
                            'suspicious_signed_value_count', 0)
                        total_reviewed_count += extraction_summary.get(
                            'reviewed_count', 0)
                        total_tagged_count += extraction_summary.get(
                            'tagged_count', 0)
                        total_reviewed_or_tagged_count += extraction_summary.get(
                            'reviewed_or_tagged_count', 0)
                        await db.commit()

                        # Log with template info
                        templates_info = ", ".join([
                            f"{st} ({cnt} items)"
                            for st, cnt in page_stats.get('templates_used', {}).items()
                        ])
                        logger.info(
                            f"✅ Page {page_num + 1} complete: "
                            f"{page_stats['extracted']} items, {page_stats['matched']} matched "
                            f"(Templates: {templates_info})"
                        )
                    else:
                        logger.info(
                            f"ℹ️ Page {page_num + 1}: No valid items extracted")

                except Exception as page_error:
                    logger.error(f"❌ Failed page {page_num + 1}: {page_error}")
                    failed_pages += 1

                    try:
                        await db.rollback()
                        logger.info(
                            f"Rolled back failed page {page_num + 1}, continuing...")
                    except Exception as rollback_error:
                        logger.error(f"Rollback failed: {rollback_error}")

                    continue

                # Small delay
                await asyncio.sleep(0.1)

            # Re-fetch the job object after the loop
            await db.refresh(job)

            # Update job status
            match_rate = (total_matched_items / total_extracted_items *
                          100) if total_extracted_items > 0 else 0

            if total_extracted_items > 0:
                job.status = JobStatus.REVIEW
                status_message = (
                    f"Processing complete! Extracted {total_extracted_items} items, "
                    f"{total_matched_items} auto-matched ({match_rate:.1f}%)"
                )
                if failed_pages > 0:
                    status_message += f" ({failed_pages} pages failed)"
                final_status = JobStatus.REVIEW
            else:
                job.status = JobStatus.ERROR
                status_message = f"Processing failed - no data extracted ({failed_pages} pages failed)"
                final_status = JobStatus.ERROR

            await db.commit()

            processing_time = (datetime.now(timezone.utc) -
                               start_time).total_seconds()
            final_message = f"{status_message} in {processing_time:.1f} seconds"

            await self._update_progress(
                job_id, 100, final_status,
                final_message,
                items_extracted=total_extracted_items,
                items_matched=total_matched_items
            )

            logger.info(
                "Extraction diagnostics for job %s: total_extracted_rows=%s rows_with_template_field_id=%s rows_without_template_field_id=%s rows_with_blank_statement_type=%s duplicate_label_count=%s duplicate_label_value_count=%s suspicious_signed_value_count=%s reviewed_count=%s tagged_count=%s reviewed_or_tagged_count=%s",
                job_id,
                total_extracted_items,
                total_template_backed_rows,
                total_extracted_items - total_template_backed_rows,
                total_blank_statement_type_rows,
                total_duplicate_label_count,
                total_duplicate_label_value_count,
                total_suspicious_signed_value_count,
                total_reviewed_count,
                total_tagged_count,
                total_reviewed_or_tagged_count,
            )

            logger.info(
                f"🎉 Completed processing: {job_company_name} - {final_message}")

            return ProcessingStatus(
                job_id=job_id,
                status=final_status,
                progress=100,
                message=final_message,
                started_at=start_time,
                updated_at=datetime.now(timezone.utc)
            )

        except Exception as e:
            logger.error(f"❌ Error processing PDF for job {job_id}: {e}")
            import traceback
            traceback.print_exc()

            try:
                result = await db.execute(select(FilingJob).where(FilingJob.id == job_id))
                job_to_update = result.scalar_one_or_none()
                if job_to_update:
                    job_to_update.status = JobStatus.ERROR
                    await db.commit()
            except Exception as status_update_error:
                logger.error(
                    f"Failed to update job status: {status_update_error}")

            await self._update_progress(job_id, 0, JobStatus.ERROR, f"Processing failed: {str(e)}")

            return ProcessingStatus(
                job_id=job_id,
                status=JobStatus.ERROR,
                error=str(e),
                started_at=start_time,
                updated_at=datetime.now(timezone.utc)
            )
        finally:
            if 'doc' in locals():
                doc.close()

    async def _process_page_multi_template(
        self,
        doc: fitz.Document,
        job_id: int,
        page_num: int,
        db: AsyncSession
    ) -> Dict[str, int]:
        """
        Process single page with MULTI-TEMPLATE TWO-STAGE + SEMANTIC MATCHING

        Stage 1: Classify ALL statement types on page
        Stage 2: Extract data with MULTIPLE template guidance
        Stage 3: Semantic matching for unmatched items
        """
        try:
            page = doc.load_page(page_num)
            page_blocks = self._extract_layout_blocks(page)
            native_text = self._extract_page_text(page)
            image_path = self._get_page_image_path(
                job_id=job_id, page_num=page_num)
            image_base64 = None

            # Create page record
            page_obj = FinancialStatementPage(
                job_id=job_id,
                page_number=page_num + 1,
                image_path=image_path
            )
            db.add(page_obj)
            await db.flush()

            page_quality = self._score_page_quality(
                native_text=native_text
            )
            extraction_text = native_text
            extraction_source = 'native_pdf'

            # ===== STAGE 1: CLASSIFY ALL STATEMENT TYPES =====
            logger.info(
                f"🔍 Stage 1: Classifying page {page_num + 1} (multi-template)...")
            classifications = self._classify_from_page_text(
                extraction_text,
                page_blocks=page_blocks
            )

            if classifications:
                logger.info(
                    f"Using {extraction_source} text classification for page {page_num + 1}: "
                    f"{', '.join(c['code'] for c in classifications)}"
                )
            else:
                image_path, image_base64 = self._ensure_page_image(
                    page=page,
                    job_id=job_id,
                    page_num=page_num,
                    native_text=native_text
                )
                classifications = await statement_classifier.classify_page(
                    image_base64=image_base64,
                    page_number=page_num + 1,
                    page_context=extraction_text
                )

            if not classifications or len(classifications) == 0:
                logger.warning(
                    f"⚠️ No classifications found for page {page_num + 1}")
                return {'extracted': 0, 'matched': 0, 'templates_used': {}}

            # Filter out low-confidence classifications
            valid_classifications = [
                c for c in classifications
                if c['confidence'] >= 0.5
            ]
            valid_classifications = self._enrich_classifications_with_layout(
                valid_classifications,
                page_blocks=page_blocks
            )

            if not valid_classifications:
                logger.warning(
                    f"⚠️ All classifications below confidence threshold for page {page_num + 1}"
                )
                return {'extracted': 0, 'matched': 0, 'templates_used': {}}

            # ===== STAGE 2: EXTRACT WITH MULTIPLE TEMPLATES =====
            logger.info(
                f"📊 Stage 2: Extracting from page {page_num + 1} "
                f"using {len(valid_classifications)} template(s)..."
            )

            # Load ALL templates for this page
            xbrl_service = get_xbrl_template_service()
            templates = []
            statement_codes = []
            section_locations = []

            for cls in valid_classifications:
                template = xbrl_service.get_template(cls['code'])
                if template:
                    templates.append(template)
                    statement_codes.append(cls['code'])
                    section_locations.append(cls['section_location'])
                else:
                    logger.warning(
                        f"⚠️ Template not found for code: {cls['code']}")

            if not templates:
                logger.error(
                    f"❌ No valid templates found for page {page_num + 1}")
                return {'extracted': 0, 'matched': 0, 'templates_used': {}}

            # Build multi-template extraction prompt
            extraction_prompt = stage2_prompt_builder.build_multi_template_extraction_prompt(
                templates=templates,
                statement_codes=statement_codes,
                section_locations=section_locations,
                page_context=extraction_text
            )

            # Log the full extraction prompt
            logger.info("="*80)
            logger.info("STAGE 2 EXTRACTION PROMPT (sent to LLM):")
            logger.info("="*80)
            logger.info(extraction_prompt)
            logger.info("="*80)
            logger.info(f"Templates: {statement_codes}")
            logger.info(f"Locations: {section_locations}")
            logger.info("="*80)

            ai_response = None
            text_route_allowed = (
                len(extraction_text) >= settings.extraction_text_min_chars
                and page_quality['text_route_score'] >= settings.page_quality_min_text_score
                and not page_quality['force_vlm']
            )

            if text_route_allowed:
                ai_response = await self._call_text_extraction_model(
                    extraction_prompt=extraction_prompt,
                    source_text=extraction_text,
                    source_name=extraction_source
                )
                if ai_response is not None and not self._response_has_items(ai_response):
                    logger.info(
                        f"Text extraction returned valid JSON but zero items for page {page_num + 1}; "
                        "continuing to VLM fallback"
                    )
                    ai_response = None

            if not self._response_has_items(ai_response):
                if settings.region_vlm_enabled:
                    image_path, image_base64 = self._ensure_page_image(
                        page=page,
                        job_id=job_id,
                        page_num=page_num,
                        native_text=native_text
                    )
                    ai_response = await self._call_region_vlm_extraction(
                        image_path=image_path,
                        classifications=valid_classifications,
                        xbrl_service=xbrl_service,
                        page_context=extraction_text
                    )

                if not self._response_has_items(ai_response):
                    image_path, image_base64 = self._ensure_page_image(
                        page=page,
                        job_id=job_id,
                        page_num=page_num,
                        native_text=native_text
                    )
                    logger.info(
                        f"Falling back to whole-page VLM extraction for page {page_num + 1} "
                        f"(source={extraction_source}, text_score={page_quality['text_route_score']:.2f})"
                    )
                    ai_response = await self._call_ai_model_with_prompt(
                        image_base64,
                        extraction_prompt
                    )

            if not self._response_has_items(ai_response):
                logger.warning(f"⚠️ No AI response for page {page_num + 1}")
                return {'extracted': 0, 'matched': 0, 'templates_used': {}}

            # Parse extracted items
            extracted_items = ai_response.get('items', [])

            if not extracted_items:
                logger.warning(
                    f"⚠️ No items extracted from page {page_num + 1}")
                return {'extracted': 0, 'matched': 0, 'templates_used': {}}

            # ===== STAGE 3: SEMANTIC MATCHING FOR FIELD MAPPING =====
            logger.info(
                f"🔗 Stage 3: Semantic matching for {len(extracted_items)} items...")

            matched_count = 0
            items_to_create = []
            templates_used = {}  # Track which templates had items

            for item in extracted_items:
                # Validate and clean item
                cleaned_item = self._validate_and_clean_financial_item(item)
                if not cleaned_item:
                    continue

                # Get template code from item (assigned by VLM)
                raw_template_code = item.get(
                    'template_code', statement_codes[0])  # Default to first
                section_location = item.get('section_location', 'unknown')

                # Normalize template code (VLM sometimes hallucinates names instead of codes)
                template_code = self._normalize_template_code(
                    raw_template_code, statement_codes)

                # Track template usage
                templates_used[template_code] = templates_used.get(
                    template_code, 0) + 1

                # Get corresponding template
                template = None
                for t, code in zip(templates, statement_codes):
                    if code == template_code:
                        template = t
                        break

                if not template:
                    logger.warning(
                        f"⚠️ Template {template_code} (raw: {raw_template_code}) not found for item, using fallback")
                    template = templates[0]  # Fallback to first template
                    template_code = statement_codes[0]

                concept_id = str(item.get('concept_id', '')).strip()
                match_result = self._match_from_llm_concept(
                    concept_id=concept_id,
                    extracted_label=cleaned_item['label'],
                    statement_code=template_code,
                    template=template
                )

                if not match_result.get('matched'):
                    cache_key = (
                        template_code, cleaned_item['label'].strip().lower())
                    cached_match = self._semantic_match_cache.get(cache_key)

                    if cached_match is not None:
                        match_result = cached_match
                    else:
                        match_result = await self._semantic_match_to_template_field(
                            extracted_label=cleaned_item['label'],
                            statement_code=template_code,
                            template=template,
                            db=db
                        )
                        self._semantic_match_cache[cache_key] = match_result

                # Create ExtractedDataItem
                extracted_data_item = self._create_extracted_data_item(
                    page_id=page_obj.id,
                    cleaned_item=cleaned_item,
                    template=template,
                    statement_code=template_code,
                )

                # Apply match if found
                if match_result.get('matched'):
                    extracted_data_item.template_field_id = match_result['field_id']
                    extracted_data_item.is_reviewed = match_result.get(
                        'confidence') == 'high'
                    matched_count += 1

                    logger.debug(
                        f"✅ Matched [{template_code}]: '{cleaned_item['label'][:50]}' → {match_result['matched_label']} "
                        f"(confidence: {match_result.get('confidence')}, score: {match_result.get('score', 0):.2f})"
                    )

                items_to_create.append(extracted_data_item)

            # Save all items in batches
            validation_warnings_count = 0
            extraction_summary = {
                'total_extracted_rows': 0,
                'rows_with_template_field_id': 0,
                'rows_without_template_field_id': 0,
                'rows_with_blank_statement_type': 0,
                'duplicate_label_count': 0,
                'duplicate_label_value_count': 0,
                'duplicate_label_candidates': [],
                'duplicate_label_value_candidates': [],
                'suspicious_signed_value_count': 0,
                'reviewed_count': 0,
                'tagged_count': 0,
                'reviewed_or_tagged_count': 0,
            }
            if items_to_create:
                batch_size = 10
                for i in range(0, len(items_to_create), batch_size):
                    batch = items_to_create[i:i + batch_size]
                    db.add_all(batch)
                    await db.flush()

                # ===== STAGE 4: CALCULATION VALIDATION =====
                logger.info(
                    f"🧮 Stage 4: Validating calculations for {len(items_to_create)} items...")

                extraction_summary = self._log_extraction_quality_summary(
                    job_id=job_id,
                    page_num=page_num,
                    items=items_to_create,
                    matched_count=matched_count,
                    validation_warnings_count=validation_warnings_count,
                    templates_used_count=len(templates_used),
                )

                # Group items by statement type for validation
                items_by_statement = {}
                for item in items_to_create:
                    stmt_type = item.statement_type or 'Unknown'
                    if stmt_type not in items_by_statement:
                        items_by_statement[stmt_type] = []
                    items_by_statement[stmt_type].append({
                        'label': item.extracted_label,
                        'value': item.extracted_value,
                        'item_obj': item
                    })

                # Validate each statement type
                for stmt_type, stmt_items in items_by_statement.items():
                    validation_result = calculation_validator.validate_extracted_items(
                        items=stmt_items,
                        statement_type=stmt_type
                    )

                    if validation_result['warnings']:
                        validation_warnings_count += len(
                            validation_result['warnings'])
                        logger.warning(
                            f"⚠️ Calculation warnings for {stmt_type}: "
                            f"{len(validation_result['warnings'])} issues found"
                        )

                        # Apply warnings to specific items
                        for label, warnings_list in validation_result['item_warnings'].items():
                            for stmt_item in stmt_items:
                                if stmt_item['label'] == label:
                                    item_obj = stmt_item['item_obj']
                                    item_obj.validation_warnings = json.dumps(
                                        warnings_list)
                                    item_obj.has_calculation_warning = True
                                    logger.debug(
                                        f"⚠️ Added warning to: {label[:50]}...")
                                    break
                    elif validation_result['validated_count'] > 0:
                        logger.info(
                            f"✅ Validation passed for {stmt_type}: "
                            f"{validation_result['validated_count']} calculations verified"
                        )

                # Commit validation updates
                await db.flush()

                logger.info(
                    f"✅ Page {page_num + 1} complete: {len(items_to_create)} items created, "
                    f"{matched_count} matched ({matched_count/len(items_to_create)*100:.1f}%), "
                    f"using {len(templates_used)} template(s), "
                    f"{validation_warnings_count} calculation warnings, "
                    f"{extraction_summary['duplicate_label_count']} duplicate-label excess rows, "
                    f"{extraction_summary['duplicate_label_value_count']} duplicate label+value excess rows"
                )

            return {
                'extracted': len(items_to_create),
                'matched': matched_count,
                'templates_used': templates_used,
                'validation_warnings': validation_warnings_count,
                'extraction_summary': extraction_summary,
            }

        except Exception as e:
            logger.error(
                f"❌ Error in multi-template processing for page {page_num + 1}: {e}")
            import traceback
            traceback.print_exc()
            raise

    def _get_page_image_path(self, job_id: int, page_num: int) -> str:
        """Build the canonical path for a rendered page image."""
        image_filename = f"job_{job_id}_page_{page_num + 1}.png"
        return os.path.join(settings.upload_directory, "pages", image_filename)

    def _get_render_dpi(self, native_text: str) -> int:
        """Choose a cheaper DPI for text-rich pages and full DPI for harder pages."""
        if len(native_text) >= settings.pdf_text_fast_path_min_chars:
            return settings.pdf_render_dpi_text_fast_path
        return settings.pdf_render_dpi

    def _ensure_page_image(
        self,
        page: fitz.Page,
        job_id: int,
        page_num: int,
        native_text: str
    ) -> Tuple[str, str]:
        """Render a page image only when a VLM path actually needs it."""
        image_path = self._get_page_image_path(
            job_id=job_id, page_num=page_num)
        if os.path.exists(image_path):
            return image_path, self._image_file_to_base64(image_path)

        dpi = self._get_render_dpi(native_text)
        return self._render_page_image(
            page=page,
            job_id=job_id,
            page_num=page_num,
            dpi=dpi
        )

    def _image_file_to_base64(self, image_path: str) -> str:
        """Load a saved page image and convert it into the VLM-friendly base64 payload."""
        from PIL import Image
        import io

        image_path = str(resolve_upload_path(image_path, "pages"))
        img = self._preprocess_image_for_vlm(image_path)
        max_dimension = 2048
        if img.width > max_dimension or img.height > max_dimension:
            original_size = (img.width, img.height)
            ratio = min(max_dimension / img.width, max_dimension / img.height)
            new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
            logger.debug(
                f"Resized existing page image from {original_size} to {new_size} for downstream extraction"
            )

        if img.mode != 'RGB':
            img = img.convert('RGB')

        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG', optimize=True)
        img_byte_arr.seek(0)
        return base64.b64encode(img_byte_arr.read()).decode("utf-8")

    def ensure_page_image_for_job(
        self,
        source_pdf_path: str,
        job_id: int,
        page_number: int
    ) -> str:
        """Create a page image on demand for review screens if it doesn't exist yet."""
        page_num = page_number - 1
        if page_num < 0:
            raise ValueError("page_number must be 1 or greater")

        source_pdf_path = str(assert_upload_child(source_pdf_path, "pdfs"))
        image_path = self._get_page_image_path(
            job_id=job_id, page_num=page_num)
        if os.path.exists(image_path):
            return image_path

        doc = fitz.open(source_pdf_path)
        try:
            total_pages = len(doc)
            if total_pages <= 0:
                raise ValueError("PDF has no pages")
            if total_pages > settings.max_pdf_pages:
                raise ValueError(
                    f"PDF has {total_pages} pages; maximum is {settings.max_pdf_pages}"
                )
            if page_num >= len(doc):
                raise IndexError("page_number out of range")

            page = doc.load_page(page_num)
            native_text = self._extract_page_text(page)
            rendered_path, _ = self._ensure_page_image(
                page=page,
                job_id=job_id,
                page_num=page_num,
                native_text=native_text
            )
            return rendered_path
        finally:
            doc.close()

    def _render_page_image(
        self,
        page: fitz.Page,
        job_id: int,
        page_num: int,
        dpi: int
    ) -> Tuple[str, str]:
        """Render a page image once and return the saved path plus base64 content."""
        zoom = dpi / 72
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)

        image_path = self._get_page_image_path(
            job_id=job_id, page_num=page_num)
        os.makedirs(os.path.dirname(image_path), exist_ok=True)
        pix.save(image_path)
        return image_path, self._image_file_to_base64(image_path)

    def _clean_extracted_text_line(self, text: str) -> str:
        """Normalize spacing inside a line while preserving overall page layout."""
        text = str(text or "").replace("\xa0", " ")
        return re.sub(r"[ \t]+", " ", text).strip()

    def _rects_overlap(
        self,
        rect_a: Tuple[float, float, float, float],
        rect_b: Tuple[float, float, float, float]
    ) -> bool:
        """Check whether two PDF rectangles overlap."""
        ax0, ay0, ax1, ay1 = rect_a
        bx0, by0, bx1, by1 = rect_b
        return not (ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0)

    def _extract_layout_blocks(self, page: fitz.Page) -> List[Dict[str, Any]]:
        """Extract text blocks with normalized coordinates for layout-aware routing."""
        try:
            blocks = page.get_text("blocks", sort=True) or []
        except TypeError:
            blocks = page.get_text("blocks") or []

        page_rect = page.rect
        page_width = max(float(page_rect.width), 1.0)
        page_height = max(float(page_rect.height), 1.0)

        layout_blocks: List[Dict[str, Any]] = []
        sorted_blocks = sorted(blocks, key=lambda block: (
            float(block[1]), float(block[0])))

        for block in sorted_blocks:
            if len(block) < 5:
                continue

            x0, y0, x1, y1, block_text = block[:5]
            block_type = block[6] if len(block) > 6 else 0
            if block_type not in (0, None):
                continue

            lines = []
            for raw_line in str(block_text).splitlines():
                cleaned_line = self._clean_extracted_text_line(raw_line)
                if cleaned_line:
                    lines.append(cleaned_line)

            if not lines:
                continue

            text = "\n".join(lines)
            bbox = (float(x0), float(y0), float(x1), float(y1))
            bbox_ratio = (
                float(x0) / page_width,
                float(y0) / page_height,
                float(x1) / page_width,
                float(y1) / page_height,
            )

            layout_blocks.append({
                'text': text,
                'normalized': text.lower(),
                'bbox': bbox,
                'bbox_ratio': bbox_ratio,
                'center_x_ratio': (bbox_ratio[0] + bbox_ratio[2]) / 2,
                'center_y_ratio': (bbox_ratio[1] + bbox_ratio[3]) / 2,
            })

        return layout_blocks

    def _extract_table_text(
        self,
        page: fitz.Page
    ) -> Tuple[List[str], List[Tuple[float, float, float, float]]]:
        """Extract table rows into a text form that preserves column relationships."""
        find_tables = getattr(page, "find_tables", None)
        if not callable(find_tables):
            return [], []

        try:
            table_finder = find_tables()
        except Exception as e:
            logger.debug(f"Table detection failed: {e}")
            return [], []

        raw_tables = getattr(table_finder, "tables", table_finder) or []
        table_sections: List[str] = []
        table_rects: List[Tuple[float, float, float, float]] = []

        for index, table in enumerate(raw_tables, 1):
            try:
                rows = table.extract()
            except Exception as e:
                logger.debug(f"Table extraction failed for table {index}: {e}")
                continue

            if not rows:
                continue

            table_lines = [f"[TABLE {index}]"]
            populated_rows = 0

            for row in rows:
                if not row:
                    continue

                cleaned_cells = [
                    self._clean_extracted_text_line(cell) for cell in row]
                if not any(cleaned_cells):
                    continue

                table_lines.append(" | ".join(cleaned_cells))
                populated_rows += 1

            if populated_rows == 0:
                continue

            table_sections.append("\n".join(table_lines))

            bbox = getattr(table, "bbox", None)
            if bbox and len(bbox) == 4:
                table_rects.append(tuple(float(value) for value in bbox))

        return table_sections, table_rects

    def _extract_block_text(
        self,
        page: fitz.Page,
        skip_rects: Optional[List[Tuple[float, float, float, float]]] = None
    ) -> List[str]:
        """Extract text blocks in reading order while keeping paragraph breaks."""
        block_sections: List[str] = []

        for block in self._extract_layout_blocks(page):
            if skip_rects and any(self._rects_overlap(block['bbox'], skip_rect) for skip_rect in skip_rects):
                continue

            block_sections.append(block['text'])

        return block_sections

    def _extract_word_text(self, page: fitz.Page) -> List[str]:
        """Fallback extractor that rebuilds lines from positioned words."""
        try:
            words = page.get_text("words", sort=True) or []
        except TypeError:
            words = page.get_text("words") or []

        words = sorted(words, key=lambda word: (
            float(word[1]), float(word[0])))
        lines: List[str] = []
        current_words: List[str] = []
        current_y: Optional[float] = None
        current_block = None
        current_line = None

        for word in words:
            if len(word) < 5:
                continue

            x0, y0, _, _, text = word[:5]
            block_no = word[5] if len(word) > 5 else None
            line_no = word[6] if len(word) > 6 else None

            if current_y is None:
                current_y = float(y0)
                current_block = block_no
                current_line = line_no
                current_words = [str(text)]
                continue

            same_line = (
                block_no == current_block and line_no == current_line
                if current_block is not None and current_line is not None
                and block_no is not None and line_no is not None
                else abs(float(y0) - current_y) <= 3
            )

            if same_line:
                current_words.append(str(text))
                continue

            cleaned_line = self._clean_extracted_text_line(
                " ".join(current_words))
            if cleaned_line:
                lines.append(cleaned_line)

            current_y = float(y0)
            current_block = block_no
            current_line = line_no
            current_words = [str(text)]

        if current_words:
            cleaned_line = self._clean_extracted_text_line(
                " ".join(current_words))
            if cleaned_line:
                lines.append(cleaned_line)

        return lines

    def _extract_page_text(self, page: fitz.Page) -> str:
        """Extract native PDF text with tables, blocks, and lines preserved as much as possible."""
        table_sections, table_rects = self._extract_table_text(page)
        block_sections = self._extract_block_text(page, skip_rects=table_rects)

        structured_parts: List[str] = []
        if table_sections:
            structured_parts.append("\n\n".join(table_sections))
        if block_sections:
            structured_parts.append("\n\n".join(block_sections))

        text = "\n\n".join(part for part in structured_parts if part).strip()

        if not text:
            text = "\n".join(self._extract_word_text(page)).strip()

        if not text:
            fallback_lines = []
            fallback_text = page.get_text("text") or ""
            for raw_line in fallback_text.splitlines():
                cleaned_line = self._clean_extracted_text_line(raw_line)
                if cleaned_line:
                    fallback_lines.append(cleaned_line)
            text = "\n".join(fallback_lines)

        return text[:settings.pdf_text_context_chars]

    def _score_page_quality(
        self,
        native_text: str
    ) -> Dict[str, float]:
        """Estimate whether a page is text-friendly or should go straight to VLM."""
        native_chars = len(native_text)

        native_score = min(1.0, native_chars /
                           max(settings.pdf_text_fast_path_min_chars, 1))
        text_route_score = native_score
        force_vlm = (
            native_score < 0.15
            and text_route_score < settings.page_quality_force_vlm_score
        )

        return {
            'native_text_score': native_score,
            'text_route_score': text_route_score,
            'force_vlm': force_vlm
        }

    def _get_text_classification_profiles(self) -> Dict[str, Dict[str, Any]]:
        """Patterns for heading and continuation-aware text classification."""
        return {
            '210000': {'min_score': 3.0, 'patterns': [
                (r"\bstatement of financial position\b", 6.0,
                 "statement of financial position heading"),
                (r"\bbalance sheet\b", 5.5, "balance sheet heading"),
                (r"\b(?:non-current|current) assets\b", 1.8, "assets section cue"),
                (r"\b(?:non-current|current) liabilities\b",
                 1.8, "liabilities section cue"),
                (r"\bequity and liabilities\b", 2.6,
                 "equity and liabilities section"),
                (r"\btotal assets\b", 1.5, "total assets line"),
                (r"\btotal equity and liabilities\b", 1.9,
                 "total equity and liabilities line"),
            ]},
            '310000': {'min_score': 3.0, 'patterns': [
                (r"\bstatement of profit or loss\b", 6.0, "profit or loss heading"),
                (r"\bstatement of income\b", 5.5, "income statement heading"),
                (r"\bincome statement\b", 5.5, "income statement heading"),
                (r"\brevenue\b", 1.4, "revenue cue"),
                (r"\bcost of sales\b", 1.8, "cost of sales cue"),
                (r"\bgross profit\b", 1.8, "gross profit cue"),
                (r"\bprofit before tax\b", 1.8, "profit before tax cue"),
                (r"\bprofit for the (?:financial )?year\b",
                 1.8, "profit for the year cue"),
            ]},
            '410000': {'min_score': 3.0, 'patterns': [
                (r"\bstatement of comprehensive income\b",
                 6.0, "comprehensive income heading"),
                (r"\bother comprehensive income\b",
                 2.4, "other comprehensive income cue"),
                (r"\btotal comprehensive income\b",
                 2.5, "total comprehensive income cue"),
            ]},
            '520000': {'min_score': 3.0, 'patterns': [
                (r"\bstatement of cash flows\b", 6.0, "cash flow heading"),
                (r"\bcash flow statement\b", 5.8, "cash flow heading"),
                (r"\bnet cash (?:generated from|from|used in) operating activities\b",
                 2.1, "operating cash flow cue"),
                (r"\bnet cash (?:generated from|from|used in) investing activities\b",
                 2.1, "investing cash flow cue"),
                (r"\bnet cash (?:generated from|from|used in) financing activities\b",
                 2.1, "financing cash flow cue"),
            ]},
            '610000': {'min_score': 3.0, 'patterns': [
                (r"\bstatement of changes in equity\b",
                 6.0, "changes in equity heading"),
                (r"\bbalance at beginning of (?:year|period)\b",
                 2.0, "opening equity balance cue"),
                (r"\bbalance at end of (?:year|period)\b",
                 2.0, "closing equity balance cue"),
                (r"\bretained earnings\b", 1.3, "retained earnings cue"),
                (r"\bshare capital\b", 1.2, "share capital cue"),
            ]},
            '620000': {'min_score': 3.0, 'patterns': [
                (r"\bstatement of retained earnings\b",
                 5.8, "retained earnings heading"),
                (r"\bretained earnings\b", 1.8, "retained earnings cue"),
                (r"\bdividends?\b", 1.2, "dividend cue"),
                (r"\bcarried forward\b", 1.2, "carried forward cue"),
            ]},
            '120000': {'min_score': 3.0, 'patterns': [
                (r"\bdirectors?(?:'s)?\s+report\b",
                 6.0, "directors report heading"),
                (r"\bprincipal activities\b", 1.5, "principal activities cue"),
                (r"\bdividends?\b", 1.3, "dividend cue"),
                (r"\breserves\b", 1.2, "reserves cue"),
                (r"\bdirectors of the company\b",
                 1.5, "directors of the company cue"),
                (r"\bsigned on behalf of the board\b", 1.5, "board signing cue"),
            ]},
            '120100': {'min_score': 3.0, 'patterns': [
                (r"\bstatement by directors\b", 6.0,
                 "statement by directors heading"),
                (r"\bin the opinion of the directors\b",
                 2.3, "directors opinion cue"),
                (r"\btrue and fair view\b", 1.8, "true and fair view cue"),
                (r"\bsigned in accordance with a resolution of the directors\b",
                 2.5, "directors resolution cue"),
            ]},
            '130000': {'min_score': 3.0, 'patterns': [
                (r"\bindependent auditors?(?:'s)?\s+report\b",
                 6.0, "independent auditors report heading"),
                (r"\bbasis for opinion\b", 1.8, "basis for opinion cue"),
                (r"\bkey audit matters\b", 1.8, "key audit matters cue"),
                (r"\bauditors?(?:'s)?\s+responsibilities for the audit\b",
                 2.1, "auditors responsibilities cue"),
            ]},
            '710000': {'min_score': 3.0, 'patterns': [
                (r"(?:note\s*)?\d+(?:\.\d+)?[\)\.\-: ]+\s*corporate information\b",
                 4.8, "corporate information note title"),
                (r"\bcorporate information\b", 5.8,
                 "corporate information heading"),
                (r"\bdate of incorporation\b", 1.6, "date of incorporation cue"),
                (r"\bregistered office\b", 1.6, "registered office cue"),
                (r"\bprincipal place of business\b",
                 1.6, "principal place of business cue"),
                (r"\bnature of business\b", 1.4, "nature of business cue"),
            ]},
            '720000': {'min_score': 3.0, 'patterns': [
                (r"(?:note\s*)?\d+(?:\.\d+)?[\)\.\-: ]+\s*(?:summary of )?significant accounting policies\b",
                 4.8, "significant accounting policies note title"),
                (r"\bsignificant accounting policies\b", 5.8,
                 "significant accounting policies heading"),
                (r"\bsummary of significant accounting policies\b",
                 5.5, "summary accounting policies heading"),
                (r"\bbasis of preparation\b", 2.0, "basis of preparation cue"),
                (r"\buse of estimates(?: and judgments)?\b",
                 1.7, "estimates and judgments cue"),
                (r"\brevenue recognition\b", 1.5, "revenue recognition cue"),
                (r"\bfinancial instruments?\b", 1.4, "financial instruments cue"),
            ]},
            '730000': {'min_score': 3.0, 'patterns': [
                (r"\bnotes to the financial statements\b", 5.8,
                 "notes to the financial statements heading"),
                (r"\bthese notes form an integral part of the financial statements\b",
                 2.1, "integral notes cue"),
            ]},
            '740000': {'min_score': 3.0, 'patterns': [
                (r"(?:note\s*)?\d+(?:\.\d+)?[\)\.\-: ]+\s*(?:issued|share) capital\b",
                 4.8, "issued capital note title"),
                (r"\bissued capital\b", 5.8, "issued capital heading"),
                (r"\bshare capital\b", 2.0, "share capital cue"),
                (r"\bordinary shares\b", 1.6, "ordinary shares cue"),
                (r"\bissued and fully paid\b", 1.8, "issued and fully paid cue"),
            ]},
            '750000': {'min_score': 3.0, 'patterns': [
                (r"(?:note\s*)?\d+(?:\.\d+)?[\)\.\-: ]+\s*related part(?:y|ies)\b",
                 4.8, "related party note title"),
                (r"\brelated party transactions?\b", 5.8,
                 "related party transactions heading"),
                (r"\bkey management personnel compensation\b",
                 2.0, "key management personnel compensation cue"),
                (r"\bcompensation of key management personnel\b",
                 2.0, "key management personnel compensation cue"),
                (r"\bbalances with related parties\b",
                 1.8, "related party balances cue"),
            ]},
        }

    def _score_pattern_matches(
        self,
        text: str,
        patterns: List[Tuple[str, float, str]]
    ) -> Tuple[float, List[str]]:
        """Score a text block against weighted regex patterns."""
        score = 0.0
        evidence: List[str] = []

        for pattern, weight, label in patterns:
            if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
                score += weight
                evidence.append(label)

        return score, evidence

    def _expand_ratio_box(
        self,
        box: Tuple[float, float, float, float],
        pad_x: float = 0.04,
        pad_y: float = 0.03
    ) -> Tuple[float, float, float, float]:
        """Expand a normalized box slightly so crops keep surrounding context."""
        x0, y0, x1, y1 = box
        return (
            max(0.0, x0 - pad_x),
            max(0.0, y0 - pad_y),
            min(1.0, x1 + pad_x),
            min(1.0, y1 + pad_y),
        )

    def _merge_ratio_boxes(
        self,
        boxes: List[Tuple[float, float, float, float]]
    ) -> Optional[Tuple[float, float, float, float]]:
        """Merge multiple normalized boxes into a single surrounding box."""
        if not boxes:
            return None

        x0 = min(box[0] for box in boxes)
        y0 = min(box[1] for box in boxes)
        x1 = max(box[2] for box in boxes)
        y1 = max(box[3] for box in boxes)
        return self._expand_ratio_box((x0, y0, x1, y1))

    def _ratio_box_overlap(
        self,
        box_a: Optional[Tuple[float, float, float, float]],
        box_b: Optional[Tuple[float, float, float, float]]
    ) -> float:
        """Calculate overlap ratio between two normalized boxes."""
        if not box_a or not box_b:
            return 0.0

        ax0, ay0, ax1, ay1 = box_a
        bx0, by0, bx1, by1 = box_b
        ix0 = max(ax0, bx0)
        iy0 = max(ay0, by0)
        ix1 = min(ax1, bx1)
        iy1 = min(ay1, by1)

        if ix1 <= ix0 or iy1 <= iy0:
            return 0.0

        intersection = (ix1 - ix0) * (iy1 - iy0)
        area_a = max((ax1 - ax0) * (ay1 - ay0), 1e-6)
        area_b = max((bx1 - bx0) * (by1 - by0), 1e-6)
        return intersection / min(area_a, area_b)

    def _infer_section_location_from_ratio_box(
        self,
        box: Optional[Tuple[float, float, float, float]]
    ) -> str:
        """Convert a normalized region box into the coarse section labels used elsewhere."""
        if not box:
            return 'full'

        x0, y0, x1, y1 = box
        width = x1 - x0
        height = y1 - y0
        center_x = (x0 + x1) / 2
        center_y = (y0 + y1) / 2

        if width >= 0.82 and height >= 0.70:
            return 'full'
        if width <= 0.42 and height >= 0.45:
            if center_x <= 0.42:
                return 'left'
            if center_x >= 0.58:
                return 'right'
        if center_y < 0.33:
            return 'top'
        if center_y < 0.67:
            return 'middle'
        return 'bottom'

    def _match_blocks_for_classification(
        self,
        code: str,
        page_blocks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Find the blocks whose text best supports a given statement classification."""
        profile = self._get_text_classification_profiles().get(code)
        if not profile:
            return []

        matches: List[Dict[str, Any]] = []
        for block in page_blocks:
            score, evidence = self._score_pattern_matches(
                block['normalized'],
                profile['patterns']
            )
            if score <= 0:
                continue

            matches.append({
                'score': score,
                'evidence': evidence,
                'block': block,
            })

        matches.sort(
            key=lambda item: (
                -item['score'],
                item['block']['center_y_ratio'],
                item['block']['center_x_ratio'],
            )
        )
        return matches

    def _build_region_box_from_matches(
        self,
        matches: List[Dict[str, Any]]
    ) -> Optional[Tuple[float, float, float, float]]:
        """Build a normalized crop box from the strongest matching text blocks."""
        if not matches:
            return None

        top_score = matches[0]['score']
        threshold = max(1.0, top_score * 0.35)
        selected_boxes = []

        for match in matches:
            if match['score'] < threshold and selected_boxes:
                continue
            selected_boxes.append(match['block']['bbox_ratio'])
            if len(selected_boxes) >= 4:
                break

        return self._merge_ratio_boxes(selected_boxes)

    def _confidence_from_score(self, score: float, has_heading: bool) -> float:
        """Map heuristic text-match scores into the classifier confidence range."""
        if has_heading:
            return min(0.97, 0.62 + (score / 12.0))
        return min(0.84, 0.40 + (score / 10.0))

    def _prune_text_classifications(self, classifications: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Drop broad note classifications when more specific note types were found."""
        codes = {classification['code'] for classification in classifications}
        specific_note_codes = {'710000', '720000', '740000', '750000'}

        if '730000' in codes and codes.intersection(specific_note_codes):
            return [
                classification
                for classification in classifications
                if classification['code'] != '730000'
            ]

        return classifications

    def _enrich_classifications_with_layout(
        self,
        classifications: List[Dict[str, Any]],
        page_blocks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Attach smarter layout regions to classifications using local text blocks."""
        if not classifications or not page_blocks:
            return classifications

        enriched: List[Dict[str, Any]] = []
        for classification in classifications:
            enriched_classification = dict(classification)
            matches = self._match_blocks_for_classification(
                classification['code'],
                page_blocks
            )
            region_box = self._build_region_box_from_matches(matches)
            if region_box:
                enriched_classification['region_box'] = region_box
                enriched_classification['section_location'] = (
                    self._infer_section_location_from_ratio_box(region_box)
                )
            enriched.append(enriched_classification)

        return enriched

    def _get_region_box(
        self,
        width: int,
        height: int,
        section_location: str,
        region_box: Optional[Tuple[float, float, float, float]] = None
    ) -> Tuple[int, int, int, int]:
        """Convert normalized region hints into pixel boxes with a coarse fallback."""
        if region_box and len(region_box) == 4:
            x0 = max(0, min(width, int(region_box[0] * width)))
            y0 = max(0, min(height, int(region_box[1] * height)))
            x1 = max(0, min(width, int(region_box[2] * width)))
            y1 = max(0, min(height, int(region_box[3] * height)))
            if x1 > x0 and y1 > y0:
                return (x0, y0, x1, y1)

        location = (section_location or 'full').lower()
        if location == 'top':
            return (0, 0, width, int(height * 0.48))
        if location == 'middle':
            return (0, int(height * 0.22), width, int(height * 0.78))
        if location == 'bottom':
            return (0, int(height * 0.52), width, height)
        if location == 'left':
            return (0, 0, int(width * 0.62), height)
        if location == 'right':
            return (int(width * 0.38), 0, width, height)
        return (0, 0, width, height)

    def _crop_region_to_base64(
        self,
        image_path: str,
        section_location: str,
        region_box: Optional[Tuple[float, float, float, float]] = None
    ) -> Optional[str]:
        """Crop a page image to a region and return base64 PNG."""
        from PIL import Image
        import io

        try:
            image_path = str(resolve_upload_path(image_path, "pages"))
            img = Image.open(image_path)
            box = self._get_region_box(
                img.width,
                img.height,
                section_location,
                region_box=region_box
            )
            cropped = img.crop(box)
            if cropped.mode != 'RGB':
                cropped = cropped.convert('RGB')
            buf = io.BytesIO()
            cropped.save(buf, format='PNG', optimize=True)
            buf.seek(0)
            return base64.b64encode(buf.read()).decode("utf-8")
        except Exception as e:
            logger.warning(f"Region crop failed for {section_location}: {e}")
            return None

    def _deduplicate_extracted_items(self, items: List[Dict]) -> List[Dict]:
        """Deduplicate region-level extraction results before mapping."""
        seen = set()
        deduped = []
        for item in items:
            key = (
                str(item.get('template_code', '')).strip(),
                str(item.get('concept_id', '')).strip(),
                str(item.get('label', '')).strip().lower(),
                str(item.get('value', '')).strip()
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _response_has_items(self, ai_response: Optional[Dict]) -> bool:
        """Treat empty-but-valid JSON responses as no extraction so fallback can continue."""
        if not isinstance(ai_response, dict):
            return False

        items = ai_response.get('items')
        return isinstance(items, list) and len(items) > 0

    async def _call_region_vlm_extraction(
        self,
        image_path: str,
        classifications: List[Dict],
        xbrl_service,
        page_context: str
    ) -> Optional[Dict]:
        """Use Qwen2.5-VL on tighter content-aware regions before escalating to whole-page VLM."""
        region_items: List[Dict] = []
        processed_regions = 0
        ordered_classifications = sorted(
            classifications,
            key=lambda classification: (
                classification.get('region_box', (0.0, 0.0, 1.0, 1.0))[1]
                if classification.get('region_box') else 0.0,
                classification.get('region_box', (0.0, 0.0, 1.0, 1.0))[0]
                if classification.get('region_box') else 0.0,
                -classification.get('confidence', 0.0),
            )
        )

        region_groups: List[Dict[str, Any]] = []
        for classification in ordered_classifications:
            template = xbrl_service.get_template(classification['code'])
            if not template:
                continue

            location = classification.get('section_location', 'full')
            region_box = classification.get('region_box')
            matched_group = None

            for group in region_groups:
                same_coarse_region = (
                    not region_box and not group.get('region_box')
                    and group['location'] == location
                )
                overlapping_region = (
                    region_box and group.get('region_box')
                    and self._ratio_box_overlap(region_box, group['region_box']) >= 0.45
                )
                if same_coarse_region or overlapping_region:
                    matched_group = group
                    break

            if matched_group is None:
                region_groups.append({
                    'templates': [template],
                    'statement_codes': [classification['code']],
                    'section_locations': [location],
                    'location': location,
                    'region_box': region_box,
                })
                continue

            matched_group['templates'].append(template)
            matched_group['statement_codes'].append(classification['code'])
            matched_group['section_locations'].append(location)
            if region_box:
                merged_box = self._merge_ratio_boxes(
                    [matched_group.get('region_box'), region_box]
                    if matched_group.get('region_box') else [region_box]
                )
                matched_group['region_box'] = merged_box
                matched_group['location'] = self._infer_section_location_from_ratio_box(
                    merged_box
                )

        for region_group in region_groups:
            if processed_regions >= settings.region_vlm_max_regions:
                break

            region_image_base64 = self._crop_region_to_base64(
                image_path,
                region_group['location'],
                region_box=region_group.get('region_box')
            )
            if not region_image_base64:
                continue

            region_prompt = stage2_prompt_builder.build_multi_template_extraction_prompt(
                templates=region_group['templates'],
                statement_codes=region_group['statement_codes'],
                section_locations=region_group['section_locations'],
                page_context=page_context
            )

            region_response = await self._call_ai_model_with_prompt(
                region_image_base64,
                region_prompt
            )
            processed_regions += 1

            if region_response and region_response.get('items'):
                region_items.extend(region_response['items'])

        if not region_items:
            return None

        return {'items': self._deduplicate_extracted_items(region_items)}

    def _classify_from_page_text(
        self,
        page_text: str,
        page_blocks: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict]:
        """Fast-path classifier using headings, continuation cues, and note-specific vocabulary."""
        normalized = page_text.lower().strip()
        if len(normalized) < 40:
            return []

        working_blocks = list(page_blocks or [])
        if not working_blocks:
            working_blocks = [{
                'text': page_text,
                'normalized': normalized,
                'bbox': (0.0, 0.0, 1.0, 1.0),
                'bbox_ratio': (0.0, 0.0, 1.0, 1.0),
                'center_x_ratio': 0.5,
                'center_y_ratio': 0.5,
            }]

        classifications: List[Dict[str, Any]] = []
        for code, profile in self._get_text_classification_profiles().items():
            matches = self._match_blocks_for_classification(
                code, working_blocks)
            if not matches:
                continue

            total_score = sum(match['score'] for match in matches[:4])
            if total_score < profile['min_score']:
                continue

            region_box = self._build_region_box_from_matches(matches)
            evidence_labels: List[str] = []
            for match in matches[:4]:
                for label in match['evidence']:
                    if label not in evidence_labels:
                        evidence_labels.append(label)

            has_heading = any(
                'heading' in label or 'title' in label for label in evidence_labels)
            reasoning_prefix = (
                "Matched heading and statement-specific text cues"
                if has_heading else
                "Matched continuation/note content cues without relying on headings"
            )
            evidence_summary = ", ".join(evidence_labels[:3])
            reasoning = reasoning_prefix if not evidence_summary else f"{reasoning_prefix}: {evidence_summary}"

            classifications.append({
                'code': code,
                'confidence': self._confidence_from_score(total_score, has_heading),
                'section_location': self._infer_section_location_from_ratio_box(region_box),
                'reasoning': reasoning,
                'region_box': region_box,
                'score': total_score,
            })

        classifications = self._prune_text_classifications(classifications)
        classifications.sort(
            key=lambda classification: (
                classification.get('region_box', (0.0, 0.0, 1.0, 1.0))[1]
                if classification.get('region_box') else 0.0,
                classification.get('region_box', (0.0, 0.0, 1.0, 1.0))[0]
                if classification.get('region_box') else 0.0,
                -classification.get('confidence', 0.0),
            )
        )

        for classification in classifications:
            classification.pop('score', None)

        return classifications

    async def _call_text_extraction_model(
        self,
        extraction_prompt: str,
        source_text: str,
        source_name: str
    ) -> Optional[Dict]:
        """Use the language model on extracted text before falling back to VLM."""
        max_retries = 2
        retry_delay = 1
        combined_prompt = (
            f"{extraction_prompt}\n\n"
            f"# EXTRACTED PAGE TEXT ({source_name}):\n"
            f"{source_text}\n\n"
            "Use only this extracted page text as the source. "
            "Return valid JSON in the required schema."
        )

        for attempt in range(max_retries):
            try:
                response = await self.text_client.chat_completion(
                    messages=[{
                        "role": "user",
                        "content": combined_prompt
                    }],
                    max_tokens=4096,
                    temperature=0.1
                )

                generated_text = response.choices[0].message.content
                extracted_data = self._extract_json_from_response(
                    generated_text)
                if extracted_data is not None:
                    logger.info(
                        f"Text extraction succeeded via {source_name} on attempt {attempt + 1}"
                    )
                    return extracted_data
            except Exception as e:
                logger.warning(
                    f"Text extraction call failed on attempt {attempt + 1}: {e}"
                )

            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
                retry_delay *= 2

        return None

    def _match_from_llm_concept(
        self,
        concept_id: str,
        extracted_label: str,
        statement_code: str,
        template: Dict
    ) -> Dict:
        """Accept a model-supplied concept_id when it belongs to the selected template."""
        if not concept_id:
            return {'matched': False}

        valid_concepts = {
            concept.get('id'): concept
            for concept in template.get('concepts', [])
            if concept.get('id')
        }
        concept_info = valid_concepts.get(concept_id)

        if not concept_info:
            return {'matched': False}

        blocked_reason = automatic_mapping_guardrail_reason(concept_id, extracted_label)
        if blocked_reason:
            logger.info(
                "Blocked LLM concept for label '%s' to %s by %s; leaving unmatched for manual review",
                extracted_label[:100],
                concept_id,
                blocked_reason,
            )
            return {
                'matched': False,
                'blocked_reason': blocked_reason,
                'blocked_concept_id': concept_id,
            }

        return {
            'matched': True,
            'field_id': concept_id,
            'statement_code': statement_code,
            'statement_type': self._get_template_statement_type(template, statement_code),
            'matched_label': concept_info.get('label', concept_id),
            'xbrl_tag': concept_id,
            'required': concept_info.get('required', False),
            'confidence': 'high',
            'score': 1.0,
            'method': 'llm_template_concept'
        }

    def _normalize_template_code(self, raw_code: str, valid_codes: List[str]) -> str:
        """
        Normalize template code from VLM response

        VLM sometimes returns names instead of numeric codes, so we need to map them back.
        If the code is already valid, return it as-is.
        Otherwise, try to find a match or return the first valid code as fallback.

        Args:
            raw_code: Template code from VLM (may be numeric like "710000" or text like "CORPORATE_INFORMATION")
            valid_codes: List of valid template codes for this page

        Returns:
            Normalized template code (one of valid_codes)
        """
        # If it's already a valid code, return it
        if raw_code in valid_codes:
            return raw_code

        # Convert to string and strip
        raw_code_str = str(raw_code).strip()

        # Try exact match (case-insensitive)
        for code in valid_codes:
            if raw_code_str.lower() == str(code).lower():
                return code

        # If raw_code is numeric but not in valid_codes, might be a typo - find closest
        if raw_code_str.isdigit():
            # Just use first valid code as fallback
            logger.warning(
                f"VLM returned unknown numeric code '{raw_code}', using {valid_codes[0]} as fallback")
            return valid_codes[0]

        # If raw_code is text (hallucinated name), try to match by statement classifier mapping
        # For example: "CORPORATE_INFORMATION" should map to 710000
        name_to_code_hints = {
            'corporate': '710000',
            'directors_report': '120000',
            'directors': '120000',
            'statement_by_directors': '120100',
            'financial_position': '210000',
            'balance_sheet': '210000',
            'profit_loss': '310000',
            'income': '310000',
            'comprehensive_income': '410000',
            'cash_flow': '520000',
            'equity': '610000',
            'accounting_policies': '720000',
            'notes': '730000',
        }

        raw_lower = raw_code_str.lower()
        for hint, suggested_code in name_to_code_hints.items():
            if hint in raw_lower and suggested_code in valid_codes:
                logger.debug(
                    f"Mapped VLM code '{raw_code}' → {suggested_code} (hint: {hint})")
                return suggested_code

        # No match found, use first valid code
        logger.warning(
            f"VLM returned unrecognized code '{raw_code}', using {valid_codes[0]} as fallback")
        return valid_codes[0]

    async def _semantic_match_to_template_field(
        self,
        extracted_label: str,
        statement_code: str,
        template: Dict,
        db: AsyncSession
    ) -> Dict:
        """
        Match extracted label to XBRL concept using hybrid semantic matching

        This method now uses XBRL concepts instead of XML template fields.
        It leverages both string matching and semantic embeddings.

        Args:
            extracted_label: Label extracted from PDF
            statement_code: Template code (e.g., '210000')
            template: XBRL template structure
            db: Database session

        Returns:
            Match result dict with concept_id, label, confidence, etc.
        """
        try:
            # Use XBRL template service's hybrid matching
            xbrl_service = get_xbrl_template_service()

            concept_id, confidence_score = await xbrl_service.find_matching_concept_hybrid(
                extracted_label=extracted_label,
                template_code=statement_code,
                db=db
            )

            if concept_id and confidence_score > 0.5:
                # Get concept info
                concept_info = xbrl_service.get_concept_info(concept_id)

                if not concept_info:
                    return {'matched': False}

                # Determine confidence level
                if confidence_score >= 0.80:
                    confidence = 'high'
                elif confidence_score >= 0.65:
                    confidence = 'medium'
                elif confidence_score >= 0.50:
                    confidence = 'low'
                else:
                    return {'matched': False}

                # Return match result
                return {
                    'matched': True,
                    # Store XBRL concept ID (e.g., "ssmt:DateOfFinancialStatements")
                    'field_id': concept_id,
                    'statement_code': statement_code,
                    'statement_type': self._get_template_statement_type(template, statement_code),
                    'matched_label': concept_info['label'],
                    'xbrl_tag': concept_id,  # Same as field_id for XBRL
                    'required': concept_info.get('required', False),
                    'confidence': confidence,
                    'score': confidence_score,
                    'method': 'xbrl_hybrid'
                }

            return {'matched': False}

        except Exception as e:
            logger.warning(
                f"XBRL semantic matching failed for '{extracted_label[:50]}...': {e}")
            import traceback
            traceback.print_exc()
            return {'matched': False}

    async def _call_ai_model_with_prompt(self, image_base64: str, prompt: str) -> Optional[Dict]:
        """Call AI model with custom prompt (same as before)"""
        max_retries = 3
        retry_delay = 1

        for attempt in range(max_retries):
            try:
                messages = [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {
                            "url": f"data:image/png;base64,{image_base64}"
                        }}
                    ]
                }]

                response = await self.vlm_client.chat_completion(
                    messages=messages,
                    max_tokens=4096,
                    temperature=0.1
                )

                generated_text = response.choices[0].message.content

                # Log the full AI response
                logger.info("="*80)
                logger.info(f"AI MODEL RESPONSE (attempt {attempt + 1}):")
                logger.info("="*80)
                logger.info(generated_text)
                logger.info("="*80)

                extracted_data = self._extract_json_from_response(
                    generated_text)

                if extracted_data is not None:
                    logger.info(
                        f"✅ AI model returned valid JSON (attempt {attempt + 1})")
                    logger.info(
                        f"Extracted {len(extracted_data.get('items', []))} items")
                    return extracted_data
                else:
                    logger.warning(
                        f"⚠️ No JSON in AI response (attempt {attempt + 1})")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    return None

            except Exception as e:
                logger.error(
                    f"Error calling AI model (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                return None

        return None

    def _validate_and_clean_financial_item(self, item: Dict) -> Optional[Dict]:
        """Validate and clean a financial item (same as before)"""
        if not isinstance(item, dict):
            return None

        label = item.get('label')
        value = item.get('value')

        label_str = "" if label is None else str(label).strip()
        value_str = "" if value is None else str(value).strip()

        if not label_str:
            return None

        year_raw = item.get('year')
        year = None

        if year_raw is not None:
            if isinstance(year_raw, int):
                if 2000 <= year_raw <= 2100:
                    year = year_raw
            else:
                year = self._extract_year_from_value(year_raw)

        return {
            'label': label_str[:1000],
            'value': value_str[:5000],
            'year': year
        }

    def _extract_year_from_value(self, value: str) -> Optional[int]:
        """Extract 4-digit year from string (same as before)"""
        if not value:
            return None

        year_pattern = r'\b(20\d{2})\b'
        match = re.search(year_pattern, str(value))

        if match:
            year = int(match.group(1))
            if 2000 <= year <= 2100:
                return year

        try:
            year_candidate = int(str(value).strip())
            if 2000 <= year_candidate <= 2100:
                return year_candidate
        except (ValueError, TypeError):
            pass

        return None

    def _extract_json_from_response(self, text: str) -> Optional[Dict]:
        """Extract JSON from AI response (same as before)"""
        raw_text = str(text or "").strip()
        if raw_text:
            try:
                parsed = json.loads(raw_text)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

        patterns = [
            r'```json\s*(\{.*?\})\s*```',
            r'```\s*(\{.*?\})\s*```',
            r'(\{[^{}]*\{[^{}]*\}[^{}]*\})',
            r'(\{[^{}]*\})'
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                json_str = match.group(1)
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    json_str_cleaned = re.sub(r',\s*([\}\]])', r'\1', json_str)
                    json_str_cleaned = re.sub(
                        r'([{,]\s*)(\w+):', r'\1"\2":', json_str_cleaned)
                    try:
                        return json.loads(json_str_cleaned)
                    except json.JSONDecodeError:
                        continue

        logger.warning(
            f"Failed to extract JSON from response: {text[:200]}...")
        return None


# Global instance
smart_ai_processor = SmartAIProcessor()

# Status tracker (keeping existing implementation)


class ProcessingStatusTracker:
    """Track processing status with real-time updates"""

    def __init__(self):
        self._status_cache = {}
        self._progress_callbacks = []

    def add_progress_callback(self, callback):
        self._progress_callbacks.append(callback)

    async def update_progress(self, progress_update: ProgressUpdate):
        job_id = progress_update.job_id

        status = ProcessingStatus(
            job_id=job_id,
            status=progress_update.status,
            progress=progress_update.progress,
            message=progress_update.message,
            updated_at=datetime.now(timezone.utc)
        )
        self._status_cache[job_id] = status

        for callback in self._progress_callbacks:
            try:
                await callback(progress_update)
            except Exception as e:
                logger.warning(f"Progress callback failed: {e}")

    async def get_status(self, job_id: int, db: AsyncSession) -> ProcessingStatus:
        # Try Redis first
        try:
            from services.redis_status_tracker import redis_status_tracker
            if redis_status_tracker.initialized:
                redis_status = await redis_status_tracker.get_status(job_id)
                if redis_status:
                    return redis_status
        except Exception as e:
            logger.debug(f"Redis status lookup failed: {e}")

        # Fall back to cache
        if job_id in self._status_cache:
            cached_status = self._status_cache[job_id]
            if (datetime.now(timezone.utc) - (cached_status.updated_at or datetime.now(timezone.utc))).total_seconds() < 30:
                return cached_status

        # Fetch from database
        result = await db.execute(select(FilingJob).where(FilingJob.id == job_id))
        job = result.scalar_one_or_none()

        if not job:
            return ProcessingStatus(
                job_id=job_id,
                status=JobStatus.ERROR,
                progress=0,
                error="Job not found"
            )

        if job.status == 'PROCESSING':
            progress = 5
            message = "Processing started..."
        elif job.status == 'REVIEW':
            progress = 100
            message = "Ready for review"
        elif job.status == 'COMPLETED':
            progress = 100
            message = "Completed"
        elif job.status == 'ERROR':
            progress = 0
            message = "Processing failed"
        else:
            progress = 0
            message = f"Job is {job.status.lower()}"

        status = ProcessingStatus(
            job_id=job_id,
            status=JobStatus(job.status),
            progress=progress,
            message=message,
            updated_at=datetime.now(timezone.utc)
        )

        self._status_cache[job_id] = status
        return status

    def clear_status(self, job_id: int):
        self._status_cache.pop(job_id, None)

    def get_all_processing_jobs(self) -> List[ProcessingStatus]:
        return [
            status for status in self._status_cache.values()
            if status.status == JobStatus.PROCESSING
        ]


# Global tracker
status_tracker = ProcessingStatusTracker()

# Connect progress tracking
smart_ai_processor.add_progress_callback(status_tracker.update_progress)


# Background task wrapper
async def process_pdf_background(job_id: int) -> None:
    """Background task wrapper for PDF processing"""
    db: AsyncSession = None
    try:
        from database import get_db
        async for session in get_db():
            db = session
            logger.info(f"Starting background processing for job {job_id}")
            status = await smart_ai_processor.process_pdf(job_id, db)
            logger.info(
                f"Background processing completed for job {job_id}: {status.status}")

            await status_tracker.update_progress(ProgressUpdate(
                job_id=job_id,
                progress=100 if status.status == JobStatus.REVIEW else 0,
                status=status.status,
                message=status.message or f"Processing {status.status.value.lower()}"
            ))
            break

    except Exception as e:
        logger.error(f"Background processing failed for job {job_id}: {e}")

        await status_tracker.update_progress(ProgressUpdate(
            job_id=job_id,
            progress=0,
            status=JobStatus.ERROR,
            message=f"Processing failed: {str(e)}"
        ))

        if db:
            try:
                result = await db.execute(select(FilingJob).where(FilingJob.id == job_id))
                job = result.scalar_one_or_none()
                if job:
                    job.status = JobStatus.ERROR
                    await db.commit()
            except Exception as db_error:
                logger.error(
                    f"Could not update job {job_id} status to ERROR: {db_error}")
