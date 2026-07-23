---
runbookId: RB-SERVICE-RCA
owner: platform-oncall
---

# Service Root-Cause Investigation

Use the attached RCA metric as a lead, not as proof by itself.

1. Confirm the associated latency, error-rate, or error-budget impact.
2. Compare the candidate timestamp with the impacted service and its dependency
   path.
3. Corroborate the metric with logs, traces, pod state, and recent changes.
4. If no user-impact evidence exists, suppress the page and retain the finding
   for analysis.
