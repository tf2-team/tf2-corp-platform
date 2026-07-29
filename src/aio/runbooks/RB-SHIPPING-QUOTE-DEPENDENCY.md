---
runbookId: RB-SHIPPING-QUOTE-DEPENDENCY
owner: checkout-oncall
---

# Shipping Quote Dependency

## Scope

Use this runbook when checkout or cart incidents point to shipping quote failures, quote latency, or checkout shipping path errors.

## First checks

- Check `shipping` and `quote` service health, error rate, latency, and recent deploys.
- Check checkout traces for the shipping/quote span and status code distribution.
- Check whether failures are regional, product-specific, or tied to downstream provider data.
- Check fallback behavior in checkout when quote is unavailable.

## Do not do

- Do not restart checkout if the dependency is clearly shipping/quote.
- Do not disable shipping quote logic without checkout owner approval.
- Do not mark checkout recovered before fresh checkout telemetry confirms it.

## Safe actions

- Page `checkout-oncall` and the owner of the failing shipping/quote service.
- Use dry-run restart recommendation only for the affected stateless service.
- Prefer rollback of the most recent shipping/quote deploy if the timeline matches.

## Escalation

Escalate with checkout trace ids, shipping/quote status codes, and recent deploy SHAs.

