# Document section grouping #19A

Status: **PASS**

## Grouping model

Sections use reconciled PDF ranges first. On a shared page, ordinary content is split only when every candidate section has a trusted, spatially distinct heading anchor. An exact anchor source can identify its own heading; missing or tied boundary evidence leaves other content ambiguous.

Multi-page content is assigned only when exactly one candidate section exists and contains every source page. Nested overlaps and section-spanning tables stay ambiguous with all candidate section IDs. Cells and normalized rows may still be assigned when their individual page/geometry is decisive.

TOC content never enters a financial section. Missing-page and out-of-range content is explicitly unassigned.

## Evidence and conservation

Every paragraph, line/heading, table, cell, and normalized row has a bounded `DocumentContentEvidence` record containing its text, complete page lists, bounds, source indexes, and provenance. Persisted normalized-row references use the actual database UUID while retaining the original candidate ID.

The analyzer enforces:

`inventory = assigned ∪ ambiguous ∪ unassigned`

The three sets must be disjoint, IDs unique, and dropped content zero. A violation fails only the optional analysis.

## Notes preparation

Notes is one primary `notes_to_financial_statements` section with level 1, no parent, and stable order. Candidate numbered note headings retain resolvable text/page/bounds. #19A creates no child note sections and performs no template classification.

## Verification

Tests cover same-page sections, missing/tied anchors, overlap warnings, nested multi-page overlaps, spanning tables and assignable cells, three-page Notes evidence, no-TOC conservation, evidence-only malformed entries, and complete reference resolution.

The 51 focused #19A tests and all 1,317 backend tests pass.

Recommended next: **#19B — classify primary sections and note subsections into the 24 internal template groups.**
