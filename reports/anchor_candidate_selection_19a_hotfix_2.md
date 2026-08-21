# Anchor candidate selection #19A-hotfix-2

Status: **PASS** for deterministic implementation and regression coverage. Fresh real-PDF smoke: **PENDING**.

## Job 66 defect and correction

The v2 selector ranked a combined score before lexical tier. Cover-page layout evidence could therefore make `DIRECTORS' REPORT AND` (Tier C, PDF 0) beat an existing exact `DIRECTORS' REPORT` (Tier A, PDF 2), and could trust the generic fragments `DIRECTORS` and `FINANCIAL STATEMENTS`. Normal financial-report headings with trailing qualifiers were rejected because candidate-token coverage penalized the qualifier words.

The deterministic order is now Tier A exact, Tier B canonical alias/equivalent/prefix, Tier C strong fuzzy, then Tier D safeguarded containment. Within one tier the order is lexical score, expected core-token coverage, heading quality, provisional-offset distance, combined score, page, and stable content ID. Layout cannot cross a tier boundary or rescue an untrusted string.

Semantic normalization removes Azure DI `:selected` and `:unselected` markers, including spacing/punctuation variants, before parsing and comparison. `source_text` retains the original Azure text and the extraction payload is not mutated.

Distinctive core tokens prevent `DIRECTORS` from representing `Statement by Directors` because `statement` is missing, and prevent `FINANCIAL STATEMENTS` from representing Notes because `notes` is missing. A bounded equivalence table handles only safe singular/plural pairs such as `director/directors`, `auditor/auditors`, and `statement/statements`; no uncontrolled stemming is used.

Canonical-prefix matching now trusts a substantially complete expected core followed by normal qualifiers. This covers `STATEMENT BY DIRECTOR PURSUANT TO`, `STATUTORY DECLARATION PURSUANT TO`, the full auditor-to-members heading, and dated Notes headings.

Pass 1 derives a provisional numbering offset from Tier A/B candidates only, requiring at least two agreeing anchors and 72% weighted support. Pass 2 uses offset distance only after lexical trust and tier. On the Job 66 regression fixture the selector chooses five exact and four prefix anchors, all at offset +1; confidence is `0.9884`, weighted +1 support is `8.56`, and both weaker-selection and off-regime counts are zero.

No live provider, mapping, confirmed-tag, template, or final-state mutation occurred.
