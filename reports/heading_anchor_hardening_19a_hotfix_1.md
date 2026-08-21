# Heading-anchor hardening #19A-hotfix-1

Status: **PASS** for deterministic implementation and regression coverage. Live Job 65 smoke: **NOT RERUN**.

## Defect and cause

Short fragments such as `TO`, `SE`, and `(e)` could previously anchor materially longer TOC titles. Containment/fuzzy scores could be amplified by layout evidence before the candidate had established lexical credibility, and anchor records did not make trust or rejection evidence explicit.

## Trust model

Matching is now lexical-first:

1. Tier A: exact normalized title.
2. Tier B: exact canonical alias.
3. Tier C: strong fuzzy match with lexical, token-coverage, and length-ratio thresholds.
4. Tier D: substantial containment with the same coverage and length safeguards.

Layout, heading role, top-of-page placement, and nearby page labels can strengthen an already credible match; they cannot rescue untrusted text.

Each anchor now exposes its tier, lexical score, bidirectional token coverage, length ratio, title-quality score, confidence, trust flag, rejection reason, and bounded rejected-candidate evidence. Rejected candidates do not vote in consensus, reserve a trusted anchor, or create a section boundary.

## Result

The Job 65-style fixture produces nine trusted anchors, zero fragment anchors, and `0.98` alignment confidence. Exact trusted examples include `STATEMENT OF FINANCIAL POSITION` and `NOTES TO THE FINANCIAL STATEMENTS`. Dedicated adversarial tests reject `TO` for Statement by Directors, `SE` for Statutory Declaration, and `(e)` for Notes, and prove that geometric placement cannot override weak lexical evidence.

All 65 focused #19A tests and all 1,420 backend tests passed. No live provider, mapping, confirmed-tag, or template-field mutation occurred.
