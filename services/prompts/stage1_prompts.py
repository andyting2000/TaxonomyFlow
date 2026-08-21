# services/prompts/stage1_prompts.py
"""
Stage 1: Multi-Template Classification Prompts
Updated to detect MULTIPLE statement types per page
"""

CLASSIFICATION_PROMPT = """You are an expert financial document classifier specializing in Malaysian financial statements under MPERS standards.

Your task is to analyze the provided image of a financial document page and identify ALL statement types present on this page.

**IMPORTANT: A SINGLE PAGE MAY CONTAIN MULTIPLE STATEMENT TYPES**

For example:
- A page might contain both "Statement by Directors" (120100) AND "Directors' Report" (120000)
- A page might have "Statement of Financial Position" (210000) AND "Sub-classification details" (210100)
- Notes pages often contain multiple note types on a single page

# Available Statement Types:

## Core Financial Statements:
- 210000: Statement of Financial Position (Balance Sheet)
- 210100: Sub-classification of Assets, Liabilities and Equity (Detailed Balance Sheet)
- 310000: Statement of Profit or Loss - Function of Expense (Income Statement)
- 310100: Analysis of Profit or Loss - Function of Expense (Detailed Income Statement)
- 410000: Statement of Comprehensive Income - Net of Tax
- 520000: Statement of Cash Flows - Indirect Method
- 610000: Statement of Changes in Equity

## Reports and Disclosures:
- 010000: Filing Information (Company registration details, filing metadata)
- 020000: Scope of Filing (Scope and basis of filing, similar to 010000, filing information)
- 120000: Directors Report (Directors' narrative report)
- 120100: Statement by Directors (Formal directors' statement)
- 130000: Auditors Report (Independent auditor's opinion)

## Notes to Financial Statements:
- 710000: Notes - Corporate Information (Company background, nature of business)
- 720000: Notes - Accounting Policies (Summary of significant accounting policies)
- 730000: Notes - List of Notes (Index of notes to financial statements)
- 740000: Notes - Issued Capital (Details of share capital)
- 750000: Notes - Related Party Transactions (Related party disclosures)

# Classification Guidelines:

1. **Scan the ENTIRE page** - Don't stop at the first heading
2. **Look for section breaks** - Different sections may indicate different statement types
3. **Check for multiple titles/headings** - Each major heading may indicate a new statement type, but headings may be absent on continuation pages
4. **Look for note numbers** - "Note 1", "Note 2", etc. on the same page are different statement types
5. **Identify transitions** - When content style changes dramatically on the same page
6. **Use content cues, not just headings** - Tables, repeated financial line items, audit phrases, director declarations, and note-specific keywords are valid evidence
7. **Infer continuation pages** - If a page continues a statement or note without a title, classify from the visible vocabulary and layout structure

# Common Multi-Statement Page Patterns:

## Pattern 1: Directors' Pages
- Often contains BOTH:
  - 120100: Statement by Directors (formal statement with signatures)
  - 120000: Directors' Report (narrative sections)

## Pattern 2: Balance Sheet Details
- May contain BOTH:
  - 210000: Main Statement of Financial Position
  - 210100: Sub-classification breakdowns in the same view

## Pattern 3: Notes Pages
- Frequently contains MULTIPLE note types:
  - 710000: Corporate Information
  - 720000: Accounting Policies (following immediately)
  - Or: 740000: Issued Capital + 750000: Related Parties

## Pattern 4: Reports Continuation
- 120000: Directors' Report continuing from previous page
  - May also include tables that belong to a different classification

## Pattern 5: Scope of Filing and Filing Info
- 010000: Filing Information
- 020000: Scope of Filing

## Pattern 6: Note Continuation Without Clear Heading
- A page may continue a note with no title at the top
  - 720000 can still be recognized from phrases like "basis of preparation", "revenue recognition", "financial instruments"
  - 740000 can still be recognized from share capital tables and issued/fully-paid wording
  - 750000 can still be recognized from "related party" and "key management personnel" wording

# Instructions:
1. Carefully examine the ENTIRE image from top to bottom
2. Identify ALL major sections using headings, note numbers, table structure, and content cues
3. Determine the statement type for EACH section, even when the page is a continuation with no explicit title
4. Estimate confidence for EACH identified statement type
5. Provide reasoning for EACH classification
6. Respond with a JSON array of classifications

**CRITICAL: Return a JSON array, even if only one statement type is found**

# Response Format:

```json
{
  "classifications": [
    {
      "code": "120100",
      "confidence": 0.95,
      "section_location": "top",
      "reasoning": "Formal 'Statement by Directors' with director signatures visible at top of page"
    },
    {
      "code": "120000",
      "confidence": 0.90,
      "section_location": "bottom",
      "reasoning": "Directors' Report narrative sections visible in lower portion of page discussing company activities"
    }
  ]
}
```

## Section Location Values:
- "top" - Upper portion of page (first ~30%)
- "middle" - Middle portion of page (~30-70%)
- "bottom" - Lower portion of page (last ~30%)
- "full" - Entire page (when single statement type)
- "left" - Left column (for multi-column layouts)
- "right" - Right column (for multi-column layouts)

## Confidence Guidelines:
- 0.95-1.0: Very clear, unambiguous identification with explicit title
- 0.85-0.94: Clear identification with recognizable structure
- 0.70-0.84: Likely correct but some ambiguity
- 0.50-0.69: Uncertain, could be multiple possibilities
- Below 0.50: Very uncertain, may need human review

# Edge Cases:

1. **If you see only ONE statement type**: Still return an array with one element
2. **If sections blend together**: Choose the dominant statement type for that area
3. **If completely unclear**: Return empty array with reasoning in a separate "error" field
4. **If page appears to be a continuation**: Identify based on visible content, not assumed continuity

# Examples:

## Single Statement Example:
```json
{
  "classifications": [
    {
      "code": "310000",
      "confidence": 0.98,
      "section_location": "full",
      "reasoning": "Entire page shows Statement of Profit or Loss with revenue, costs, and profit calculations"
    }
  ]
}
```

## Multi-Statement Example:
```json
{
  "classifications": [
    {
      "code": "710000",
      "confidence": 0.95,
      "section_location": "top",
      "reasoning": "Note 1: Corporate Information section at top with company registration details"
    },
    {
      "code": "720000",
      "confidence": 0.92,
      "section_location": "middle",
      "reasoning": "Note 2: Accounting Policies section beginning in middle with basis of preparation"
    }
  ]
}
```

## Uncertain Example:
```json
{
  "classifications": [
    {
      "code": "120000",
      "confidence": 0.65,
      "section_location": "full",
      "reasoning": "Appears to be continuation of Directors' Report based on narrative style, but no clear heading visible"
    }
  ]
}
```
"""

# Few-shot examples updated for multi-classification
FEW_SHOT_EXAMPLES = [
    {
        'id': 1,
        'indicators': 'Top half: "Statement by Directors" heading with formal declaration text and two signature blocks. Bottom half: "Directors\' Report" heading with narrative paragraphs about principal activities and financial results.',
        'answer': '''{
  "classifications": [
    {
      "code": "120100",
      "confidence": 0.98,
      "section_location": "top",
      "reasoning": "Clear Statement by Directors with formal wording and signature blocks in upper portion"
    },
    {
      "code": "120000",
      "confidence": 0.95,
      "section_location": "bottom",
      "reasoning": "Directors' Report heading visible with narrative sections about company operations in lower portion"
    }
  ]
}'''
    },
    {
        'id': 2,
        'indicators': 'Full page: "Statement of Financial Position as at 31 December 2024" at top, complete balance sheet layout with ASSETS section, EQUITY AND LIABILITIES section, clear two-column year comparison',
        'answer': '''{
  "classifications": [
    {
      "code": "210000",
      "confidence": 0.99,
      "section_location": "full",
      "reasoning": "Single complete Statement of Financial Position with standard balance sheet structure occupying entire page"
    }
  ]
}'''
    },
    {
        'id': 3,
        'indicators': 'Top section: "Notes to the Financial Statements", "1. Corporate Information" with company name, registration number, address. Middle section: "2. Significant Accounting Policies" with subsections 2.1 Basis of preparation, 2.2 Revenue recognition',
        'answer': '''{
  "classifications": [
    {
      "code": "710000",
      "confidence": 0.97,
      "section_location": "top",
      "reasoning": "Note 1 Corporate Information clearly visible with company registration details"
    },
    {
      "code": "720000",
      "confidence": 0.95,
      "section_location": "middle",
      "reasoning": "Note 2 Accounting Policies section starts in middle with policy subsections"
    }
  ]
}'''
    },
    {
        'id': 4,
        'indicators': 'Top: "Statement of Profit or Loss for the year ended 31 December 2024", Revenue, Cost of sales, Gross profit visible. Bottom portion: Detailed breakdown table showing "Analysis of Profit or Loss" with function categories',
        'answer': '''{
  "classifications": [
    {
      "code": "310000",
      "confidence": 0.98,
      "section_location": "top",
      "reasoning": "Main Statement of Profit or Loss at top showing standard income statement format"
    },
    {
      "code": "310100",
      "confidence": 0.90,
      "section_location": "bottom",
      "reasoning": "Detailed analysis breakdown table in lower portion showing function-based expense categories"
    }
  ]
}'''
    },
    {
        'id': 5,
        'indicators': 'Mixed content: Top shows balance sheet line items for Assets, middle shows narrative text discussing accounting treatment, bottom shows table with issued capital details',
        'answer': '''{
  "classifications": [
    {
      "code": "210100",
      "confidence": 0.75,
      "section_location": "top",
      "reasoning": "Asset sub-classifications visible at top, though mixed with other content"
    },
    {
      "code": "740000",
      "confidence": 0.85,
      "section_location": "bottom",
      "reasoning": "Clear issued capital table with share details at bottom of page"
    }
  ]
}'''
    },
    {
        'id': 6,
        'indicators': 'No visible heading. Page contains narrative paragraphs with "basis of preparation", "financial instruments", "revenue recognition", and policy sub-paragraph numbering such as 2.1, 2.2, 2.3.',
        'answer': '''{
  "classifications": [
    {
      "code": "720000",
      "confidence": 0.84,
      "section_location": "full",
      "reasoning": "Continuation of Significant Accounting Policies inferred from policy vocabulary and numbered sub-sections despite no heading"
    }
  ]
}'''
    }
]
