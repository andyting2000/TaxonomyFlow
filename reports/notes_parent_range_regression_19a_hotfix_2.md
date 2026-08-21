# Notes parent-range regression #19A-hotfix-2

Status: **PASS** for implementation and regression coverage. Fresh real-PDF smoke: **PENDING**.

Job 66 v2's reported 17 Notes subsections and passing conservation were a false success: the Notes parent was PDF `0-0`, so every child came from cover text such as the company number, company name, `DIRECTORS' REPORT AND`, `FINANCIAL STATEMENTS`, date text, and auditor contact details.

The primary fix is the #19A authoritative Notes parent range, PDF `16-23` / Azure `17-24`. The #19B boundary was hardened only with a containment invariant: fully inside evidence may create children, boundary-spanning evidence remains ambiguous, and an emitted child outside its parent fails closed. This does not redesign Notes semantics.

The Job 66 regression fixture emits nine Notes children distributed only across PDF pages 16-23 (`16:2`, then one child on each page 17-23). Zero children are outside the parent and zero come from page 0. All 17 Notes evidence items are assigned, none are ambiguous, unassigned, or dropped, conservation passes, and the smoke hard gates pass.
