---
runbookId: RB-DATASTORE-VALKEY-CART
owner: checkout-oncall
---

# Valkey Cart Datastore Issue

## Scope

Use this runbook when incidents involve `valkey-cart`, cart/session cache errors, memory pressure, connection failures, or cart/checkout dependency symptoms.

## First checks

- Check `cart` and `checkout` error rate, latency, and dependency traces to Valkey.
- Check Valkey memory, evictions, connection count, CPU, and network errors.
- Check recent cart deploys, configuration changes, and TLS/auth secret rotation.
- Confirm whether customer cart data may be affected.

## Do not do

- Do not flush Valkey or delete keys as an automatic remediation.
- Do not restart stateful/cache infrastructure from AIOps.
- Do not scale callers aggressively if the cache is already saturated.

## Safe actions

- Page `checkout-oncall` and data/platform owner for Valkey.
- Use page-only action for protected datastore incidents.
- Consider temporarily reducing cart write pressure only through approved controls.

## Escalation

Escalate with cart error samples, Valkey metrics, and whether checkout placement is degraded.

