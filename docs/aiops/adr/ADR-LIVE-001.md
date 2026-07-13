# ADR-LIVE-001 - Current Dry-Run Mode And Later Live-Remediation Gate

> Status: Proposed - current mode selected; required signatures pending
> Owner: AIO4 AIOps sub-team
> Required reviewers: TF2 CDO owner; AIO4 remediation owner; AIO4 runtime/integration owner
> Last updated: 2026-07-13

## Context

Phase 3 requires a continuously operating incident-response automation loop. It also requires safety checks, blast-radius control, verification, rollback or escalation, least privilege, auditability, SLO protection, and budget control. Enabling Kubernetes writes without those controls would create a larger operational risk than the incidents AIOps is intended to mitigate.

At the inspected chart revision `6c49c645a03922d763dd77e54cfe1db6227eaf16`, no AIOps workload, separate executor, approval provider, or exact AIOps mutation Role exists. No live target, action, cost state, or verification/rollback plan has yet been approved with deployed evidence.

## Decision

### Current P0 mode

The selected P0 mode is `dry-run`.

Dry-run is a real production operating mode, not a mock. It must continuously use real TF2 telemetry and routing to perform:

```text
Detect -> Qualify -> Correlate -> Create/update incident
       -> Evaluate every safety gate
       -> Record the exact non-mutating action proposal
       -> Evaluate the predefined verification queries
       -> Audit and escalate to the human owner
```

The ordinary `aiops-runtime` ServiceAccount remains namespace-scoped read-only, cannot read Secrets, and cannot mutate application resources. The dry-run chart contains no executor workload, mutation Role, or mutation RoleBinding.

### Later Phase 3 live-remediation transition

Live remediation is deferred, not removed from the Phase 3 plan. The team treats one gated live action as the later acceptance target for its full Phase 3 live-remediation demonstration; it will not claim that live-remediation target while the system operates in dry-run. The team will evaluate and enable at most one exact live action later only after all requirements below are satisfied simultaneously for the same action request:

1. A signed revision of this ADR names one stable action ID, exact resource kind, namespace, and `resourceName`.
2. CDO owns and explicitly approves the action and target.
3. A real auditable approval provider binds approver, incident, action digest, target, reason, issue time, and expiry. A boolean configuration value is not approval.
4. A separate executor workload and ServiceAccount have the minimum verb on the exact resource; the ordinary runtime remains read-only.
5. Live evidence proves the target is stateless, multi-replica, ready, outside protected incident infrastructure, and limited to one service.
6. The action is not competing with an HPA or another controller unless that controller interaction is explicitly designed and tested.
7. Official error-budget policy permits the action.
8. Current cost evidence permits the action when it can affect cost.
9. A pre-action snapshot, deterministic verification queries/windows, timeout, cooldown, maximum attempts, and deterministic rollback are implemented and tested.
10. A store-backed lock proves no other live action is running.
11. Every dependency and safety input is fresh; unavailable or ambiguous evidence fails closed to escalation.
12. Controlled dry-run and integration evaluation has passed, followed by CDO-reviewed canary evidence.

Enabling live mode requires a reviewed ADR update and chart PR. It is not enabled by changing a runtime boolean alone.

### Candidate for later evaluation

A possible candidate is a temporary `N -> N+1 -> N` change for one exact stateless Deployment. It remains unapproved and disabled. It may be selected only if the target is already multi-replica, is not HPA-controlled, has current cost headroom, has a captured original replica count, and can be verified and restored automatically within an approved TTL. If no target satisfies the complete gate, TF2 remains in dry-run mode and escalates to CDO.

## Phase 3 Completion Evidence

For the current dry-run baseline:

- signed `ADR-SAFETY-001` and this decision;
- deployed runtime reports `mode=dry-run`;
- chart/RBAC proof shows no mutation identity;
- real alert, incident, proposed action, gate results, verification evaluation, audit timeline, and human escalation evidence;
- rejection tests for protected, stateful, single-replica, broad, stale, unapproved, unverifiable, and cost-unknown actions.

For any later live transition, add every item in the twelve-point gate above plus the exact live action result, rollback evidence, and post-action verification.

## Consequences

- The team can deliver and evaluate the required safe response loop now without manufacturing approval or broad credentials.
- P0 cannot claim autonomous Kubernetes mutation; it must be described accurately as continuous dry-run remediation with real escalation.
- Live remediation remains an explicit later Phase 3 milestone, but schedule pressure cannot bypass its acceptance gates.

## Rollback And Revisit Conditions

- The emergency safe state is `dry-run` plus absence/removal of executor mutation RBAC.
- Any expired approval, missing cost/error-budget state, unavailable verification query, executor uncertainty, or adverse telemetry immediately blocks further execution and escalates.
- Revisit this ADR when a CDO-approved exact action and all required evidence are available. Record the new revision, signers, chart commit, approval provider, and activation/expiry window before enabling `live-approved`.
