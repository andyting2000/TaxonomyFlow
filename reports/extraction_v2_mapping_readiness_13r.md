# Feature #13R Extraction v2 Mapping Readiness Report

## Assessment

- Overall status: promising_but_not_production_ready
- Production ready: False
- Mapping pipeline ready: False
- XBRL generation validated: False
- Arelle validation passed: False
- Database mutated: False

#13Q benchmark succeeded and Extraction v2 plus Hugging Face Qwen now produces useful numeric and text-block candidates. Candidate normalization, duplicate control, section confidence, and mapping readiness gates are needed before production cutover.

## Readiness Counts

- {'high': 337, 'low': 146, 'medium': 318, 'not_ready': 139}

## Per Case Readiness

| Case | High | Medium | Low | Not Ready | Score | Classification |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 001-bizaid-synthetic | 2 | 37 | 1 | 82 | 11.5 | needs_numeric_cleanup_first |
| 002-bezlife-marketing | 64 | 43 | 6 | 2 | 81.0 | needs_text_block_cleanup_first |
| 003-fine-batik | 85 | 69 | 32 | 3 | 72.7 | needs_numeric_cleanup_first |
| 004-info-house | 46 | 58 | 29 | 17 | 58.9 | needs_manual_review_policy |
| 005-jconnector | 49 | 52 | 18 | 15 | 63.5 | needs_candidate_cleanup_first |
| 006-Rahsia-Herbal | 68 | 31 | 41 | 6 | 66.8 | needs_manual_review_policy |
| 007-Shield-Plus | 23 | 28 | 19 | 14 | 52.2 | needs_numeric_cleanup_first |

## Mapping Readiness Gates

### Candidate Validity Gate
- numeric candidates must have numeric values
- text blocks must have sufficient text
- labels must not be empty
- pure year/date rows must not be treated as facts

### Duplicate Conflict Gate
- duplicate label/value rows need evidence for detail rows
- duplicate labels with conflicting values require review or aggregation policy

### Section Confidence Gate
- candidate should have a reasonable statement_section
- missing or generic section lowers readiness

### Year/Context Gate
- current/prior values should be assigned consistently
- year headers must not become facts

### Sign Gate
- negative values should preserve original evidence
- sign normalization must not happen silently

### Text-Block Gate
- text blocks should not be over-split into single-line fragments
- text blocks should not be merged across unrelated sections

### Mapping Confidence Gate
- no automatic mapping for weak labels or generic headings
- manual review is required for low-confidence mapping

## Cleanup Recommendations

### Safe Deterministic Cleanup Candidates
- Remove or reclassify pure date labels extracted as numeric facts.
- Reclassify pure year/date rows as metadata or heading, not facts.
- Normalize whitespace, punctuation, currency symbols, commas, dashes, and parentheses negatives.
- Suppress empty candidates and keep empty candidate pages as processed benchmark evidence.

### Needs Conservative Heuristics
- Infer current/prior years only from nearby table headers with explicit evidence.
- Apply subtotal versus total classification with section-aware heuristics.
- Handle duplicate label conflicts with an explicit review or aggregation policy.
- Use nearby headings for section inheritance when statement_section is missing.
- Tune text-block grouping so narrative disclosures are not split line by line or merged across sections.

### Needs Mapping Stage Design
- Match labels to taxonomy concepts only after candidate validity gates pass.
- Separate detail rows from summary concepts before mapping.
- Define sign policy and concept-specific guardrails before value normalization changes.
- Keep dimensions and aggregation decisions in the mapping stage, not extraction cleanup.

### Needs Manual Review
- Review duplicate labels with conflicting values.
- Review weak labels attached to numeric values.
- Review ambiguous labels that could map to multiple taxonomy concepts.
- Review suspicious negative values and possible current/prior reversal cases.

## Recommended Next Feature

- Feature #13S - Extraction v2 duplicate and conflict control before mapping.
