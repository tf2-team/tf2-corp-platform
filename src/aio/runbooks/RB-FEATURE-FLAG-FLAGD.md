---
runbookId: RB-FEATURE-FLAG-FLAGD
owner: platform-oncall
---

# Feature Flag Failure

## Scope

Use this runbook when incidents involve `flagd`, `flagd-ui`, OpenFeature clients, stale flags, or fault-injection flag state.

## First checks

- Check flagd pod health, config source, sync status, and client error logs.
- Check whether the incident aligns with an intentional fault-injection flag.
- Check affected services for OpenFeature evaluation failures and fallback behavior.
- Check recent flag rollout, config map, secret, or GitOps changes.

## Do not do

- Do not restart or mutate flag infrastructure automatically.
- Do not flip feature flags from AIOps without explicit owner approval.
- Do not assume flag faults are production incidents until BTC/test flag state is checked.

## Safe actions

- Page `platform-oncall` with flag key, environment, affected service, and evaluation errors.
- Use page-only or dry-run recommendation unless a feature owner approves a flag revert.
- Prefer reverting the flag source of truth through GitOps or the approved flag workflow.

## Escalation

Escalate to service owner if a specific flag caused customer-impact behavior.

