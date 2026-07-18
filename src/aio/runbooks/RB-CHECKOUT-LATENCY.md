---
runbookId: RB-CHECKOUT-LATENCY
owner: checkout-oncall
---

# Checkout Latency

Trigger: two confirmed baseline deviations on `checkout_p95_latency_5m`.

1. Confirm the incident contains two consecutive samples and verified signal quality.
2. Re-run the tracked `checkout.p95_latency.5m` PromQL and compare the last 30 baseline samples with the two confirmation samples.
3. Inspect the linked Jaeger checkout trace; rank downstream spans for cart, catalog, shipping, payment, and email by duration/error.
4. Check checkout readiness, restarts, replicas, and recent rollout. Do not restart a healthy pod only because latency is high.
5. Escalate to the owner of the earliest abnormal dependency; use `checkout-oncall` when evidence remains ambiguous.

Verify recovery: two fresh collection cycles produce no adaptive checkout-latency event and checkout success remains within its rolling-24h SLO. Missing telemetry is inconclusive, not recovery.

Prohibited: changing `flagd`, suppressing the detector, or treating no traffic/missing series as zero.
