# Additional Supervisor-Guided Remapping Cases

Three additional cases are selected to move the quality smoke from two to five actual revisions.

## 1. Bezlife - Tax expenses for the year

- Job: `59`
- Row ID: `17436c9e-aa0f-4bdb-a586-e2d8b96985ea`
- Suggestion ID: `9f5b310d-4b6f-4b4e-82fe-2d488554f769`
- Initial: `ifrs-smes:IncomeTaxExpenseContinuingOperations`, confidence `0.85`
- Likelihood: **high**
- Reason: this repeats the proven cash-flow versus profit-or-loss statement-family mismatch.

## 2. INFO House - Cash flows from investing activities

- Job: `61`
- Row ID: `1d8fdcf9-ff8d-40cb-8d7f-5a2585fa4060`
- Suggestion ID: `7ad8e410-6198-462b-8424-21d17d0ed4c3`
- Initial: `ifrs-smes:OtherInflowsOutflowsOfCashClassifiedAsInvestingActivities`, confidence `0.60`
- Alternative: `ifrs-smes:CashFlowsFromUsedInInvestingActivities`
- Likelihood: **high**
- Reason: this repeats the proven broad-substitute pattern with a closer bounded alternative.

## 3. Bezlife - TOTAL EQUITY AND LIABILITIES DRAFT WIE

- Job: `59`
- Row ID: `c442f08d-11d1-4e91-9a98-7560bb552d7f`
- Suggestion ID: `681f1ed0-721f-4a26-8a67-ef275cb5811a`
- Initial: `ifrs-smes:EquityAndLiabilities`, confidence `0.85`
- Likelihood: **medium**
- Reason: trailing OCR/source text and unexplained context make this an ambiguous-label/source-conflict test.
- Caveat: if the Supervisor agrees and no correction control appears, a replacement case will be needed.

## Manual Actions

For each named card:

1. Click **Run Supervisor review**.
2. Wait for the persisted review.
3. If eligible, click **Re-run mapping with Supervisor feedback** exactly once.
4. Wait for **Correction attempt 1 completed**.
5. Do not use the batch action, Accept, Reject, or a second correction attempt.

No provider call or runtime mutation was performed during selection.
