---
runbookId: RB-CHECKOUT-SLO
owner: checkout-oncall
---

# Checkout SLO Breach

Trigger: rolling-24h checkout bad ratio is greater than 1% with real PlaceOrder traffic.

1. Confirm numerator, denominator, capture time, and verified signal quality; no traffic is not a healthy zero.
2. Quantify failed orders and error-budget consumption, then freeze risky changes while the budget is exhausted.
3. Inspect checkout dependency span errors/latency and recent deployments; attach the most relevant trace and logs.
4. Route a supported dependency failure to its owner, otherwise keep cause `unknown` and page `checkout-oncall`.

Verify recovery: current short-window failures stop and the rolling-24h ratio trends back within 1%. Record both values; the 24h window may remain breached after the active fault ends.

Prohibited: changing `flagd`, clearing evidence, or claiming recovery from missing telemetry.
