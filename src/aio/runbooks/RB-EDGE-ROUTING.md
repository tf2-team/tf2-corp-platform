---
runbookId: RB-EDGE-ROUTING
owner: platform-oncall
---

# Edge Routing Failure

## Scope

Use this runbook for `frontend-proxy`, ingress, Envoy, ALB/CloudFront path routing, or edge-to-frontend failures.

## First checks

- Check `frontend-proxy` pod health, route config, error rate, and p95 latency.
- Check frontend health separately to avoid blaming the proxy for upstream app failures.
- Check ingress, ALB/CloudFront, TLS/cert status, and recent routing changes.
- Check blocked/admin paths and whether the failure is path-specific.

## Do not do

- Do not restart `frontend-proxy` live without confirming blast radius.
- Do not change public routing, path blocks, or TLS settings directly from AIOps.
- Do not bypass security path policy to restore traffic.

## Safe actions

- Page `platform-oncall` with affected host/path, status codes, and proxy logs.
- Use dry-run recommendation only for proxy restart unless an approved rollout/rollback exists.
- If route config changed recently, prefer GitOps revert over manual patch.

## Escalation

Escalate to platform/infra if ALB, CloudFront, certificate, or DNS signals are involved.

