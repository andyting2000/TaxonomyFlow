# Supervisor-Guided Remapping Case Selection

## Phase 1 Status

Five cases are selected. Phase 2 is waiting for manual card-level UI actions.

The ingestion/Celery gate already passed and was not repeated. PostgreSQL contains 35 pending suggestions across fresh jobs 59-61, but no current Supervisor reviews or guided revisions. No live Supervisor or mapper call was made during selection.

## Coverage

- Filings: Bezlife, Fine Batik, INFO House
- Jobs: 59, 60, 61
- Statement families: Cash Flows, Financial Position, Profit or Loss
- Categories: statement-family mismatch, period/context mismatch, concept scope mismatch, preferred alternative, ambiguous/generic row
- Intended behaviors: at least one qname change, at least one retained qname, and at least one abstention

## Selected Cards

### 1. INFO House - Tax expenses for the year

- Job: `61`
- Row ID: `384594c5-8f64-4ec8-b7e0-8cc3f717523f`
- Suggestion ID: `c3d67b79-9543-4018-9dd1-85e7c60d56f2`
- Statement: Statement of Cash Flows
- Initial: `ifrs-smes:IncomeTaxExpenseContinuingOperations` - Tax expense
- Confidence: `0.85`
- Category: statement-family mismatch
- Selection reason: every candidate is a profit-or-loss concept despite the cash-flow context. A better candidate request or abstention is safer than forcing the current candidate.
- Existing Supervisor outcome: none
- Current correction eligibility: no, `missing_supervisor_review`

### 2. Bezlife - Cash and cash equivalents at beginning of year / period

- Job: `59`
- Row ID: `9e1c42a9-db17-4130-a007-ee149543ca5d`
- Suggestion ID: `38feda38-bec0-427e-a28d-f5d258adb081`
- Statement: Statement of Cash Flows
- Initial: `ifrs-smes:CashAndCashEquivalents` - Cash and cash equivalents at end of period
- Confidence: `0.93`
- Category: period/context mismatch
- Selection reason: the row says beginning of period while candidate metadata says end of period. The qname may remain defensible if the period is represented through context, so this tests better justification rather than requiring a qname change.
- Existing Supervisor outcome: none
- Current correction eligibility: no, `missing_supervisor_review`

### 3. Fine Batik - Trade receivables

- Job: `60`
- Row ID: `26a44a6f-bc75-4727-9507-0df28e9e7393`
- Suggestion ID: `144bcaa2-a328-42f4-a133-49905aa6411d`
- Statement: Statement of Financial Position
- Initial: `ssmt-mpers:TradeReceivables` - Total trade receivables
- Confidence: `0.97`
- Category: concept family/scope mismatch
- Selection reason: alternatives span total trade receivables, trade-and-other current receivables, and current trade receivables, but the persisted row has no current/non-current section qualifier. The confidence needs scope scrutiny.
- Existing Supervisor outcome: none
- Current correction eligibility: no, `missing_supervisor_review`

### 4. Fine Batik - Cash flows from investing activities

- Job: `60`
- Row ID: `e5304cca-d3a9-4f76-acae-1a6af42e0266`
- Suggestion ID: `38b4306a-0fae-47b6-af5a-ead713204c39`
- Statement: Statement of Cash Flows
- Initial: `ifrs-smes:OtherInflowsOutflowsOfCashClassifiedAsInvestingActivities`
- Confidence: `0.65`
- Category: preferred alternative/disagreement
- Preferred alternative to review: `ifrs-smes:CashFlowsFromUsedInInvestingActivities`
- Selection reason: the row is a whole investing-activities cash-flow line, while the selected concept is restricted to other inflows/outflows. This is the strongest bounded qname-change case.
- Existing Supervisor outcome: none
- Current correction eligibility: no, `missing_supervisor_review`

### 5. Bezlife - Add : Other income

- Job: `59`
- Row ID: `ecca68af-d1db-4784-9246-72dc2dba1dc7`
- Suggestion ID: `790e39da-f6dc-42a7-9b2b-8d0b6a1e52fd`
- Statement: Statement of Profit or Loss
- Initial: `ifrs-smes:OtherIncome` - Total other income
- Confidence: `0.86`
- Category: ambiguous/generic row
- Selection reason: the generic additive row was mapped to a total summary concept, and the bounded candidates contain no specific other-income subtype. Retention with an explicit limitation or abstention is safer than forced confidence.
- Existing Supervisor outcome: none
- Current correction eligibility: no, `missing_supervisor_review`

## Manual UI Actions

Process only these five cards. Do not use **Run Supervisor reviews for all**.

For each card:

1. Open the named job and locate the card by exact row label and initial qname.
2. Click **Run Supervisor review** and confirm the live advisory request.
3. Wait for the persisted decision and issues.
4. If **Re-run mapping with Supervisor feedback** appears, click it exactly once.
5. If it does not appear, record the decision; the review was not correction-eligible.
6. Do not Accept or Reject the initial suggestion and do not attempt a second correction yet.

All five initial rows currently have `confirmed_tag_id=null`, no template mapping, no Supervisor review, and no revision. Initial snapshot hashes are recorded in the JSON report for the Phase 3 immutability comparison.

## Safety

- No automatic Supervisor execution or remapping
- No provider call during selection
- No database/job or mapping mutation
- No auto-apply, auto-accept, or auto-reject
- No `confirmed_tag_id` or final mapping mutation
- No auditor XML, parsed XBRL facts, benchmark gold qname, target answer, or evaluation label sent externally
- No XBRL generation or Arelle

The feature remains active. After the five manual card workflows are complete, Phase 3 will inspect persisted reviews/revisions, run one retry-limit check, compare immutable snapshots, and classify quality.
