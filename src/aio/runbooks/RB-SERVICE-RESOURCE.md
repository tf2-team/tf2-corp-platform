# Service Resource Anomaly

Use this runbook when RCA identifies a service resource signal such as CPU, memory,
disk I/O, socket I/O, or workload readiness as the likely root cause.

## Checks

1. Confirm the metric is present and fresh; treat missing telemetry as monitoring loss.
2. Compare the affected service against its own recent baseline and request rate.
3. Inspect pod readiness, restarts, limits, throttling, node pressure, and recent deploys.
4. Check direct dependencies and traces before attributing customer impact.
5. Escalate when the resource anomaly is not corroborated by service-health evidence.

Do not restart stateful or protected services from this runbook.
