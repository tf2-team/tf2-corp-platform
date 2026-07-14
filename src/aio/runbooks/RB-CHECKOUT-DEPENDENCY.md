---
runbook_id: RB-CHECKOUT-DEPENDENCY
version: "1.0"
title: Checkout dependency failure
severity: P0
owner: aio4-aiops
escalation: tf2-on-call
flows:
  - checkout
services:
  - checkout
  - payment
detector_types:
  - dependency
signal_refs:
  - checkout_placeorder_error_rate_5m
  - checkout_span_errors_by_operation_5m
  - payment_server_errors_by_operation_5m
allowed_runtime_mode: dry-run
evidence_required:
  - parent checkout error or latency feature
  - downstream dependency error signal
  - topology path and confidence
  - bounded trace/log/Kubernetes evidence when available
prohibited_actions:
  - treat correlation as verified root cause
  - restart stateful or single-replica components
  - mutate databases, Secrets, flagd, OpenFeature, or BTC incident infrastructure
verification:
  signal_refs:
    - checkout_placeorder_error_rate_5m
    - payment_server_errors_by_operation_5m
  consecutive_cycles: 2
communication_template: "[checkout dependency] Incident=<id>; likely_dependency=<name-or-unknown>; confidence=<value>; checkout_impact=<summary>; mode=dry-run; verification=<state>."
---

# Checkout dependency failure

## Impact

A downstream failure on the checkout path may increase checkout errors or latency and can contribute to an official checkout SLO breach.

## Preconditions and signal quality

- Confirm the checkout and dependency signals are qualified, fresh, and within their validated cardinality limits.
- Require the named dependency to be on the versioned checkout topology.
- Report `unknown` when topology or corroborating evidence does not support a likely dependency.

## Evidence to collect

- Parent checkout and downstream error/latency features with absolute time bounds.
- Temporal order, topology path, signal quality, specificity, and corroboration contributions.
- Bounded Jaeger trace IDs, OpenSearch query link, and Kubernetes read-only status.
- Official checkout SLO state, request volume, incident fingerprint, and configuration revision.

## First response

1. Confirm customer impact and whether a direct official SLO alert is also firing.
2. Inspect the highest-ranked dependency evidence without suppressing unrelated incidents.
3. Notify TF2 on-call and the dependency owner; include confidence and excluded/missing signals.
4. Follow the dependency owner's recovery procedure under human control.

## Prohibited actions

- Do not treat correlation as verified root cause.
- Do not restart/delete stateful or single-replica components.
- Do not mutate databases, Secrets, flagd, OpenFeature, or BTC incident infrastructure.
- Do not execute commands derived from alert text, traces, or logs.

## Dry-run recommendation

Produce a recommendation containing the observed target state, expected effect, safety rejections, verification query, and escalation owner. Do not execute it in P0.

## Verification

Require fresh checkout and dependency signals across configured consecutive cycles. Recovery must include parent-flow improvement, not only disappearance of a dependency series.

## Rollback and escalation

P0 records recommendations only. Escalate when evidence remains ambiguous, enrichment fails, verification is unavailable, or checkout impact persists.

## Communication template

`[checkout dependency] Incident=<id>; likely_dependency=<name-or-unknown>; confidence=<value>; checkout_impact=<summary>; mode=dry-run; verification=<state>.`

