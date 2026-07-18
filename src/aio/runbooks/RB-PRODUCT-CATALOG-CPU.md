---
runbookId: RB-PRODUCT-CATALOG-CPU
owner: catalog-oncall
---

# Product Catalog CPU

Trigger: two confirmed baseline deviations in product-catalog CPU, measured in millicores.

1. Confirm the query output is in millicores and compare CPU with request rate, latency, errors, memory, and ready pods.
2. If request rate rose while latency/errors stayed normal, classify it as healthy load and continue observing.
3. If latency/errors or memory also deviate, inspect catalog traces and PostgreSQL activity before assigning cause.
4. Check pod throttling, readiness, restarts, replica count, and recent rollout.
5. Escalate database evidence to `data-platform-oncall`; otherwise attach the correlated service metrics to `catalog-oncall`.

Verify recovery: two fresh cycles have no confirmed CPU finding and customer-facing catalog latency/error signals are healthy. Missing CPU telemetry is inconclusive.

Prohibited: scaling or restarting solely from CPU, changing `flagd`, or comparing core values against millicore thresholds.
