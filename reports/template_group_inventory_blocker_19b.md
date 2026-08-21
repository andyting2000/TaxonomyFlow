# #19B canonical template inventory blocker

Status: **BLOCKED**

Feature #19B stopped at Part 1 because the repository does not currently expose one internally consistent semantic definition of its 24 template groups.

## Finding

- Classification: `confirmed_issue`
- Severity: `high`
- Affected area: template inventory, section classification, persisted `statement_type` labels, and Review Workspace grouping
- Blocks later features: yes

The executable inventory is `mpers_templates.json`, loaded by `XBRLTemplateService`. It provides exactly 24 IDs, concepts, and role URIs. Its raw descriptions are placeholders, so the service replaces them with `FRIENDLY_TEMPLATE_DESCRIPTIONS` before APIs and downstream mapping use them.

The bundled SSM MPERS taxonomy role definitions and each template's actual concepts are internally consistent, but two active runtime names are materially wrong:

| Code | Active runtime name | Bundled taxonomy meaning | Concept evidence |
| --- | --- | --- | --- |
| `740000` | Notes - Information on Companies | Notes - Issued capital | Disclosure of issued capital |
| `750000` | Notes - Reports | Notes - Related party transactions | Disclosure of related parties |

`730000` is also material to #19B: the runtime name `Notes to Financial Statements` resembles a parent container, while the official role is `Notes - List of notes`. The requested architecture requires the Notes parent to remain `container_only`.

## Exact 24-code comparison

| Code | Runtime display name | Bundled taxonomy definition | Existing family |
| --- | --- | --- | --- |
| `020000` | Scope of Filing | Scope of filing | scope |
| `120000` | Directors Report | Disclosure - Directors report | directors_report |
| `120100` | Statement by Directors | Disclosure - Statement by directors | statement_by_directors |
| `120200` | Director Business Review | Disclosure - Director business review | director_business_review |
| `130000` | Auditors Report | Disclosure - Auditors report to members | auditors_report |
| `210000` | Statement of Financial Position | Statement of financial position, by current/non-current method | financial_position |
| `210100` | Sub-classification of Assets, Liabilities and Equity (Current/Non-Current) | Sub-classification of assets, liabilities and equity, by current/non-current method | financial_position |
| `220000` | Statement of Financial Position (Order of Liquidity) | Statement of financial position, by order of liquidity method | financial_position |
| `220100` | Sub-classification of Assets, Liabilities and Equity (Order of Liquidity) | Sub-classification of assets, liabilities and equity, by order of liquidity method | financial_position |
| `310000` | Statement of Profit or Loss (By Function) | Statement of profit or loss, by function of expense | profit_or_loss |
| `310100` | Analysis of Profit or Loss (By Function) | Analysis of profit or loss, by function of expense | profit_or_loss |
| `320000` | Statement of Profit or Loss (By Nature) | Statement of profit or loss, by nature of expense | profit_or_loss |
| `320100` | Analysis of Profit or Loss (By Nature) | Analysis of profit or loss, by nature of expense | profit_or_loss |
| `410000` | Statement of Comprehensive Income | Statement of Comprehensive Income - Net of tax | comprehensive_income |
| `420000` | Statement of Comprehensive Income (Before Tax) | Statement of Comprehensive Income - Before tax | comprehensive_income |
| `510000` | Statement of Cash Flows (Direct Method) | Statement of cash flows, direct method | cash_flows |
| `520000` | Statement of Cash Flows (Indirect Method) | Statement of cash flows, indirect method | cash_flows |
| `610000` | Statement of Changes in Equity | Statement of Changes in Equity | changes_in_equity |
| `620000` | Statement of Retained Earnings | Statement of Retained Earnings | changes_in_equity |
| `710000` | Notes - Corporate Information | Notes - Corporate information | corporate_information |
| `720000` | Notes - Significant Accounting Policies | Notes - Summary of significant accounting policies | accounting_policies |
| `730000` | Notes to Financial Statements | Notes - List of notes | notes |
| `740000` | Notes - Information on Companies | Notes - Issued capital | notes |
| `750000` | Notes - Reports | Notes - Related party transactions | notes |

## Authority decision required

The audit supports this source split, but applying it changes active runtime semantics and needs an explicit compatibility plan:

1. Use `XBRLTemplateService` and `mpers_templates.json` for membership, concepts, and role URIs.
2. Use bundled taxonomy role definitions and concepts for semantic meanings.
3. Use `TEMPLATE_CODE_FAMILY` only as existing family evidence.
4. Create one versioned card adapter after reconciliation; do not copy or fork the 24 IDs.
5. Preserve compatibility aliases for historical `statement_type` values and Review Workspace grouping.
6. Resolve the #19B narrative/container policy without changing inventory membership.

The repository also lacks canonical `template_kind`, aliases, expected section types, positive/exclusion indicators, assignment multiplicity, and a semantic inventory version. These fields cannot be safely invented while the active meanings conflict.

## Verification and safety

- Runtime inventory count: 24
- `mpers_templates.json` SHA-256: `892024B5869BA983ACDE86DBF0E940F78DCB35459422455F21E8935DA19C6E5A`
- MPERS role XSD SHA-256: `145BF4A40885BF2F6145121B805161EE94FB177150CD2FEA200E91D0E825872A`
- Three independent read-only audits agreed the conflict blocks #19B.
- No classifier, feature flag, pipeline, frontend, database, or mapping code changed.
- No Azure, LLM, XBRL, Arelle, mapping, `confirmed_tag_id`, or final-mapping action occurred.

## Decision

#19B is blocked at Part 1. The next feature is:

`#19B-blocker-1 - Reconcile the canonical internal template-group inventory`

#19C was not started.
