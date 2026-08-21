# services/prompts/stage2_prompt_builder.py
"""
Stage 2: Multi-Template Dynamic Prompt Builder
Builds extraction prompts for MULTIPLE templates simultaneously
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class Stage2PromptBuilder:
    """
    Dynamically builds extraction prompts from MULTIPLE XML templates
    Creates template-specific prompts for accurate data extraction from pages with multiple statement types
    """
    
    # Base instruction template for MULTI-TEMPLATE extraction
    BASE_INSTRUCTION = """You are an expert financial data extractor specializing in Malaysian MPERS financial statements.

Your task is to extract ALL financial data from this image which contains MULTIPLE STATEMENT TYPES and return it in structured JSON format.

⚠️  **CRITICAL: This page contains {template_count} different statement types:**

{template_summary}

# EXTRACTION STRATEGY:

1. **Scan the entire page from top to bottom**
2. **Identify section boundaries** - Look for headings, spacing, or style changes
3. **Extract data for EACH statement type separately**
4. **Match each extracted item to the correct template AND field** based on the comprehensive field lists provided below
5. **Use the EXACT field_id from the template** when you find a matching field
6. **Include the template_code with each extracted item** so we know which template it belongs to
7. **Leverage the field metadata** (xbrl_tag, position, section, data_type) to make accurate matches

# DETAILED TEMPLATE STRUCTURES:

{detailed_templates}

# OUTPUT FORMAT:

Return your response as a JSON object with items grouped by template:

```json
{{
  "items": [
    {{
      "template_code": "120100",
      "section_location": "top",
      "concept_id": "ssmt:ExactConceptIdFromTemplate",
      "label": "Exact label as shown on page",
      "value": "Exact value as shown (with commas, formatting)",
      "year": 2024,
      "level": 2,
      "required": true
    }},
    {{
      "template_code": "120000",
      "section_location": "bottom",
      "concept_id": "ssmt:AnotherConceptId",
      "label": "Another label",
      "value": "Another value",
      "year": 2024,
      "level": 1,
      "required": false
    }}
  ]
}}
```

# CRITICAL RULES FOR MULTI-TEMPLATE EXTRACTION:

1. **Section Awareness**: Pay attention to where items are located on the page
   - Items in the TOP section → likely belong to the first template
   - Items in the MIDDLE/BOTTOM → likely belong to the second/third template

2. **Template Code Assignment**: ⚠️ EXTREMELY IMPORTANT - Use ONLY the NUMERIC codes provided above!
   - Valid codes for this page: {valid_template_codes}
   - ❌ DO NOT invent new codes or use descriptive names like "CORPORATE_INFORMATION"
   - ✅ USE ONLY these exact numeric codes: {valid_template_codes}
   - Match the template_code to the section where you found the data
   - Use the section_location from the classification
   - When in doubt, use the first code: {first_template_code}

3. **Concept Matching**: ⚠️ CRITICAL - Use the comprehensive concept lists provided for each template!
   - Each template below includes COMPLETE XBRL concept definitions with metadata
   - Look for concepts that match the label, data type, and hierarchy you see on the page
   - When you find a match, use the EXACT concept_id provided in the template (e.g., "ssmt:TotalAssets")
   - Concept IDs use namespace prefixes (ssmt:, ifrs-smes:, etc.)
   - Use the parent/level metadata to understand the hierarchical structure
   - Don't force a concept from template A into template B
   - If uncertain which template, use the template that best matches the concept type and section

4. **Avoid Duplication**: Don't extract the same data twice for different templates
   - Each piece of data should appear only once
   - Assign it to the most appropriate template

5. **Preserve Context**: Note the section_location for each item:
   - "top", "middle", "bottom", "full", "left", "right"

# MONETARY VALUE RULES:
- Keep all formatting (commas, parentheses)
- Parentheses indicate negative values: (1,000) = -1,000
- Include currency symbols if present
- If value spans multiple years, create separate items

# TEXT BLOCK RULES (for Notes/Reports):
- For narrative sections, extract complete paragraphs
- Preserve formatting and structure
- Use concept_id from template if it's a text-block type concept

Now extract all data from the image following these instructions. Remember: this page has MULTIPLE statement types, so be thorough and organized."""
    
    def __init__(self):
        logger.info("Stage 2 Multi-Template Prompt Builder initialized")

    def _get_template_description(self, template: Dict, statement_code: str) -> str:
        """Return the human-readable statement name from current template metadata."""
        for key in ("description", "title", "statement_type"):
            value = template.get(key)
            if value and str(value).strip():
                return str(value).strip()

        code = template.get("code") or statement_code
        return f"Template {code}" if code else "Unknown Statement"
    
    def build_multi_template_extraction_prompt(
        self,
        templates: List[Dict],
        statement_codes: List[str],
        section_locations: List[str],
        page_context: Optional[str] = None
    ) -> str:
        """
        Build dynamic extraction prompt for MULTIPLE templates
        
        Args:
            templates: List of XML template structures
            statement_codes: List of statement codes matching templates
            section_locations: Where each template appears on page (top, middle, bottom)
            page_context: Optional context text
        
        Returns:
            Complete extraction prompt for multiple templates
        """
        # Build template summary
        template_summary_parts = []
        for i, (code, location) in enumerate(zip(statement_codes, section_locations), 1):
            template = templates[i-1]
            title = self._get_template_description(template, code)
            template_summary_parts.append(
                f"{i}. **{title}** (code: {code}) - Located in {location.upper()} section"
            )
        
        template_summary = "\n".join(template_summary_parts)
        
        # Build detailed templates section
        detailed_templates = []
        for i, (template, code, location) in enumerate(zip(templates, statement_codes, section_locations), 1):
            detailed_templates.append(
                self._format_single_template(template, code, location, i)
            )
        
        detailed_templates_text = "\n\n".join(detailed_templates)

        # Format valid template codes for the prompt
        valid_codes_str = ", ".join(statement_codes)
        first_code = statement_codes[0] if statement_codes else "unknown"

        # Format base instruction
        prompt = self.BASE_INSTRUCTION.format(
            template_count=len(templates),
            template_summary=template_summary,
            detailed_templates=detailed_templates_text,
            valid_template_codes=valid_codes_str,
            first_template_code=first_code
        )
        
        # Add page context if provided
        if page_context:
            prompt += f"\n\n# ADDITIONAL CONTEXT:\n{page_context[:500]}"
        
        return prompt
    
    def _format_single_template(
        self,
        template: Dict,
        statement_code: str,
        section_location: str,
        index: int
    ) -> str:
        """
        Format a single template for the multi-template prompt
        
        Args:
            template: XML template structure
            statement_code: Statement code
            section_location: Where on page (top, middle, bottom)
            index: Template number (1, 2, 3...)
        
        Returns:
            Formatted template section
        """
        statement_title = self._get_template_description(template, statement_code)
        
        # Build concept list
        concept_list = self._build_field_list(template)

        # Get statement-specific notes
        specific_notes = self._get_statement_specific_notes(statement_code)

        # Count concepts for informative header
        concept_count = len([f for f in concept_list.split('\n') if '→ concept_id:' in f])

        template_section = f"""
## Template {index}: {statement_title} (Code: {statement_code})

**Location on page:** {section_location.upper()}

**Complete XBRL concept definitions for this template ({concept_count} concepts total):**
(★ indicates required concepts, → shows concept metadata)

{concept_list}

{specific_notes}
"""
        return template_section
    
    def _build_field_list(self, template: Dict) -> str:
        """
        Build formatted field list from XBRL template structure

        XBRL templates have a flat 'concepts' array with hierarchical metadata,
        not nested sections/groups/fields like the old XML templates.

        Args:
            template: XBRL template structure with 'concepts' array

        Returns:
            Formatted field list string
        """
        concepts = template.get('concepts', [])

        if not concepts:
            return "  (No specific concepts defined - extract all visible items)"

        fields = []

        # Process each concept
        for concept in concepts:
            # Build hierarchical path for context
            parent = concept.get('parent', '')
            level = concept.get('level', 0)

            # Format concept as field
            field_info = self._format_concept(concept, level, parent)
            if field_info:
                fields.append(field_info)

        # Return ALL concepts (no truncation) for complete template knowledge
        field_list = "\n".join(fields)
        logger.debug(f"Built field list with {len(fields)} concepts for XBRL template")
        return field_list

    def _format_concept(self, concept: Dict, level: int, parent: str) -> Optional[str]:
        """
        Format a single XBRL concept for the prompt

        Args:
            concept: XBRL concept dictionary
            level: Hierarchy level (0 = root, 1 = child, etc.)
            parent: Parent concept ID

        Returns:
            Formatted concept string
        """
        concept_id = concept.get('id', '')
        label = concept.get('label', '')
        required = concept.get('required', False)
        namespace = concept.get('namespace', '')

        if not concept_id or not label:
            return None

        # Format with indentation based on level
        indent = "  " * level
        required_marker = "★ " if required else "  "

        # Infer data type from concept ID patterns (XBRL naming conventions)
        data_type_hint = ""
        concept_lower = concept_id.lower()

        if any(x in concept_lower for x in ['assets', 'liabilities', 'equity', 'revenue', 'profit', 'loss', 'cash', 'amount']):
            data_type_hint = " [MONETARY - e.g., 1,234,567 or (500,000)]"
        elif 'date' in concept_lower:
            data_type_hint = " [DATE - e.g., 31 December 2024]"
        elif 'percentage' in concept_lower or 'rate' in concept_lower:
            data_type_hint = " [PERCENT - e.g., 5.5% or 0.055]"
        elif 'shares' in concept_lower or 'units' in concept_lower:
            data_type_hint = " [SHARES/UNITS - number]"
        elif any(x in concept_lower for x in ['description', 'note', 'narrative', 'disclosure']):
            data_type_hint = " [TEXT BLOCK - full paragraphs/narrative]"

        # Build concept description with metadata
        parts = [f"{indent}{required_marker}{label}{data_type_hint}"]
        parts.append(f"{indent}   → concept_id: {concept_id}")
        parts.append(f"{indent}   → namespace: {namespace}")

        if parent:
            parts.append(f"{indent}   → parent: {parent}")

        return "\n".join(parts)

    def _get_statement_specific_notes(self, statement_code: str) -> str:
        """
        Get statement-specific extraction notes (same as before)
        """
        # Balance Sheet variations
        if statement_code in ['210000', '210100', '220000', '220100']:
            return """
# SPECIAL NOTES FOR STATEMENT OF FINANCIAL POSITION:
- Assets listed first (Non-current, then Current)
- Followed by Equity and Liabilities
- Two columns: Current Year | Previous Year
- Total Assets must equal Total Equity and Liabilities
- Watch for subtotals at each section level"""
        
        # Income Statement variations
        elif statement_code in ['310000', '320000', '320100', '310000', '310100']:
            return """
# SPECIAL NOTES FOR STATEMENT OF PROFIT OR LOSS:
- Starts with Revenue at the top
- Shows progression: Revenue -> Gross Profit -> Operating Profit -> Net Profit
- Function format: Cost of sales, Administrative, Distribution
- Nature format: Materials, Staff costs, Depreciation
- Watch for subtotals and profit measures"""
        
        # Comprehensive Income
        elif statement_code in ['410000', '420000']:
            return """
# SPECIAL NOTES FOR COMPREHENSIVE INCOME:
- Starts with Profit/Loss for the year
- Then Other Comprehensive Income items
- Total Comprehensive Income at bottom
- May show tax effects separately"""
        
        # Cash Flow variations
        elif statement_code in ['510000', '520000']:
            return """
# SPECIAL NOTES FOR CASH FLOW STATEMENT:
- Three sections: Operating, Investing, Financing
- Direct method: Cash receipts and payments
- Indirect method: Starts with Profit Before Tax + adjustments
- Each section has subtotals
- Ends with Net Increase/Decrease in Cash"""
        
        # Equity statements
        elif statement_code in ['610000', '620000']:
            return """
# SPECIAL NOTES FOR EQUITY STATEMENTS:
- Table format with columns for each equity component
- Rows: Opening balance, Changes, Closing balance
- Track movements: Profit, Dividends, Other changes
- All columns must reconcile"""
        
        # Reports (Directors, Auditors)
        elif statement_code in ['120000', '120100', '120200', '130000']:
            return """
# SPECIAL NOTES FOR REPORTS:
- Primarily narrative text in paragraphs
- Extract complete paragraphs, not fragments
- Preserve section headings
- May contain some tabular data
- Director/Auditor signatures important"""
        
        # Notes
        elif statement_code in ['710000', '720000', '730000', '740000', '750000']:
            return """
# SPECIAL NOTES FOR NOTES TO FINANCIAL STATEMENTS:
- May contain narrative text, tables, or both
- Preserve paragraph structure for narrative
- For tables: Extract headers and all rows
- Note numbers and titles are important
- Some notes span multiple pages"""
        
        return ""


# Global instance for easy import
stage2_prompt_builder = Stage2PromptBuilder()
