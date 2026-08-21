# TOC-aware template-native pipeline

## Status and scope

Feature #19A adds the disabled-by-default document-structure foundation, and
#19A-hotfix-1 published the hardened `19A-v2` grouping contract, and
#19A-hotfix-2 publishes `19A-v3` with lexical-tier-first anchor selection and
authoritative mapped TOC ranges. #19A-hotfix-3 publishes `19A-v4`, separates
full-page ownership from within-page heading geometry, and preserves explicit
multi-page ranges when a robust numbering regime resolves both endpoints even
if repeated continuation headers retain near-tie evidence. Feature
#19B adds a separate disabled-by-default hierarchical classifier that consumes
that structure and assigns primary sections and Notes children to the reconciled
canonical 24-template registry.

Neither feature selects taxonomy qnames, maps rows, populates template values or
tags, changes editing behavior, automates Supervisor review, generates XBRL, or
changes the normal-user interface. The current extraction and mapping workflow
remains authoritative. Structure and classification artifacts do not replace
`statement_type`, `template_field_id`, mapping suggestions, Supervisor records,
`confirmed_tag_id`, or final mappings.

## Current extraction architecture

The production call path is:

1. `tasks._run_azure_di_pdf_processing`
2. `services.azure_di_production_extraction.process_azure_di_filing_job`
3. one Azure Document Intelligence provider call
4. plain Azure layout normalization
5. local candidate conversion and the existing Extraction v2 normalizer
6. existing page/row persistence and deterministic statement/template mapping
7. filing status `REVIEW`
8. optional existing AI mapping suggestions

The #19A analyzer is inserted after step 5 has produced usable normalized rows and before step 6 begins current deterministic mapping. Analysis therefore sees the transient raw Azure layout and normalized rows while leaving current mapping inputs untouched. Extracted-row database IDs are attached after existing row persistence; the optional artifacts are written before the final extraction transaction commits `REVIEW`.

### Verified page and provenance semantics

- Azure `page_number` is retained as a 1-based document page number.
- Existing `financial_statement_pages.page_number` is also 1-based.
- #19A introduces a separate 0-based `pdf_page_index`, normally `azure_page_number - 1`.
- A printed page number or label is a third, independently reconciled value.
- Azure paragraph and table indexes are zero-based normalization ordinals.
- Raw pages, lines, words, paragraphs, paragraph roles, spans, tables, cells, polygons, and bounding regions exist only in the transient Azure result today.
- Current normalized rows keep selective table/paragraph provenance. Database rows do not preserve the full Azure layout.
- Printed page labels were not previously parsed or stored.
- Existing statement grouping is candidate-level context inference, not a lossless document section model.

The analyzer consumes the raw Azure result because the existing candidate normalizer intentionally suppresses TOC/index content from mapping input.

## Feature flags

All flags default to `false`.

- `TOC_AWARE_PIPELINE_ENABLED`: runs deterministic local structure analysis.
- `TOC_AWARE_STRUCTURE_PERSISTENCE_ENABLED`: atomically writes the validated versioned result after extraction commits.
- `TOC_AWARE_LLM_FALLBACK_ENABLED`: reserved for a later feature. #19A exposes the state but never performs an LLM call.
- `TOC_AWARE_TEMPLATE_CLASSIFICATION_ENABLED`: runs #19B deterministic-first classification after a successful #19A structure result.
- `TOC_AWARE_TEMPLATE_CLASSIFICATION_PERSISTENCE_ENABLED`: publishes the source-validated #19B artifact.
- `TOC_AWARE_TEMPLATE_CLASSIFICATION_LIVE_LLM_ENABLED`: allows one bounded structured fallback call per unresolved section or subsection.

Classification persistence also requires #19A structure persistence because the
classification artifact is cryptographically tied to that source. A structure,
classification, or artifact-write failure produces a bounded warning and does
not turn an otherwise usable filing into `ERROR`. Every new extraction attempt
invalidates both prior derived artifacts regardless of current flags, so a later
flag change cannot expose evidence from an older attempt.

## Versioned contracts

The API contract uses typed Pydantic models:

- `TocEntry`: raw and normalized title, canonical hint, numeric and original printed-page labels, source TOC page/text, confidence, range method, and parse warnings.
- `HeadingAnchor`: TOC entry, matched source reference/text, PDF/Azure page, score/method, bounding evidence, plausible alternatives, and warnings.
- `DocumentPageMapping`: distinct PDF index, Azure number, printed number/label and numbering scheme, offset, method, confidence, anchor, and review state.
- `DocumentSection`: title/type, TOC and anchor references, authoritative printed/PDF/Azure page ranges, separate optional start/end heading bounding geometry and offsets, range-consistency evidence, hierarchy fields, review state, and source-content reference lists.
- `DocumentContentEvidence`: bounded artifact-scoped text, all source pages, bounding evidence, source indexes, and provenance for every referenced paragraph, line, table, cell, or normalized row.
- `DocumentContentDisposition`: explicit ambiguous or unassigned terminal state with reason, candidate sections, singular and multi-page evidence, and compact provenance.
- `DocumentStructureResult`: feature version, detection evidence, entries, anchors, mappings, sections, the content-evidence catalog, warnings, conservation/safety evidence, and generation time.

The full Azure response is not copied. Because the current database does not persist raw Azure layout blocks, the versioned artifact stores only the bounded evidence needed to resolve its artifact-scoped references. When an existing normalized row is persisted, all section/disposition/catalog references are replaced with that row's database UUID while its original candidate ID remains in provenance.

## Phase A algorithms implemented by #19A

### TOC detection

Detection is document-wide and deterministic; it does not assume the TOC is on the first or second page. Evidence includes:

- exact or OCR-normalized `INDEX`, `CONTENTS`, or `TABLE OF CONTENTS`;
- `Page`, `Pages`, or `Page No.` column text;
- repeated title plus terminal page/range patterns;
- known financial-report section aliases;
- density of short title/page rows.

Equivalent table-row, paragraph, and line evidence is de-duplicated before scoring while numeric source order is retained. Detection chooses one strongest explicit `INDEX`/`CONTENTS` seed (or one strongest heading-less fallback) and derives a single contiguous block from it. It no longer preselects unrelated high-density pages elsewhere in the document. Continuation expansion is bounded around that seed: the adjacent page requires plausible page-reference continuity, a repeated page column, or another heading; later pages additionally require known-section evidence and remain capped. Continuations never become recursive seeds. The artifact records the selected block start/end and termination reason. A document with no reliable candidate returns `toc_detected=false`, creates no sections, and preserves the entire content inventory as unassigned.

### TOC entry parsing and title normalization

The parser handles:

- Arabic and canonical Roman page labels;
- single starting pages and explicit ranges;
- Unicode hyphen, en dash, em dash, minus, and narrowly scoped OCR separators;
- leading Arabic/Roman enumeration;
- dotted leaders and page-column text;
- uppercase and title-case input.

An accepted TOC entry must have a valid trailing page label/range and a credible title inside the active TOC block. Two consecutive non-entry lines terminate that block. Address, company-number, contact/account-detail, date/year, standalone numeric/Roman, subparagraph-marker, punctuation-only, stop-word-only, and one/two-character fragment patterns are rejected. Rejected source lines remain in the document content inventory for conservation, but they are not `TocEntry` records and cannot create anchors or structural sections.

Title normalization uses NFKC cleanup, removes Azure DI `:selected` and
`:unselected` presentation markers from semantic comparison text, checks exact
aliases first, applies a bounded standard-library fuzzy threshold second, and
uses `unknown_section` when unresolved. The original Azure line remains intact
in `TocEntry.source_text`; only the parsed semantic title is cleaned. The same
semantic cleanup is shared by TOC, canonical section, heading-anchor, and Notes
heading comparison. The canonical foundation types include directors' reports,
director statements, statutory declarations, auditor reports, primary financial
statements, Notes, company information, and unknown sections. Plain
`income_statement` remains distinct from combined comprehensive-income wording.

### Range inference

Explicit ends remain explicit. A start-only entry normally ends at the immediate next TOC entry's start minus one. Entries sharing a starting page within the same numbering scheme retain overlapping same-page ranges and a duplicate-start warning so heading evidence can divide the page. Decreases and Roman-to-Arabic changes are explicit reset/regime warnings rather than backward inference. A final range may end only at a reconciled document end in the same scheme. Every inferred range carries an explicit method; it is never indistinguishable from an explicit range.

### Heading anchors and page reconciliation

Candidate headings are taken from non-TOC Azure paragraphs and lines. Reusable heading-quality rules reject empty, numeric, Roman-only, stop-word-only, section-marker, and short-fragment candidates before layout signals can add confidence. Core title tokens remove stop words and normalize only an explicit safe set of financial-heading singular/plural pairs (`director(s)`, `auditor(s)`, `statement(s)`, `report(s)`, `flow(s)`, and `account(s)`). Missing distinctive core tokens therefore reject `DIRECTORS` for Statement by Directors and `FINANCIAL STATEMENTS` for Notes.

Matching is tiered: A exact normalized title; B exact canonical alias, controlled singular/plural equivalent, or canonical title prefix with a recognized trailing qualifier/date; C strong fuzzy match with bidirectional meaningful-token coverage and a reasonable length ratio; D substantial containment with complete or substantially complete expected core coverage. Canonical-prefix examples include `STATEMENT BY DIRECTOR PURSUANT TO`, `STATUTORY DECLARATION PURSUANT TO`, `INDEPENDENT AUDITORS' REPORT TO THE MEMBERS OF ...`, and `NOTES TO THE FINANCIAL STATEMENTS - 31 DECEMBER 2024`. Candidate-token dilution from a legitimate trailing qualifier does not negate full expected-core coverage.

Selection is deterministic and lexical-tier-first: A, then B, then C, then D. Within a tier it sorts by lexical score, expected-core coverage, heading quality, provisional-regime distance, layout-enhanced score, physical page, and source ID. Layout cannot make C/D beat A/B. Paragraph/line copies at the same location collapse, while spatially distinct or cross-page alternatives remain auditable.

Each `HeadingAnchor` exposes tier/method, lexical score, expected/candidate/token and core-token coverage, missing expected core tokens, length ratio, heading-quality score, `trusted`, rejection reason, confidence, alternatives, and bounded rejected-candidate diagnostics. Only same-tier cross-page near-ties create ambiguity; a weaker lower-tier alternative cannot suppress a stronger selection. Only trusted, non-near-tie anchors participate in the initial page-regime consensus. A selected trusted near-tie anchor may be retained afterward as start geometry only when its page agrees with an independently robust mapped TOC start. It never establishes or replaces the full page range. Thus fragments such as `TO`, `SE`, `(e)`, `(i)`, and `1` cannot anchor long section titles.

For an anchor:

`offset = pdf_page_index - printed_page_number`

Thus printed page 11 on PDF index 13 produces offset `+2`.

Anchor resolution uses two passes. Pass 1 chooses A/B evidence to derive a provisional offset per numbering scheme when at least two high-trust anchors provide at least 72% weighted support. Pass 2 re-ranks every lexically trusted candidate using distance from its entry's predicted PDF page before layout evidence. Proximity never rescues a lexically invalid candidate. Final consensus is then recalculated only from final trusted selections.

Trusted anchors use tier/confidence weights: exact canonical headings outrank exact aliases/prefixes, which outrank strong fuzzy and substantial-containment evidence. Weighted support, dominant offsets, trusted/rejected counts, inconsistent trusted counts, and competing high-quality offsets are retained in the alignment summary. A dominant regime with at least two anchors, at least 72% weighted support, and no competing offset supported by two high-quality anchors may project ranges without review. Repeated continuation-header near ties remain visible, but do not make that regime ambiguous when their selected first-page anchors agree with the dominant offset. Rejected and low-weight noise cannot make an otherwise stable regime ambiguous. A single anchor remains a review-required proposal. Same-tier plausible cross-page alternatives are excluded from offset consensus. Multiple Roman/Arabic or reset regimes are projected only when each contiguous regime has at least two supporting anchors; unsafe conflicts still produce `page_alignment_ambiguous` and stop broad projection.

Cover pages and other prefatory pages remain explicitly unmapped when they have no printed Arabic page in the reconciled regime. Roman labels and resets remain separate evidence rather than being silently mixed into an Arabic global offset.

### Section grouping and conservation

For a reliable alignment, a resolved printed TOC start/end projected through
unique page mappings is authoritative. Page ownership is stored only in
`pdf_page_start` / `pdf_page_end` and `azure_page_start` / `azure_page_end`.
Heading positions are stored separately in `start_heading_bbox`,
`start_heading_offset`, `end_heading_bbox`, and `end_heading_offset`. A heading
confirms the mapped start, refines a legitimate shared-page transition, or
helps when mappings are missing; it cannot collapse a reliable multi-page
range or replace either endpoint with an off-regime page.

The final consistency validator compares every uniquely mapped printed range
with the stored PDF range. `range_consistency` exposes the expected and observed
ranges, observed boundary sources, safe-reconciliation decision, and dimensions
including `start_page_conflict`, `end_page_conflict`, `range_collapsed`,
`off_regime_anchor`, and `missing_endpoint_mapping`. A contradiction is
reconciled to a sufficiently supported mapping, or cleared and marked
`section_range_conflicts_with_page_mapping` when safe reconciliation is
impossible. It does not force endpoints from a single anchor, an inconsistent
regime, duplicate printed labels, or low-confidence mappings.

Finalized ranges also report full-page gap, unintended overlap, and legitimate
same-page geometry-boundary counts. Consecutive explicit ranges remain owned by
their TOC endpoints. A next-section heading can provide end geometry only on a
genuine shared page; it cannot truncate the preceding range.

Heading geometry refines overlapping same-page sections. Tables spanning multiple sections remain ambiguous at table level; cells and normalized rows may still be assigned when their own page/geometry is decisive. TOC-source content is explicitly unassigned and never enters a financial statement section.

Every inventoried paragraph, line/heading, table, cell, and normalized row has a resolvable content-evidence record and ends in exactly one state:

- referenced by one section;
- explicitly ambiguous between candidate sections; or
- explicitly unassigned with a reason.

The analyzer checks pairwise-disjoint terminal sets and requires:

`inventory = assigned union ambiguous union unassigned`

A failed conservation check aborts the optional analysis and is isolated from extraction.

The safety summary also reports `assignment_rate`, `ambiguity_rate`,
`unassigned_rate`, `dropped_rate`, assignment/unassigned rates excluding
TOC-excluded evidence, explicit/resolved-range projection counts, and
section/page-mapping conflict/reconciliation counts. The read-only real-PDF evaluator at
`scripts/report_toc_aware_real_pdf_smoke.py JOB_ID` loads only validated
#19A/#19B/#19C artifacts, performs no provider/database/mapping mutation, and
emits `excessive_unassigned_content` as an evaluator warning when a valid TOC,
high-confidence alignment, and resolved primary ranges still leave more than
half of eligible evidence unassigned. It also reports selected exact/prefix/
fuzzy/partial anchors, stronger-alternative inversions, off-regime selections,
Notes range and child-page distribution, and range-projection consistency. Hard
smoke gates require zero stronger-alternative inversions, unresolved range
conflicts, Notes children outside their parent, and dropped evidence. This is a
smoke-quality gate, not a universal production job-failure threshold.

### Local developer smoke workflow

Routine local artifact diagnosis does not require Swagger, a bearer token,
`curl`, or an authenticated API request. Use the normal product path to upload
or reprocess a filing, wait until the filing reaches `REVIEW`, then run:

```powershell
.\.venv\Scripts\python.exe -B scripts\diagnose_toc_pipeline_job.py JOB_ID
```

Use `--json` when the same read-only result needs to be archived or shared. The
utility loads effective flags through the same `config.settings` object used by
FastAPI and Celery, performs SELECT-only optional job metadata queries, discovers
current and stale local #19A/#19B/#19C artifacts, validates their version/hash
linkages, and reports the complete #19C execution/persistence gate set. Runs
created after `#19C-hotfix-0` also have durable stage evidence, so a missing
#19C artifact reports an exact stable skip/failure reason and the execution-time
safe configuration. Legacy runs without that artifact still report
`diagnosis: UNKNOWN` and list the missing evidence instead of guessing.

The command never calls an HTTP endpoint, Azure, an LLM, or Supervisor; it does
not build or persist mappings, mutate the database or template fields, generate
XBRL, or run Arelle. Exit codes are `0` complete/healthy, `1` pipeline problem,
`2` incomplete/missing artifact, `3` invalid job/input, and `4` diagnostic
failure.

### Pipeline execution observability

Every production Azure-DI run now creates the bounded operational artifact:

`uploads/document-structures/job_{job_id}/pipeline_execution_status.json`

It is separate from #19A/#19B/#19C mapping outputs and is replaced atomically
for each retry. The production control flow is:

```text
process_azure_di_filing_job
  -> AzureDocumentIntelligenceProvider.analyze_pdf_path
  -> _run_local_normalization
  -> analyze_document_structure                         [#19A analysis gate]
  -> _persist_candidates + attach_persisted_extracted_row_ids
  -> analyze_template_classification                    [#19B analysis gate]
  -> persist_document_structure                         [#19A persistence gate]
  -> persist_template_classification                    [#19B persistence gate]
  -> source_rows_from_normalized_candidates
  -> build_document_initial_mapping
       -> load/validate #19A and #19B sources
       -> build_taxonomy_concept_inventory
       -> retrieve_section_aware_candidates             [retrieval phase]
       -> run_bounded_initial_mapping_llm               [mapping phase]
  -> persist_initial_mapping                            [publication phase]
       -> serialize -> temp write -> atomic rename -> validate
  -> commit FilingJob.REVIEW
```

The REVIEW commit occurs only after #19C has either published or durably
recorded why it was skipped/failed. Optional-stage failures still do not erase
successful extraction rows or mutate accepted mappings.

The status artifact records `started`, `completed`, `skipped`, or `failed` for
Azure extraction, normalization, #19A analysis/persistence, #19B
classification/persistence, #19C candidate retrieval, #19C mapping build, and
#19C persistence. #19C persistence separately records `writer_invoked`,
`serialization_completed`, `atomic_temp_write_completed`, `rename_completed`,
and `post_write_validation_completed`. Error evidence is limited to a stable
reason, a bounded fixed summary, and the exception class; exception text and
payload bytes are not stored.

Candidate retrieval additionally records bounded row-isolation metrics:
source rows received, structurally skipped rows, eligible/attempted/successful
rows, rows with zero safe candidates, locally failed rows, and stage-fatal
error count. At most 100 local error records are retained, each containing only
the persisted row identifier, a whitelisted reason code, and a sanitized
exception class. No label, source value, arbitrary exception message, or stack
trace is written to execution telemetry.

Stable reasons are `feature_disabled`, `persistence_disabled`,
`upstream_structure_missing`, `upstream_structure_invalid`,
`upstream_classification_missing`, `upstream_classification_invalid`,
`upstream_hash_mismatch`, `registry_hash_mismatch`,
`concept_inventory_unavailable`, `row_limit_exceeded`, `zero_eligible_rows`,
`candidate_retrieval_failed`, `mapping_build_failed`,
`artifact_serialization_failed`, `artifact_write_failed`,
`artifact_validation_failed`, `artifact_missing_after_publication`,
`upstream_requires_review`, and `unexpected_exception`.

The safe configuration snapshot contains only the extraction pipeline, TOC
feature/persistence/live-mode booleans, #19C mode, and bounded row/candidate/
concurrency/timeout settings. It never includes provider keys, API/bearer
tokens, database passwords, credential-bearing Redis URLs, model payloads, or
financial data. A canonical sorted-JSON SHA-256 is stored as `safe_config_hash`.
The local diagnostic recomputes the current hash and reports `MATCH` or
`DIFFERENT`, with differences limited to those same whitelisted fields. This
makes a worker that retained pre-restart settings diagnosable without Swagger,
an auth token, or a provider call.

`requires_human_review=true` and
`section_range_conflicts_with_page_mapping` are not #19C execution gates.
They remain visible in #19A and propagate review warnings into advisory #19C
rows. The diagnostic lists each conflict's section/title, printed range,
projected PDF range, stored PDF range, conflict reason, reconciliation state,
and whether it blocks downstream execution. #19C remains advisory throughout.

### Notes preparation

`notes_to_financial_statements` is one primary section with:

- `parent_section_id = null`;
- `section_level = 1`;
- stable `section_order`;
- retained candidate numbered note-heading references.

#19A does not create or classify child note sections.

#19B scopes Notes evidence to the #19A parent range. Evidence crossing a Notes
boundary is ambiguous rather than assigned to a child, and every emitted Notes
child range is validated to remain inside its parent container. This makes
correct parent-range projection the primary protection against cover-page
headings becoming false Notes children.

## Persistence model

#19A uses a versioned result artifact rather than four new relational tables. The fixed path is owner-indirectly scoped by the filing job:

`uploads/document-structures/job_{job_id}/structure_19a_v4.json`

Properties:

- the payload is validated against `DocumentStructureResult`;
- size is bounded;
- a unique temporary file plus atomic replace prevents partial reads;
- the fixed job/version path gives clear retry upsert semantics and prevents duplicates;
- the artifact is written after extraction rows have stable flushed IDs and before the final REVIEW commit;
- a failed new analysis/write discards any stale prior artifact;
- every processing retry invalidates the previous attempt's artifact even when #19A is disabled;
- normal and admin job deletion include the derived artifact in existing owned cleanup;
- the endpoint validates embedded job and feature identity before returning it.
- availability is limited to owned jobs in `REVIEW` or `COMPLETED`; processing/error jobs cannot expose a stale result.

`19A-v4` is a deliberate artifact-version increment because persisted page
ownership, geometry, consistency diagnostics, and repeated-header regime
semantics changed. Legacy `structure_19a_v1.json`, `structure_19a_v2.json`, and
`structure_19a_v3.json` files are never loaded as v4. #19B embeds the structure
version and SHA-256, and #19C embeds both structure and classification hashes,
so a v3 source or any v4 source change makes old downstream artifacts stale. Processing retry already
invalidates the fixed #19A, #19B, and #19C derived artifacts before extraction;
atomic fixed-name replacement prevents duplicate derived rows/files and does not
mutate confirmed mappings or legacy production results.

A later phase may migrate the versioned JSON into a single job-owned database artifact table or fully normalized TOC/section tables. That migration should add a job foreign key with cascade deletion, attempt/version identity, source snapshot hash, and transactional upsert. Full Azure payload duplication is not planned.

## Read-only API

Both endpoints first enforce the existing normal-user owned-job check:

- `GET /api/v1/filings/jobs/{job_id}/document-structure/capabilities`
- `GET /api/v1/filings/jobs/{job_id}/document-structure`

Capabilities expose the three flags, deterministic mode, feature version, persisted-result state, availability, and configuration warnings. The result endpoint returns only a validated available artifact. Cross-owner and legacy-null-owner jobs remain hidden with `404`.

No frontend route, panel, navigation item, or normal-user diagnostics surface is added.

## Failure behavior

- No reliable TOC: successful result with `toc_not_detected`; existing filing continues.
- Low-confidence/malformed TOC: source evidence and warnings are retained.
- Missing anchor: a range may still use a unique reliable printed-page mapping; otherwise it remains unresolved.
- Ambiguous alignment: broad projection is stopped; exact anchors and ambiguous/unassigned content remain.
- Analyzer exception: bounded task warning; existing persistence/mapping continues.
- Artifact exception: bounded task warning, stale artifact discarded, existing persistence/mapping continues.
- Flags disabled: analyzer and artifact writer are not called; only stale derived-artifact invalidation occurs, and current extraction/mapping behavior is unchanged.

## Planned architecture

### Phase A — TOC and document structure

Implemented by #19A: deterministic TOC detection, entry parsing, title normalization, heading anchors, page alignment, lossless section grouping, Notes preparation, safe artifact/API, and compatibility guards.

### Phase B — section and note-subsection classification

Implemented by #19B and advanced to `19B-v2` by #19B-hotfix-1. It validates and converts the canonical registry
into `TemplateGroupCard` records before classification. Legacy display labels
never replace official role semantics, and any registry/source/hash mismatch
fails closed.

Primary routing uses the #19A canonical section type plus bounded section
evidence. Narrative sections return `narrative_only` with zero assignments. The
Notes primary section creates the code-less `notes_container` outcome. Mutually
exclusive financial-position, profit/loss, comprehensive-income, and cash-flow
variants require explicit method/tax evidence; insufficient qualifiers return
`ambiguous` with alternatives rather than selecting by code order.

Notes children are segmented from #19A heading and content evidence. Arabic,
Roman, nested alphabetic, split-line, unnumbered, OCR-noisy, same-page, and
multi-page headings are supported. The v2 deterministic quality layer combines
number plausibility, lexical/sentence shape, character and word ratios,
capitalization, punctuation, repeated-page position, Azure heading roles,
geometry, and table overlap. Running headers, company boilerplate, page markers,
watermark fragments, standalone units, numeric table fragments, and numbered
prose remain evidence but cannot create independent boundaries.

Paragraph/line duplicates at the same page position collapse by compatible note
number and normalized title. A repeated `(continued)` number/title extends the
existing logical child and retains every contributing heading evidence ID and
boundary position. Different note numbers with the same words remain distinct.
Child IDs are a deterministic hash of parent ID plus stable logical number/title
identity, so inserting rejected boilerplate does not renumber later children.

Paragraph, table, cell, heading, and extracted-row evidence within the Notes
range ends assigned, ambiguous, or unassigned. Leading Notes boilerplate is
attached to the first accepted logical child. Pairwise-disjoint terminal sets are
enforced and dropped content must be zero. Tables continuing onto a later page
remain with the prior note when their geometry precedes a new heading; unresolved
crossings remain ambiguous. The artifact and developer diagnostic expose raw and
accepted candidate counts, duplicate/continuation merges, rejection categories,
attached extracted rows, zero-meaning children, conservation, and dropped count.

Child classification runs in this order: exact eligible canonical label/alias,
official wording, deterministic title/context indicators, optional bounded LLM,
then explicit ambiguous/unassigned. Zero, one, and multiple assignments are
supported. `730000` remains the taxonomy leaf `Notes - List of notes`; `740000`
is issued capital; `750000` is related-party transactions.

The bounded fallback receives only the section title/range, nearby headings,
limited paragraphs/table headers/row labels, canonical cards, and
do-not-confuse guidance. Character and collection limits are configurable and
omissions are counted. It never receives auditor XML/XBRL, benchmark expected
IDs, evaluation labels, taxonomy qname answers, or final mappings. Output must
be strict JSON with known registry IDs. Unknown IDs, invalid JSON, invalid
outcome/assignment combinations, and empty matched outcomes fail closed. There
is no recursive retry.

The fixed classification artifact is:

`uploads/document-structures/job_{job_id}/template_classification_19b_v2.json`

It uses atomic replace, bounded size, fixed job/version identity, #19A artifact
version/hash, canonical registry version/hash, stale-source rejection, retry
invalidation, and existing owned cleanup. It never overwrites the #19A artifact.
The v1 filename is stale after the logical-child identity/segmentation semantic
change. #19C loads only the current #19B artifact and binds its own artifact to
the current classification version and semantic hash, so a v1-linked #19C result
fails closed until the pipeline is rerun; candidate scoring and ranking are
unchanged.

Owned read-only endpoints are:

- `GET /api/v1/filings/jobs/{job_id}/template-classification/capabilities`
- `GET /api/v1/filings/jobs/{job_id}/template-classification`

They enforce ownership, `REVIEW`/`COMPLETED` status, artifact identity, source
hash, and registry hash. #19B adds no frontend route, panel, navigation item, or
normal-user diagnostics surface.

## Canonical MPERS template-group registry

Before Phase B classification, #19B-blocker-1 reconciled the complete 24-code
inventory in:

`taxonomy/template_group_registry_mpers_2022_v1.json`

The authority order is fixed:

1. the bundled official taxonomy role URI, role ID, and role definition;
2. the bundled presentation-role structure and concepts;
3. the versioned canonical repository registry derived from that evidence;
4. user-friendly display labels;
5. compatibility aliases.

`mpers_templates.json` remains the executable source for the exact 24-code
membership and concept payload. `XBRLTemplateService` validates that inventory
against the canonical registry and bundled role/linkbase files before applying
semantic metadata. A duplicate code, conflicting role, missing definition,
concept-membership drift, wrong taxonomy version, or known swapped label fails
registry validation.

### Taxonomy semantics versus display labels

`official_role_definition` and `canonical_name` represent taxonomy semantics.
`user_display_name` is product wording. `description` remains the compatible API
display field and now uses `user_display_name`. Historical runtime descriptions
are aliases only; they do not override canonical meaning and must never drive a
mapping migration.

Durable identity is the six-digit `code`, with `role_uri` as the secondary
technical identifier. Human-readable names are not durable. A label change does
not reassign confirmed mappings, change template field values, or rewrite
persisted `statement_type` rows. Review Workspace grouping resolves historical
labels through aliases and displays the reconciled label.

### Structural navigation versus taxonomy templates

Review Workspace navigation nodes may be structural. Taxonomy template groups
must correspond to actual canonical roles. The Notes parent is therefore:

`notes_container`

It is a code-less `structural_navigation_container`, has no role URI, and
produces the Phase B outcome `container_only`. It is not a 25th template and no
taxonomy code was invented for it.

Code `730000` is separately and explicitly the official taxonomy role
`Notes - List of notes`. Its presentation role is rooted at
`ssmt-mpers:DisclosureOfNotesAndOtherExplanatoryInformationAbstract` and contains
83 generic note-disclosure concepts. It remains a real `note_list`
`leaf_template`. The historical label `Notes to Financial Statements` resolves
to `730000` only for persisted-row grouping and is excluded from future parent
section classification.

Code `740000` retains its code and role URI but has canonical meaning
`Notes - Issued capital` and display label `Issued Capital Note`. The incorrect
historical label `Notes - Information on Companies` is a non-classifying
compatibility alias.

Code `750000` retains its code and role URI but has canonical meaning
`Notes - Related party transactions` and display label
`Related Party Transactions`. The incorrect historical label
`Notes - Reports` is a non-classifying compatibility alias.

### Inventory versioning and compatibility

The registry declares source taxonomy version `SSMxT_2022v1.0`, semantic
inventory version `mpers-2022-v1`, complete provenance, ordered concept-membership
hashes, and a deterministic semantic inventory hash. Any future taxonomy version
requires a new versioned registry and explicit reconciliation; an existing
version must not be silently repointed.

The deterministic command is:

`python -B scripts/validate_template_group_registry.py`

It compares the canonical registry with the bundled role XSD, presentation and
calculation linkbases, and runtime template inventory, and returns nonzero on
mismatch. It is local-only: it does not call a model/provider, open a database
session, mutate a mapping, generate XBRL, or execute Arelle.

### Phase C — section-aware taxonomy candidate retrieval

Implemented by #19C as a disabled-by-default advisory mapping foundation. The
current persisted contract is `19C-v2`. It loads and revalidates the persisted #19A and #19B artifacts
before doing any work. A source-structure, classification, registry, or concept
inventory hash mismatch fails closed and no #19C result is exposed.

The allowed concept universe is derived in this exact order:

1. the canonical template-group IDs assigned by #19B;
2. exact concept membership in `mpers_templates.json` for those codes;
3. datatype, period type, balance, abstract, nillable, and substitution-group
   metadata from the four bundled MPERS taxonomy schemas;
4. role URI, statement family, presentation variant, and classification
   semantics from the canonical 24-group registry.

Display labels never grant membership. `notes_container` remains code-less and
cannot produce a concept universe. Narrative, container, not-applicable,
classification-failed, ambiguous, and unassigned sections do not produce fact
mappings. Multiple valid assignments use the bounded union of only those
assigned groups and retain each contributing group on every concept card.

`services/section_aware_taxonomy_concept_cards.py` builds 923 deterministic
local `TaxonomyConceptCard` records for the current inventory. Cards include
qname/local name, standard and optional label forms, documentation when
available, schema fact metadata, exact group/code/role membership, statement
families, parent/child/path evidence, bounded aliases and indicators,
do-not-confuse collisions, taxonomy version, and local provenance. The card
inventory hash is deterministic. No provider, reference XBRL, benchmark answer,
correctness label, or evaluation verdict participates. Abstract, axis, member,
hypercube, table, and line-item structural concepts are not selectable facts.

Every normalized source row is retained with either its persisted extracted-row
UUID or a namespaced normalization candidate identity. Eligibility is explicit:
`fact_candidate`, `subtotal_candidate`, `total_candidate`, `heading_only`,
`table_header`, `continuation_label`, `narrative_row`, `empty_value`,
`duplicate_row`, `structural_only`, `unsupported`, or
`ambiguous_eligibility`. Headings and empty rows may remain bounded context but
are not automatically mapped.

The row context carries only its section/subsection, assignment, label,
current/prior values and years, available unit/currency/sign/indentation,
bounded ancestors/siblings/children, table headers, nearby evidence, and Top-K
cards. Defaults are 12,000 characters, four siblings, three ancestors, three
descendants, two nearby paragraphs, and eight cards. Truncation and omitted
counts are explicit; an impossible character bound fails closed. It never sends
an entire PDF or Notes section.

`#19C-hotfix-0b` separates row-local preparation failures from systemic
contract failures. Redundant deterministic score-reason strings are the first
candidate metadata removed when a context exceeds its character cap; candidate
identities, numeric scores, rank/order, and all Top-K candidates remain intact.
If an individual row still cannot be prepared or scored safely, its candidate
outcome is `retrieval_failed`, the row requires human review, no concept is
selected, and independent rows continue. Unassigned, ambiguous, narrative, and
container classifications remain safe non-eligible rows. Unknown group scope
returns no safe candidates and never broadens to the 923-card inventory.

Registry loading/linkage, concept-inventory construction or malformed-index
failures, upstream artifact identity/hash failures, invalid source identity,
and row-limit violations remain stage-fatal. The read-only local replay command
is:

`python -B scripts/diagnose_candidate_retrieval_job_19c.py --job-id 68`

It joins current structure evidence to persisted extracted rows, runs
`deterministic_only` candidate retrieval/mapping in memory, makes zero provider
calls, and never invokes the artifact writer or mutates the database.

Candidate scoring is deterministic and auditable. It combines label/local-name
and alias similarity, optional documentation, section and exact group
compatibility, datatype and period compatibility, hierarchy/sibling/value
shape, total behavior, and indicator penalties. The score is a rank, not a
correctness probability. Incompatible group concepts never enter scoring;
incompatible period types and structural/dimension concepts are excluded.
Current/non-current versus liquidity, function versus nature, before-tax
versus net-of-tax, and direct versus indirect presentations remain separated by
the #19B group assignment. Ties sort by qname. Top-K is configurable with a hard
maximum of 20 and defaults to eight. An empty compatible set returns
`no_safe_candidate`; it never broadens to the full taxonomy.

Exact duplicates and same-label competing source rows are recorded separately,
including page/table context differences and review requirements. The first
exact source may receive a deterministic advisory recommendation; later exact
duplicates are retained as `duplicate_row`. No row overwrites another.

### Phase D — bounded initial Mapping LLM

Also implemented by #19C. Supported modes are `deterministic_only`, `mock_llm`,
and `live_llm`; the safe default is `deterministic_only`, which makes zero
provider calls. Mock mode requires an injected backend/test client. Live mode
requires the initial-mapping and live-provider flags and reuses the approved
Hugging Face Qwen mapper client with its rate-limit retries forced to zero.
Concurrency defaults to one, each eligible row has one bounded timeout, and at
most one provider call is made. There is no repair or recursive retry.

The external payload boundary recursively rejects auditor/reference XML,
parsed or generated XBRL, benchmark/gold mappings, expected/correct qnames,
correctness/evaluation labels or verdicts, hidden decisions,
`confirmed_tag_id`, and final mappings. Full taxonomy files and unrelated
sections are never included. Production financial payloads and raw responses
are not logged or persisted; the artifact retains only provider/model, one-way
prompt hash, and bounded result metadata.

The provider must return one strict JSON object with exactly the seven response
keys. `mapped` must identify one supplied candidate and its exact qname;
alternatives must also be supplied and are deduplicated. Unknown concepts,
unknown qnames, mismatched ID/qname pairs, duplicate/unknown JSON keys, invalid
confidence, extra prose, invalid JSON, and selected concepts on abstention fail
closed as `validation_failed`. Provider exceptions and timeouts become
`provider_failed`. All results require human review; mapped does not mean
accepted, confirmed, final, or safe to auto-apply.

The fixed atomic artifact is:

`uploads/document-structures/job_{job_id}/initial_mapping_19c_v2.json`

Its 128 MiB hard bound is based on 5,000 rows times eight compact cards at an
estimated 2.5 KiB per card (about 100 MiB) plus result metadata. It binds to the
#19A version/hash, #19B version/hash, registry version/hash, taxonomy version,
concept inventory hash, retrieval version, and prompt version. Retry and job or
account deletion remove it. A #19C analysis or write failure removes only #19C,
adds a structured warning, preserves #19A/#19B and existing production results,
and allows the usable filing to remain in `REVIEW`.

Owned read-only endpoints are:

- `GET /api/v1/filings/jobs/{job_id}/initial-mapping/capabilities`
- `GET /api/v1/filings/jobs/{job_id}/initial-mapping`
- `GET /api/v1/filings/jobs/{job_id}/initial-mapping/rows/{row_id}`

They enforce ownership, eligible job status, all artifact identities, and stale
source rejection. #19C adds no frontend route or panel. It does not populate a
template field, write an AI suggestion, modify `confirmed_tag_id`, create a
final mapping, generate XBRL, or run Arelle.

#### #19C semantic retrieval v2

The current retrieval contract is `19C-section-aware-retrieval-v2`, persisted
under mapping contract `19C-v2`. It preserves each raw source label unchanged
and derives a separate auditable semantic label for ranking. The derived copy
may remove only leading `Add`/`Less` presentation markers and trailing
evidence-backed OCR/watermark tokens (`DISCUSSION`, `DRAFT`, `WIE`). It also
canonicalizes `non-current`, `non current`, and `noncurrent` without treating
`noncurrent` as `current`.

Ranking uses deterministic finance-phrase and semantic-family evidence. It
explicitly contrasts current/noncurrent, asset/liability,
receivable/payable/reserve, ordinary income or profit/expense/OCI, and
tax asset/liability/expense. Total/subtotal agreement is a positive signal;
abstract concepts, dimensions, text concepts for numeric rows, incompatible
period types, and concepts outside the classified canonical template groups
remain nonselectable. Balance metadata remains supporting evidence only.

The retriever never broadens a template group to obtain a plausible label. If
the source semantic family has no supported selectable concept in the
authoritative template membership, the candidate set records an explicit
`semantic_scope_limitation` and deterministic mapping abstains. Related
concepts remain visible for human review but cannot become a forced mapping.
For template 420000, the authoritative role contains comprehensive-income/OCI
concepts plus `ProfitLoss`; it does not contain the ordinary P&L detail concepts
for revenue, cost of sales, gross profit, employee/operating expenses, other
income, profit before tax, or ordinary tax expense.

The developer-only command
`python -B scripts/audit_candidate_ranking_19c.py <job_id>` performs SELECT-only
local reconstruction and prints the complete pre/post-filter pool for every
eligible row. It reports raw and semantic labels, section/subsection/template
context, every candidate's full card and score breakdown, and explicit
exclusion reasons. It performs no authentication bypass against an API because
it exposes no route, makes no provider call, publishes no artifact, and mutates
neither database nor source document.

The false-default controls are
`TOC_AWARE_TAXONOMY_CANDIDATE_RETRIEVAL_ENABLED`,
`TOC_AWARE_INITIAL_MAPPING_ENABLED`,
`TOC_AWARE_INITIAL_MAPPING_PERSISTENCE_ENABLED`, and
`TOC_AWARE_INITIAL_MAPPING_LIVE_LLM_ENABLED`. Mode, model, Top-K, row cap,
timeout, concurrency, minimum score, and context collection/character bounds
are separately configurable. When the controls are absent, existing production
behavior is unchanged.

### Phase E — direct draft template population

Return the initial mapping draft directly to the corresponding editable template field. Draft population is not confirmation.

### Phase F — inline tag and value editing

The user can edit both taxonomy tag and extracted value directly in the template, with mapping and source provenance available in context.

### Phase G — user-triggered AI review

The user may click one AI review action. One Supervisor review evaluates the current draft. Only when the Supervisor identifies a concrete correctable issue may its bounded feedback be sent once to the Mapping LLM for at most one conditional remap. The revised draft returns to the same template field.

There is no recursive review/remap loop, no auto-accept, and no automatic final mapping.

### Phase H — accessible normal-user Review Workspace

The Review Workspace becomes the primary and only normal-user review surface. The user reviews and edits directly in the template.

The final normal-user experience has:

- no separate AI Mapping Suggestions panel;
- no separate Supervisor queue panel;
- no separate remapping panel;
- no technical workflow navigation between AI panels.

### Phase I — comparison and controlled cutover

Compare old and new pipelines on quality, safety, completeness, latency, and reviewer effort. Retire or hide legacy AI panels only after parity and controlled cutover evidence are accepted.

## Human authority

Human save/confirmation remains authoritative throughout all phases. AI output is always a draft or advisory review. There is no auto-accept, no automatic final mapping, and no automatic XBRL filing decision.
