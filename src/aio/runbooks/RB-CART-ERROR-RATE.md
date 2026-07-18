---
runbookId: RB-CART-ERROR-RATE
owner: checkout-oncall
---

# Cart Error Rate

Trigger: two confirmed deviations in the Cart span error ratio.

1. Re-run the tracked `cart.error_rate_5m` spanmetrics query and confirm a non-zero request denominator.
2. Inspect Cart error spans/logs and separate application failures from Valkey connectivity failures.
3. Check Cart and `valkey-cart` readiness, restarts, endpoints, and recent rollout.
4. Test one read-only cart health path; do not mutate a customer cart for diagnosis.
5. Escalate storage symptoms to `checkout-oncall`; otherwise attach the failing operation and trace to the incident.

Verify recovery: the detector is absent for two fresh cycles, the metric remains present, and cart success is at least 99.5% over the official window.

Prohibited: flushing Valkey, deleting cart data, changing `flagd`, or accepting an absent metric as a zero error rate.
