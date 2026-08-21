# Page alignment and range application #19A-hotfix-1

Status: **PASS** on the deterministic Job 65-style regression. Live Job 65 smoke: **NOT RERUN**.

## Weighted consensus

Only trusted anchors can contribute to page alignment. Each vote is weighted by match tier, lexical confidence, token coverage, title quality, and anchor confidence. A dominant offset needs at least two anchors and at least 72% of trusted weighted support, with no competing offset supported by two or more tier A/B anchors. Roman and Arabic/reset regimes remain separate and require local support.

The fixture produces nine trusted anchors, no inconsistent trusted anchors, `8.928` weighted support for offset `+1`, and `0.98` alignment confidence. Human review is not required.

## Ranges and conservation

Reliable explicit ranges are applied completely. Printed Notes pages `15-22` map to PDF page indexes `16-23`, and the Notes section contains ten evidence references instead of zero.

Of 45 fixture evidence items, 28 are assigned, none are ambiguous, 17 are explicitly unassigned, and none are dropped. Assignment is `0.622222`; unassigned evidence is `0.377778`, materially below the reproduced approximately `0.81` Job 65 baseline. The residual cover/INDEX material remains conserved as unassigned evidence.

Same-page geometry splitting and piecewise page-number regimes remain covered by regressions. The smoke evaluator emits `excessive_unassigned_content` only when a valid TOC, alignment confidence of at least `0.80`, primary ranges, and an unassigned rate above `0.50` coexist; it warns without failing the processing job.

Verification passed across 65 focused #19A tests, 61 downstream #19B/#19C tests, and all 1,420 backend tests. A new real Job 65 artifact is required before reporting a live-PDF pass.
