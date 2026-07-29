---
runbookId: RB-MEM0-MEMORY-STORE
owner: aie-oncall
---

# Mem0 Memory Store Issue

## Scope

Use this runbook when `mem0` or the shopping-copilot memory path has latency, errors, unavailable storage, or bad retrieval behavior.

## First checks

- Check Mem0 health, dependency database status, and memory retrieval latency/error rate.
- Check shopping-copilot traces to see whether memory read/write is blocking user requests.
- Check auth, network, migrations, and recent image/config changes.
- Confirm whether fallback without memory is working.

## Do not do

- Do not delete memory data, PVCs, or backing database records.
- Do not run migrations or repair jobs without AIE owner approval.
- Do not mark recovery if memory writes are silently failing.

## Safe actions

- Page `aie-oncall` with failing operation, user impact, and dependency status.
- Disable memory-enhanced behavior only through approved feature flags.
- Keep AIOps action page-only unless a reviewed Mem0 recovery runbook exists.

## Escalation

Escalate to AIE and platform if backing database or network policy is implicated.

