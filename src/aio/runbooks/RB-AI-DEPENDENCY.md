---
runbookId: RB-AI-DEPENDENCY
owner: aie-oncall
---

# AI Dependency Failure

## Scope

Use this runbook when an incident points to `llm`, `external-llm`, `aws-bedrock`, `shopping-copilot`, `mem0`, or an AI provider dependency.

## First checks

- Check the AIOps incident root cause and confirm whether the affected path is retrieval, model inference, memory store, or provider access.
- Check `llm`, `shopping-copilot`, and `mem0` health, error rate, latency, and recent deploys.
- Check provider quota, throttling, timeout, auth, and network errors.
- Check fallback behavior so storefront/cart flows remain degraded gracefully rather than failing hard.

## Do not do

- Do not restart or scale external providers.
- Do not clear memory stores, vector indexes, or user context without AIE owner approval.
- Do not mark recovery on stale or missing telemetry.

## Safe actions

- Page AIE owner with incident id, failing route, provider/status code, and recent deploy SHA.
- Keep runtime action in dry-run unless a service-specific rollback and approval are present.
- Use local fallback or provider failover only if the feature flag and owner approval already exist.

## Escalation

Escalate to `aie-oncall`; include trace ids, provider error samples, request volume, and user-facing impact.

