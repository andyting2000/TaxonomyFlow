# Job 68 candidate-retrieval failure — #19C-hotfix-0b

Status: **PASS for implementation and read-only replay; production post-fix rerun is NOT_RERUN.**

Job 68 failed before mapping build and publication because
`_trim_to_character_limit` raised `ValueError: Row mapping context cannot fit
the configured character limit`. In the original normalized-candidate order,
the first trigger was row `f77723f8-9bb8-4748-bd2c-dbff4889bd9f`, candidate
26, label `Turnover`, in matched section `section-6`, template group `420000`,
statement family `comprehensive_income`. Its eight-card payload remained 12,455
characters after the legacy trim against a 12,000-character cap. No source
financial values are included here.

All 25 eligible contexts initially exceeded the cap. The legacy trimmer reduced
15 successfully, but 10 `420000` contexts remained oversized because repeated
deterministic score-reason strings were not removable. Candidate scoring,
sorting, inventory lookup, #19A/#19B linkage, configuration, and persistence
were not the cause.

The row-shape audit found 26 rows without section context, 10 ambiguous rows,
36 unassigned rows, 5 narrative rows, and 51 rows with no template group; all
were safely non-eligible. There were no duplicate row IDs, missing labels,
rows with both values absent, multiple-group rows, unknown current
classification IDs, or cards missing datatype/period metadata. Four duplicate
or competing-label diagnostics were retained for review but did not trigger the
runtime failure.

The fix trims only those redundant reason strings when needed. It preserves all
eight candidate identities, numeric scores, rank/order, and candidate scope.
Unexpected row-specific preparation failures now become fail-closed
`retrieval_failed` abstentions; systemic registry/inventory/upstream failures
remain stage-fatal.

The read-only Job 68 replay completed 76/76 rows: 51 structural/non-eligible,
25 eligible/attempted/successful, zero local failures, zero zero-candidate rows,
and zero stage-fatal errors. Decisions were 2 mapped advisory suggestions, 15
ambiguous, 8 abstain, and 51 structural-only. Provider calls and every mutation
count were zero. The replay did not invoke persistence or modify Job 68.

One final fresh production PDF rerun is required to prove the deployed worker
publishes `initial_mapping_19c_v1.json`; the expected three #19C stages are all
`completed`.
