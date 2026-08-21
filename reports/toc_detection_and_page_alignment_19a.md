# TOC detection and page alignment #19A

Status: **PASS**

## Detection and parsing

Detection is document-wide. It combines explicit `INDEX`/`CONTENTS` headings, page-column labels, repeated title/page patterns, known financial section aliases, and short-row density.

Multi-page continuation is bounded around an explicit heading seed. The adjacent page needs plausible page-reference continuity, another heading, or a page column; later pages additionally need strong TOC-specific evidence. Continuation pages never become recursive seeds. Tests cover both a three-page TOC and financial-statement pages that would otherwise be absorbed.

The parser supports explicit/start-only ranges, Arabic and canonical Roman labels, Unicode dash variants, numbered layouts, Page No. text, OCR separators, and dotted leaders without required whitespace. It preserves every malformed source line as evidence. Unparsed or physically impossible page references cannot create #19A boundaries.

Ranges use the immediate next TOC entry in the same numbering scheme. Same-page starts remain shared; decreases and Roman-to-Arabic changes are warnings, not silent backward inference.

## Normalization

Title normalization uses:

1. exact normalized aliases;
2. deterministic fuzzy matching at `0.88`;
3. `unknown_section`.

Income Statement remains distinct from combined comprehensive-income wording.

## Heading anchors and reconciliation

Heading scoring uses normalized equality, aliases, fuzzy similarity, Azure roles, case, top-of-page geometry, nearby printed labels, and table boundaries.

Paragraph/line copies at the same coordinates collapse. Spatially distinct or cross-page alternatives remain in `alternative_candidates` with page, text, score, method, signals, and bounds. Cross-page alternatives within `0.12` cannot support offset consensus or section boundaries.

Alignment uses:

`offset = pdf_page_index - printed_page_number`

Multiple consistent anchors create a consensus. One anchor is review-only. Piecewise Roman/Arabic/reset regimes require at least two anchors per contiguous regime. Duplicate printed labels are resolved only inside the anchor's regime. Inconsistent or ambiguous anchors stop broad projection and preserve unmapped/review-required evidence.

## Verification

The 51 focused #19A tests and all 1,317 backend tests pass. Adversarial coverage includes continuation flood-fill, dotted leaders, Roman word suffixes, non-monotonic starts, coherent alternative heading sets, same-page spatial ambiguity, and page-reset collisions.

Recommended next: **#19B — classify primary sections and note subsections into the 24 internal template groups.**
