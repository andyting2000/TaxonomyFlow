# template_420000_candidate_audit_19c_hotfix_1

Analysis status: **PASS**

This is a deterministic, read-only Job 70 analysis. It made zero provider calls, did not publish a mapping artifact, and did not mutate the database or source document.

## First answer

- A — correct concept below old Top-8: 1
- B — correct concept filtered out: 0
- C — correct concept absent from 420000 membership: 9
- D — correct concept absent from the 923-card inventory: 0
- E — alternate qname/label finding: 1

## Full authoritative membership

| Position | QName | Label | Selectable | Exclusion |
| ---: | --- | --- | --- | --- |
| 0 | ssmt-mpers:DisclosureOnStatementOfComprehensiveIncomeBeforeTax | Disclosure on statement of comprehensive income before tax [abstract] | false | abstract_concept_not_selectable_for_fact |
| 1 | ifrs-smes:ConsolidatedAndSeparateFinancialStatementsAxis | Consolidated and separate financial statements [axis] | false | abstract_concept_not_selectable_for_fact |
| 2 | ifrs-smes:ConsolidatedMember | Group [member] | false | abstract_concept_not_selectable_for_fact |
| 3 | ifrs-smes:SeparateMember | Company [member] | false | abstract_concept_not_selectable_for_fact |
| 4 | ifrs-smes:ProfitLoss | Total Profit (Loss) | true |  |
| 5 | ifrs-smes:OtherComprehensiveIncomeBeforeTaxExchangeDifferencesOnTranslation | Other comprehensive income, before tax, exchange differences on translation | true |  |
| 6 | ifrs-smes:OtherComprehensiveIncomeBeforeTaxActuarialGainsLossesOnDefinedBenefitPlans | Other comprehensive income, before tax, actuarial gains (losses) on defined benefit plans | true |  |
| 7 | ifrs-smes:OtherComprehensiveIncomeBeforeTaxGainsLossesOnRevaluation | Other comprehensive income, before tax, gains (losses) on revaluation | true |  |
| 8 | ssmt-mpers:ShareOfOtherComprehensiveIncomeOfAssociatesAndJointVenturesAccountedForUsingEquityMethodThatWillNotBeReclassifiedToProfitOrLossBeforeTax | Share of other comprehensive income of associates and joint ventures accounted for using equity method | true |  |
| 9 | ssmt-mpers:OtherComprehensiveIncomeThatWillNotBeReclassifiedToProfitOrLossBeforeTax | Total other comprehensive income that will not be reclassified to profit or loss, before tax | true |  |
| 10 | ssmt-mpers:OtherComprehensiveIncomeBeforeTaxExchangeDifferencesOnTranslation | Other comprehensive income, before tax, exchange differences on translation | true |  |
| 11 | ssmt-mpers:OtherComprehensiveIncomeBeforeTaxChangesInFairValueOfHedgingInstrument | Other comprehensive income, before tax, change in fair value of hedging instrument | true |  |
| 12 | ssmt-mpers:ShareOfOtherComprehensiveIncomeOfAssociatesAndJointVenturesAccountedForUsingEquityMethodThatWillBeReclassifiedToProfitOrLossBeforeTax | Share of other comprehensive income of associates and joint ventures accounted for using equity method, before tax | true |  |
| 13 | ssmt-mpers:OtherComprehensiveIncomeThatWillBeReclassifiedToProfitOrLossBeforeTax | Total other comprehensive income that will be reclassified to profit or loss, before tax | true |  |
| 14 | ssmt-mpers:IncomeTaxRelatingToComponentsOfOtherComprehensiveIncomeThatWillNotBeReclassifiedToProfitOrLoss | Aggregated income tax relating to components of other comprehensive income that will not be reclassified to profit or loss | true |  |
| 15 | ssmt-mpers:IncomeTaxRelatingToComponentsOfOtherComprehensiveIncomeThatWillBeReclassifiedToProfitOrLoss | Aggregated income tax relating to components of other comprehensive income that will be reclassified to profit or loss | true |  |
| 16 | ssmt-mpers:OtherComprehensiveIncomeBeforeTaxGainsLossesOnOtherItems | Other comprehensive income before tax gains (losses) on other items | true |  |
| 17 | ifrs-smes:OtherComprehensiveIncome | Other comprehensive income | true |  |
| 18 | ifrs-smes:ComprehensiveIncome | Comprehensive income | true |  |
| 19 | ifrs-smes:ComprehensiveIncomeAttributableToOwnersOfParent | Comprehensive income, attributable to owners of parent | true |  |
| 20 | ifrs-smes:ComprehensiveIncomeAttributableToNoncontrollingInterests | Comprehensive income, attributable to non-controlling interests | true |  |
| 21 | ifrs-smes:ComprehensiveIncome | Comprehensive income | true |  |

## Semantic classifications

| Source label | Classification | Explanation |
| --- | --- | --- |
| Turnover | NO_CONCEPT_IN_TEMPLATE | The exact Revenue concept exists in inventory but has no 420000 membership. |
| Less : Cost of sales | NO_CONCEPT_IN_TEMPLATE | The exact CostOfSales concept exists in inventory but has no 420000 membership. |
| Gross profit | TOTAL_ONLY | GrossProfit is outside 420000; only the broader ProfitLoss total is present. |
| Staff costs | TOTAL_ONLY | The role has no staff/employee expense line; only the broader ProfitLoss total is present. |
| Other operating costs | TOTAL_ONLY | The role has no operating-expense line; only the broader ProfitLoss total is present. |
| Profit / (Loss) from operating activities | RELATED_SUPPORTED_CONCEPT | ProfitLoss is related but broader; the exact operating-activities concept is outside 420000. |
| Add : Other income | TOTAL_ONLY | OtherIncome is outside 420000; only the broader ProfitLoss total is present. |
| Profit / (Loss) before taxation | RELATED_SUPPORTED_CONCEPT | ProfitLoss is related but broader; ProfitLossBeforeTax is outside 420000. |
| Less : Taxation | NO_CONCEPT_IN_TEMPLATE | 420000 tax concepts apply to OCI components, not ordinary income-tax expense. |
| Total comprehensive profit / (loss) for the year / period | EXACT_SUPPORTED_CONCEPT | ComprehensiveIncome is an exact selectable 420000 member. |

No 420000 membership expansion is supported by the authoritative sources. Ordinary P&L semantics remain visible limitations and safely abstain; exact comprehensive income is ranked directly.
