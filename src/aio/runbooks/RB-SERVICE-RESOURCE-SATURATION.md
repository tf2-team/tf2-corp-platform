---
runbookId: RB-SERVICE-RESOURCE-SATURATION
owner: platform-oncall
---

# Service Resource Saturation

Confirm that the affected service has a user-visible SLO breach before acting on
the resource signal.

1. Compare CPU, memory, disk I/O, socket I/O, and ready-pod history with request
   rate over the same window.
2. Check whether the resource change precedes the latency or error-rate impact.
3. Inspect pod restarts, throttling, limits, node pressure, and dependency health.
4. Treat low absolute utilization without corroborating impact as diagnostic
   evidence, not as an incident.
5. Escalate or resize only after the resource signal and user impact are
   correlated.
