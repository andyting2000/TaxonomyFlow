# TOC boundary hardening #19A-hotfix-1

Status: **PASS** for deterministic implementation and regression coverage. Live Job 65 smoke: **NOT RERUN**.

## Defect and cause

The prior Job 65 artifact contained approximately 50 TOC entries even though the real INDEX had nine. Parsing continued into company-information, address, and later body content. Those false entries produced false boundaries and contributed to the previously observed approximately 81% unassigned-evidence rate.

The detector treated strong pages outside the physical INDEX as additional TOC pages, while the entry extractor retained weak or unparsed lines and had no shared title-quality gate.

## Hardening

Detection now selects one strongest explicit `INDEX`, `CONTENTS`, or `TABLE OF CONTENTS` seed and expands only through credible adjacent continuation pages. It records the bounded block start/end and termination reason, and warns when TOC-like candidates exist outside that block.

Entry extraction now requires a credible title and a valid trailing Arabic or Roman printed-page reference. It stops after two consecutive non-entry lines. Numeric-only, isolated Roman, one/two-character fragment, stop-word-only, address, company-number, contact/account, and date-like titles are rejected. Raw document evidence is still retained; rejected lines simply cannot become TOC boundaries.

## Result

The Job 65-style fixture retains exactly the nine real entries, selects only the INDEX page, and accepts zero suspicious body entries. Focused regressions cover bounded continuation, entry rejection, integrated grouping, and the smoke-report quality gate.

Verification passed: 65 focused #19A tests, 61 downstream #19B/#19C tests, 118 affected extraction/task/ownership/API tests, and all 1,420 backend tests. Application import exposed 89 routes; the canonical 24-template registry validated with zero errors.

No live provider call, database mutation, mapping mutation, frontend change, XBRL generation, or Arelle run occurred. A live result still requires reprocessing Job 65 into a `19A-v2` artifact.
