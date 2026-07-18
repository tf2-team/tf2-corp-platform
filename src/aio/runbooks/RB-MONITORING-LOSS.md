---
runbookId: RB-MONITORING-LOSS
owner: platform-oncall
---

# Monitoring Loss

Trigger: a required Prometheus signal is missing, stale, invalid, or returns more than one series where one aggregate was required.

1. Identify the affected query ID and quality reason from the event.
2. Run the query directly and inspect target/scrape health, labels, unit, sample timestamp, and series count.
3. Check the OTel Collector and Prometheus before investigating the application.
4. Keep every dependent health/anomaly conclusion unknown until the signal is restored.
5. Escalate query/collector ownership to `platform-oncall` with the failing expression and timestamps.

Verify recovery: the exact signal returns one fresh, semantically valid series for two cycles. A synthetic `vector(0)` is not valid recovery evidence.

Prohibited: substituting zero, suppressing no-data incidents, or modifying `flagd`.
