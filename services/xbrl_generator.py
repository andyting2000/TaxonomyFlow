# services/xbrl_generator.py
import os
import re
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from lxml import etree
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import ExtractedDataItem, FilingJob, FinancialStatementPage
from file_safety import safe_filename_component
from schemas import XBRLGenerationResponse
from services.xbrl_template_service import automatic_mapping_guardrail_reason

import logging

logger = logging.getLogger(__name__)


class XBRLGenerator:
    """Generate MBRS FS-MPERS XBRL instance documents."""

    def __init__(self):
        self.nsmap = {
            "xbrli": "http://www.xbrl.org/2003/instance",
            "link": "http://www.xbrl.org/2003/linkbase",
            "xlink": "http://www.w3.org/1999/xlink",
            "iso4217": "http://www.xbrl.org/2003/iso4217",
            "xbrldi": "http://xbrl.org/2006/xbrldi",
            "ifrs-smes": "https://xbrl.ifrs.org/taxonomy/2022-03-24/ifrs-smes",
            "ssmt-dei": "http://xbrl.ssm.com.my/taxonomy/2022-12-31/ssmt-dei-core",
            "ssmt-dei-ee-mpers": "http://xbrl.ssm.com.my/taxonomy/2022-12-31/ssmt-dei-ee-mpers",
            "ssmt": "http://xbrl.ssm.com.my/taxonomy/2022-12-31/ssmt-cor",
            "ssmt-mpers": "http://xbrl.ssm.com.my/taxonomy/2022-12-31/ssmt-mpers-cor",
            "ssmt-mfrs": "http://xbrl.ssm.com.my/taxonomy/2022-12-31/ssmt-mfrs-cor",
        }

    async def generate_xbrl(
        self,
        job_id: int,
        db: AsyncSession,
        include_unreviewed: bool = False,
    ) -> XBRLGenerationResponse:
        try:
            job, items = await self._load_job_data(job_id, db, include_unreviewed)

            if not job:
                return XBRLGenerationResponse(success=False, error="Filing job not found")

            if not items:
                return XBRLGenerationResponse(success=False, error="No reviewed items with mappable tags found")

            grouped_items = self._group_items_by_statement_and_year(items)
            xbrl_content = self._create_xbrl_document(job, grouped_items)

            filename = self._generate_filename(job)
            file_path = self._save_xbrl_file(filename, xbrl_content)

            logger.info("Generated XBRL file for job %s: %s", job_id, filename)
            return XBRLGenerationResponse(
                success=True,
                file_path=file_path,
                content=xbrl_content.decode("utf-8"),
            )
        except Exception as e:
            logger.error("Error generating XBRL for job %s: %s",
                         job_id, e, exc_info=True)
            return XBRLGenerationResponse(success=False, error=str(e))

    async def _load_job_data(
        self,
        job_id: int,
        db: AsyncSession,
        include_unreviewed: bool,
    ) -> Tuple[Optional[FilingJob], List[ExtractedDataItem]]:
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
            return None, []

        reviewed_items: List[ExtractedDataItem] = []
        for page in job.pages:
            for item in page.extracted_items:
                # Accept either taxonomy-confirmed tag OR template concept qname.
                if include_unreviewed or (
                    item.is_reviewed and (
                        item.confirmed_tag or item.template_field_id)
                ):
                    reviewed_items.append(item)

        return job, reviewed_items

    def _group_items_by_statement_and_year(
        self, items: List[ExtractedDataItem]
    ) -> Dict[str, Dict[int, List[ExtractedDataItem]]]:
        grouped: Dict[str, Dict[int, List[ExtractedDataItem]]] = {}

        for item in items:
            if not item.confirmed_tag and not item.template_field_id:
                continue

            statement = item.statement_type or "General"
            grouped.setdefault(statement, {})

            if item.financial_year:
                grouped[statement].setdefault(
                    item.financial_year, []).append(item)

            if item.value_previous_year and item.financial_year_previous:
                prev_item = type(
                    "obj",
                    (object,),
                    {
                        "extracted_label": item.extracted_label,
                        "extracted_value": item.value_previous_year,
                        "confirmed_tag": item.confirmed_tag,
                        "template_field_id": item.template_field_id,
                        "financial_year": item.financial_year_previous,
                        "statement_type": item.statement_type,
                    },
                )()
                grouped[statement].setdefault(
                    item.financial_year_previous, []).append(prev_item)

        return grouped

    def _create_xbrl_document(
        self,
        job: FilingJob,
        grouped_items: Dict[str, Dict[int, List[ExtractedDataItem]]],
    ) -> bytes:
        root = etree.Element(
            f"{{{self.nsmap['xbrli']}}}xbrl",
            nsmap=self.nsmap,
            id="MBRS_Preparation_Tool_2.2",
        )

        self._add_schema_ref(root)
        contexts = self._add_comprehensive_contexts(root, job)
        unit_id = self._add_unit(root, "MYR")
        self._add_document_info_facts(root, job, contexts)
        self._add_all_financial_facts(root, grouped_items, contexts, unit_id)

        if job.directors_report_html:
            self._add_directors_report(root, job, contexts)

        return etree.tostring(root, pretty_print=True, xml_declaration=True, encoding="UTF-8")

    def _add_schema_ref(self, root: etree.Element) -> None:
        etree.SubElement(
            root,
            f"{{{self.nsmap['link']}}}schemaRef",
            {
                f"{{{self.nsmap['xlink']}}}type": "simple",
                f"{{{self.nsmap['xlink']}}}href": "https://mbrs.ssm.com.my/taxonomy/SSMxT2022v1.0/rep/ssm/ca-2016/fs/mpers/ssmt-fs-mpers_2022-12-31_entry_point.xsd",
            },
        )

    def _add_comprehensive_contexts(self, root: etree.Element, job: FilingJob) -> Dict[str, str]:
        contexts: Dict[str, str] = {}
        fye = job.financial_year_end.date() if hasattr(
            job.financial_year_end, "date") else job.financial_year_end
        entity_id = job.registration_number or "UNKNOWN"

        current_year = fye.year
        current_start = date(current_year - 1, fye.month,
                             fye.day) + timedelta(days=1)
        current_end = fye

        prior_year = current_year - 1
        prior_end = date(prior_year, fye.month, fye.day)
        prior_start = date(prior_year - 1, fye.month,
                           fye.day) + timedelta(days=1)

        current_start_str = current_start.strftime("%Y%m%d")
        current_end_str = current_end.strftime("%Y%m%d")
        prior_start_str = prior_start.strftime("%Y%m%d")
        prior_end_str = prior_end.strftime("%Y%m%d")

        contexts["current_duration"] = f"fromto_{current_start_str}_{current_end_str}"
        self._create_context(root, contexts["current_duration"], entity_id,
                             period_start=current_start, period_end=current_end)

        contexts["current_instant"] = f"asof_{current_end_str}"
        self._create_context(
            root, contexts["current_instant"], entity_id, instant=current_end)

        contexts["prior_duration"] = f"fromto_{prior_start_str}_{prior_end_str}"
        self._create_context(
            root, contexts["prior_duration"], entity_id, period_start=prior_start, period_end=prior_end)

        contexts["prior_instant"] = f"asof_{prior_end_str}"
        self._create_context(
            root, contexts["prior_instant"], entity_id, instant=prior_end)

        sep_dim = [{
            "dimension": "ifrs-smes:ConsolidatedAndSeparateFinancialStatementsAxis",
            "member": "ifrs-smes:SeparateMember",
            "type": "explicit",
        }]

        contexts["current_duration_separate"] = f"fromto_{current_start_str}_{current_end_str}_SeparateMember"
        self._create_context(root, contexts["current_duration_separate"], entity_id,
                             period_start=current_start, period_end=current_end, dimensions=sep_dim)

        contexts["current_instant_separate"] = f"asof_{current_end_str}_SeparateMember"
        self._create_context(
            root, contexts["current_instant_separate"], entity_id, instant=current_end, dimensions=sep_dim)

        contexts["prior_instant_separate"] = f"asof_{prior_end_str}_SeparateMember"
        self._create_context(
            root, contexts["prior_instant_separate"], entity_id, instant=prior_end, dimensions=sep_dim)

        return contexts

    def _create_context(
        self,
        root: etree.Element,
        context_id: str,
        entity_id: str,
        period_start: Optional[date] = None,
        period_end: Optional[date] = None,
        instant: Optional[date] = None,
        dimensions: Optional[List[Dict]] = None,
    ) -> None:
        context = etree.SubElement(
            root, f"{{{self.nsmap['xbrli']}}}context", id=context_id)
        entity = etree.SubElement(context, f"{{{self.nsmap['xbrli']}}}entity")
        etree.SubElement(entity, f"{{{self.nsmap['xbrli']}}}identifier",
                         scheme="https://www.ssm.com.my/").text = entity_id

        period = etree.SubElement(context, f"{{{self.nsmap['xbrli']}}}period")
        if instant:
            etree.SubElement(
                period, f"{{{self.nsmap['xbrli']}}}instant").text = instant.strftime("%Y-%m-%d")
        else:
            etree.SubElement(
                period, f"{{{self.nsmap['xbrli']}}}startDate").text = period_start.strftime("%Y-%m-%d")
            etree.SubElement(
                period, f"{{{self.nsmap['xbrli']}}}endDate").text = period_end.strftime("%Y-%m-%d")

        if dimensions:
            scenario = etree.SubElement(
                context, f"{{{self.nsmap['xbrli']}}}scenario")
            for dim in dimensions:
                if dim.get("type") == "explicit":
                    etree.SubElement(
                        scenario,
                        f"{{{self.nsmap['xbrldi']}}}explicitMember",
                        dimension=dim["dimension"],
                    ).text = dim["member"]

    def _add_unit(self, root: etree.Element, currency_code: str = "MYR") -> str:
        unit = etree.SubElement(
            root, f"{{{self.nsmap['xbrli']}}}unit", id=currency_code)
        etree.SubElement(
            unit, f"{{{self.nsmap['xbrli']}}}measure").text = f"iso4217:{currency_code}"
        return currency_code

    def _add_document_info_facts(self, root: etree.Element, job: FilingJob, contexts: Dict[str, str]) -> None:
        duration_context = contexts["current_duration"]
        instant_context = contexts["current_instant"]

        etree.SubElement(root, f"{{{self.nsmap['ssmt-dei']}}}DescriptionOfPresentationCurrency",
                         contextRef=duration_context).text = "Malaysian Ringgit (MYR)"
        etree.SubElement(
            root, f"{{{self.nsmap['ssmt-dei']}}}LevelOfRoundingUsedInFinancialStatements", contextRef=duration_context).text = "Actuals"
        etree.SubElement(root, f"{{{self.nsmap['ssmt-dei']}}}NameAndVersionOfSoftwareUsedToGenerateXBRLFile",
                         contextRef=duration_context).text = "MBRS_Preparation_Tool v2.2"
        etree.SubElement(root, f"{{{self.nsmap['ssmt-dei']}}}TaxonomyVersion",
                         contextRef=duration_context).text = "SSMxT_2022v1.0"

        etree.SubElement(
            root,
            f"{{{self.nsmap['ssmt']}}}DisclosureOnWhetherCompanysSharesAreTradedOnAnyOfficialStockExchange",
            contextRef=duration_context,
        ).text = "Not-listed"

        etree.SubElement(
            root,
            f"{{{self.nsmap['ssmt']}}}DisclosureOfWhetherCompanyRegulatedByBankNegaraMalaysiaAtFinancialYearEnd",
            contextRef=duration_context,
        ).text = "Company not regulated by Bank Negara Malaysia"

        fye = job.financial_year_end.date() if hasattr(
            job.financial_year_end, "date") else job.financial_year_end
        approval_date = fye + timedelta(days=180)
        etree.SubElement(
            root,
            f"{{{self.nsmap['ssmt']}}}DateOfFinancialStatementsApprovedByBoardOfDirectors",
            contextRef=instant_context,
        ).text = approval_date.strftime("%Y-%m-%d")

    def _add_all_financial_facts(
        self,
        root: etree.Element,
        grouped_items: Dict[str, Dict[int, List[ExtractedDataItem]]],
        contexts: Dict[str, str],
        unit_id: str,
    ) -> None:
        facts_added = 0
        for years_data in grouped_items.values():
            for year, items in years_data.items():
                for item in items:
                    if self._add_financial_fact(root, item, year, contexts, unit_id):
                        facts_added += 1
        logger.info("Added %s financial facts to XBRL", facts_added)

    def _add_financial_fact(
        self,
        root: etree.Element,
        item: ExtractedDataItem,
        year: int,
        contexts: Dict[str, str],
        unit_id: str,
    ) -> bool:
        try:
            if not item.confirmed_tag and not item.template_field_id:
                return False

            value, decimals = self._clean_and_get_decimals(
                item.extracted_value)
            context_ref = self._select_context(item, year, contexts)
            if not context_ref:
                return False

            if item.confirmed_tag:
                ns_prefix = item.confirmed_tag.namespace
                tag_name = item.confirmed_tag.xbrl_tag
            elif ":" in (item.template_field_id or ""):
                blocked_reason = automatic_mapping_guardrail_reason(
                    item.template_field_id,
                    getattr(item, "extracted_label", None),
                )
                if blocked_reason:
                    logger.info(
                        "Skipped template fact for label '%s' to %s by %s; leaving for manual review",
                        getattr(item, "extracted_label", "<unknown>"),
                        item.template_field_id,
                        blocked_reason,
                    )
                    return False
                ns_prefix, tag_name = item.template_field_id.split(":", 1)
            else:
                return False

            if ns_prefix not in self.nsmap:
                logger.warning("Unknown namespace prefix: %s", ns_prefix)
                return False

            fact = etree.SubElement(
                root,
                f"{{{self.nsmap[ns_prefix]}}}{tag_name}",
                contextRef=context_ref,
                unitRef=unit_id,
                decimals=decimals,
            )
            fact.text = value
            return True
        except Exception as e:
            logger.warning("Error adding fact for item %s: %s",
                           getattr(item, "extracted_label", "<unknown>"), e)
            return False

    def _select_context(self, item: ExtractedDataItem, year: int, contexts: Dict[str, str]) -> Optional[str]:
        current_year = int(contexts["current_instant"].split("_")[1][:4])
        is_current = year >= current_year

        if item.confirmed_tag:
            period_type = item.confirmed_tag.period_type
        else:
            stmt = (item.statement_type or "").lower()
            if any(k in stmt for k in ("position", "balance", "assets", "liabilities")):
                period_type = "instant"
            else:
                period_type = "duration"

        year_prefix = "current" if is_current else "prior"
        context_key = f"{year_prefix}_{period_type}_separate"
        if context_key not in contexts:
            context_key = f"{year_prefix}_{period_type}"
        return contexts.get(context_key)

    def _add_directors_report(self, root: etree.Element, job: FilingJob, contexts: Dict[str, str]) -> None:
        text_block = etree.SubElement(
            root,
            f"{{{self.nsmap['ssmt']}}}DisclosureOfDirectorsReportExplanatory",
            contextRef=contexts["current_duration"],
        )
        text_block.text = etree.CDATA(job.directors_report_html)

    def _clean_and_get_decimals(self, value_str: str) -> Tuple[str, str]:
        if not isinstance(value_str, str):
            return "0", "0"

        cleaned_str = value_str.replace(",", "").replace(" ", "").strip()

        if cleaned_str.startswith("(") and cleaned_str.endswith(")"):
            cleaned_str = "-" + cleaned_str[1:-1]

        cleaned_str = re.sub(r"[^\d.-]", "", cleaned_str)
        if not cleaned_str or cleaned_str in ["-", ".", "-."]:
            return "0", "0"

        try:
            float(cleaned_str)
            decimals = len(cleaned_str.split(
                ".")[1]) if "." in cleaned_str else 0
            return cleaned_str, str(decimals)
        except Exception:
            return "0", "0"

    def _generate_filename(self, job: FilingJob) -> str:
        reg_num = safe_filename_component(job.registration_number, "UNKNOWN")
        fye = job.financial_year_end.strftime("%Y%m%d")
        return f"SSM_FS-MPERS_{reg_num}_{fye}.xbrl"

    def _save_xbrl_file(self, filename: str, content: bytes) -> str:
        output_dir = "uploads/xbrl"
        os.makedirs(output_dir, exist_ok=True)
        file_path = os.path.join(output_dir, filename)
        with open(file_path, "wb") as f:
            f.write(content)
        return file_path


xbrl_generator = XBRLGenerator()


async def generate_xbrl_for_job(
    job_id: int,
    db: AsyncSession,
    include_unreviewed: bool = False,
) -> XBRLGenerationResponse:
    return await xbrl_generator.generate_xbrl(job_id, db, include_unreviewed)


def validate_xbrl_content(xbrl_content: str) -> Dict[str, object]:
    try:
        if re.search(r"<!\s*(DOCTYPE|ENTITY)\b", xbrl_content, re.IGNORECASE):
            return {"valid": False, "error": "DOCTYPE and ENTITY declarations are not allowed"}

        parser = etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            load_dtd=False,
            huge_tree=False,
        )
        root = etree.fromstring(xbrl_content.encode("utf-8"), parser=parser)
        if root.tag != "{http://www.xbrl.org/2003/instance}xbrl":
            return {"valid": False, "error": "Root element is not xbrli:xbrl"}
        return {"valid": True, "error": None}
    except Exception as e:
        return {"valid": False, "error": str(e)}
