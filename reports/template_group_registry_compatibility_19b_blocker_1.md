# Template-group registry compatibility

Status: **PASS**

Durable identity remains template `code` and `role_uri`. Human-readable labels
are not durable identifiers and are never used to migrate or reassign mappings.

## Behavior

- The 24 codes, role URIs, and concept memberships remain unchanged.
- No database migration or persisted-row rewrite is required.
- Existing `description` remains in the API; canonical, official, display,
  alias, kind, structural, family, and version fields are additive.
- Review Workspace grouping accepts legacy aliases but displays the reconciled
  user label.
- Confirmed mappings and template field values are not mutated.

## Legacy aliases

| Code | Legacy lookup aliases |
| --- | --- |
| 120000 | Directors Report |
| 130000 | Auditors Report, Audit Information |
| 210000 | Statement of Financial Position, Statement of Financial Position - Current/Non-Current |
| 210100 | Sub-classification of Assets, Liabilities and Equity (Current/Non-Current), Sub-classification - Current/Non-Current |
| 220000 | Statement of Financial Position (Order of Liquidity), Statement of Financial Position - Order of Liquidity |
| 220100 | Sub-classification of Assets, Liabilities and Equity (Order of Liquidity), Sub-classification - Order of Liquidity |
| 310000 | Statement of Profit or Loss (By Function), Statement of Profit or Loss - By Function |
| 310100 | Analysis of Profit or Loss (By Function), Analysis of Profit or Loss - By Function |
| 320000 | Statement of Profit or Loss (By Nature), Statement of Profit or Loss - By Nature |
| 320100 | Analysis of Profit or Loss (By Nature), Analysis of Profit or Loss - By Nature |
| 410000 | Statement of Comprehensive Income |
| 510000 | Statement of Cash Flows - Direct Method, Statement of Cash Flows - Direct |
| 520000 | Statement of Cash Flows - Indirect Method, Statement of Cash Flows - Indirect |
| 710000 | Notes - Corporate Information |
| 720000 | Notes - Significant Accounting Policies, Significant Accounting Policies |
| 730000 | Notes to Financial Statements |
| 740000 | Notes - Information on Companies |
| 750000 | Notes - Reports |

`Notes to Financial Statements` is retained for historical grouping only. It
must not classify the Notes parent as `730000`; that parent is the separate
`notes_container`.
