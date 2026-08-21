# Template-group inventory reconciliation (#19B-blocker-1)

Status: **PASS**

Canonical source: `taxonomy/template_group_registry_mpers_2022_v1.json`

Semantic inventory hash: `16de7eaeafcdf760c7f4869072a6b0a3925088f6bc260672389b5c502015b7d4`

## Result

- Canonical template groups: 24 / 24
- Non-exact comparisons: 20
- Semantic/structural corrections: 5
- Validation errors: 0
- #19B may resume: true

## Authority

1. Bundled official taxonomy role URI and definition.
2. Bundled presentation-role structure.
3. Canonical repository registry derived from the taxonomy.
4. User display labels.
5. Compatibility aliases.

## Resolutions

- `730000`: 730000 is the official generic note-disclosure list role. The code-less notes_container is the Review Workspace parent.
- `740000`: `Notes - Issued capital`; display label `Issued Capital Note`.
- `750000`: `Notes - Related party transactions`; display label `Related Party Transactions`.
- Structural Notes parent: code-less `notes_container`, `container_only`, and not part of the 24 taxonomy roles.

## Verification

- Focused canonical registry tests passed: 25 tests in 0.119s.
- Targeted template service, mapping, Review Workspace API, ownership, document structure, taxonomy metadata, and XBRL validation regressions passed: 110 tests in 13.277s.
- Frontend authenticated helper and Review Workspace source regressions passed: 30 tests.
- Frontend production build passed: 1,586 modules transformed.
- Full backend discovery passed: 1,342 tests in 44.413s.
- Changed Python files passed py_compile.

## Recommendation

19B-resume - Resume section and note-subsection classification using the canonical 24-template registry
