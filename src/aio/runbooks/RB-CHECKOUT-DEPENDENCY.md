---
runbookId: RB-CHECKOUT-DEPENDENCY
owner: checkout-oncall
---

# Checkout Dependency Failure

Trigger: checkout-to-payment error ratio exceeds 5% with a non-zero payment-span denominator.

1. Confirm the span name matches payment and the value is a ratio, not a raw error count.
2. Inspect the earliest failing payment span and matching payment logs.
3. Check payment readiness, restarts, endpoints, rollout, and checkout symptoms.
4. If payment evidence is absent, remove the attribution and escalate as unknown checkout failure.
5. Attach the exact PromQL, trace, log window, and customer impact to `payments-oncall`.

Verify recovery: payment-span errors remain below threshold for two fresh cycles and checkout short-window success recovers. Missing payment spans are inconclusive.

Prohibited: changing the payment failure flag, forcing a payment, or restarting payment without owner approval.
