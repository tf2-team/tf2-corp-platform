---
runbookId: RB-LOAD-GENERATOR
owner: platform-oncall
---

# Load Generator Issue

## Scope

Use this runbook when `load-generator` or synthetic traffic causes unusual request rate, worker failures, or misleading AIOps anomalies.

## First checks

- Check whether a load test is active and whether the target host/path is expected.
- Check load-generator master/worker health, expected worker count, and CPU.
- Compare service anomalies against traffic shape to separate real incidents from test load.
- Check if test flags or BTC mandates are intentionally injecting faults.

## Do not do

- Do not treat load-generator pressure alone as customer impact.
- Do not auto-remediate production services solely because synthetic load is high.
- Do not scale load-generator workers without checking cost and test owner.

## Safe actions

- Page `platform-oncall` or the active test owner.
- Stop or reduce test traffic only through the approved test control path.
- Annotate incidents as synthetic-load-related when confirmed.

## Escalation

Escalate with test id, target URL, worker count, and observed request rate.

