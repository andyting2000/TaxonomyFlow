# Supervisor Quality Smoke Interim Assessment

## Status

Five live Supervisor reviews completed, but only two were correction-eligible. The quality smoke remains open at **2/5 actual revisions**.

## Revision Outcomes

### Tax expenses for the year

- Initial and revised qname: `ifrs-smes:IncomeTaxExpenseContinuingOperations`
- Classification: **still_ambiguous**
- The response is structurally valid and remains human-review-only.
- It acknowledges the statement-family mismatch but then asserts that tax expense can routinely appear in cash flows without distinguishing tax expense from cash tax paid.
- No remaining ambiguity was recorded even though the mismatch remains unresolved.

### Cash flows from investing activities

- Initial: `ifrs-smes:OtherInflowsOutflowsOfCashClassifiedAsInvestingActivities`
- Revised: `ifrs-smes:CashFlowsFromUsedInInvestingActivities`
- Classification: **improved**
- The revised qname better represents the whole investing-activities cash-flow row.
- Net/gross and missing row-role ambiguity were retained appropriately.
- The phrase “The alternative candidate is overly narrow” is internally unclear after selecting the preferred alternative, but it does not invalidate the qname improvement.

## Agree Outcomes

Trade receivables, beginning-period cash, and other income all received `agree` outcomes. The correction control was correctly withheld, no revision was created, and zero correction attempts were consumed.

The other-income review remained not safe to accept because the mapper-confidence guardrail withheld the advisory safe flag.

## Persistence And Safety

- 5/5 initial snapshot hashes unchanged
- 2 separate completed revision records
- Both revisions use `correction_attempt=1`
- Both require human review and are not safe for auto-apply
- Zero `confirmed_tag_id`, template mapping, Accept/Reject, or final mapping mutations

Three more actual revisions are required before Phase 3 can close the quality smoke.
