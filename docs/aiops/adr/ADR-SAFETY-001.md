# ADR-SAFETY-001 - Remediation Safety Policy

> Status: Proposed - policy selected; required signatures and runtime evidence pending
> Owner: AIO4 remediation and operations owner
> Required reviewers: AIO4 runtime/integration owner; TF2 CDO owner
> Last updated: 2026-07-13

## Context

The Phase 3 response loop must reduce customer impact without creating excessive agency, bypassing BTC incident controls, violating the TF2 budget, or hiding failure behind an unverified automation claim. `ADR-LIVE-001` selects real dry-run as the current P0 mode and keeps a later one-action live transition gated.

## Decision

### Modes

| Mode | Kubernetes writes | Routing | Use |
|---|---|---|---|
| `observe` | None | Test/internal | Local and initial integration only |
| `dry-run` | None | Real TF2 route | Current P0 production choice |
| `live-approved` | One exact request through a separate executor | Real TF2 route | Disabled until the revised `ADR-LIVE-001` gate passes |

Every image and Helm values file defaults to `dry-run`. The ordinary runtime always uses a read-only ServiceAccount. Dry-run still evaluates the exact proposed request against current Kubernetes, SLO, error-budget, cost, cooldown, target, approval, verification, and rollback state, then records the result and escalates without mutation.

### Fail-closed policy order

1. Validate runtime mode and exact allow-listed action ID.
2. Validate current incident state and exact target match.
3. Reject protected, stateful, single-replica, broad, or multi-service targets.
4. Require verified multi-replica readiness and one-service blast radius.
5. Acquire the one-action lock; enforce cooldown and maximum attempts.
6. Require official error-budget permission and current cost permission where applicable.
7. Require approval digest/identity/expiry in live mode.
8. Require deterministic verification, timeout, and rollback.
9. Require every dependency and safety input to be available and fresh.
10. Persist the decision and exact gate inputs before execution or dry-run completion.

Any failed, missing, stale, ambiguous, or unavailable input blocks live execution and causes an attributable escalation.

### Always blocked

- flagd, OpenFeature, central flag source, or BTC incident-path mutation/bypass;
- database, schema, data, Secret, or credential mutation;
- restart/delete of stateful or single-replica workloads;
- wildcard, namespace-wide, cluster-wide, or multi-service mutation;
- concurrent live actions;
- scale changes without current cost evidence and CDO approval;
- actions without deterministic verification and rollback;
- expired, mismatched, fixture, or boolean-only approval;
- LLM-selected, LLM-approved, LLM-executed, or LLM-verified operations.

### Verification and outcomes

Verification uses predeclared qualified telemetry queries and consecutive fresh windows. Every response finishes as one of: `verified-recovered`, `rolled-back`, `failed`, `inconclusive`, or `escalated`. Missing telemetry is `inconclusive`, never success. A runtime restart never replays a previously executing mutation automatically.

## Evidence Required

- Owner/reviewer signatures and links to `ADR-LIVE-001` and the implementing policy revision.
- Unit tests for every rejection and ordering rule.
- Real-state dry-run output containing target, preconditions, gate results, proposed request, blast radius, verification plan, rollback plan, and final escalation.
- Runtime/chart proof that P0 has no mutation identity.
- Audit timeline reconstruction across notification failure and runtime restart.
- Verification pass, fail, stale, and unavailable scenarios.
- If live mode is later proposed: the complete additional evidence listed in `ADR-LIVE-001`.

## Consequences

- Safety behavior is deterministic, testable, and independent of any LLM explanation.
- Current P0 meets the planned response-loop scope through real dry-run and human escalation while live mutation remains accurately gated.
- Some incidents will require slower human/CDO handling; this is preferable to unsafe automated action under unknown state.

## Rollback And Revisit Conditions

- Safe rollback is always to `dry-run` with no executor mutation RoleBinding.
- Revisit only through a signed ADR change when one exact action has complete live evidence, least-privilege execution, verification, rollback, budget, and error-budget approval.
