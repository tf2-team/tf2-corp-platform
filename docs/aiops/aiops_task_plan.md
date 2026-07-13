# AIOps Task Breakdown - AIO4 Team (TF2)

> **Team:** AIO4 (AIOps sub-team) | **TF:** TF2 (AIO4 + CDO03 + CDO06)  
> **Timeline covered by this plan:** Week 2-3 only, July 13 -> July 24, 2026  
> **Last updated:** July 13, 2026  
> **Scope:** AIOps only. AIE work such as Shopping Copilot, review-summary quality, prompt-injection guardrails, and AI product features is excluded except where AIOps consumes an AIE-owned correctness status as an external signal.

> [!NOTE]
> - ClickUp layout is preserved: Task Name, Assignee, Description, Status, Due Date, Priority, and Tags.
> - Week 1 has been removed because it has already passed.
> - Each task description includes `Evidence required:` so the task owner knows exactly what proof must be shown before the task can be marked complete.
> - This plan is aligned to Phase 3 requirements, `tf2-corp-platform/docs/aiops/aio4_phase3_summary.md`, `tf2-corp-platform/src/aio/raws/architect.md`, `tf2-corp-platform/src/aio/raws/implement_plan.md`, and `tf2-corp-platform/docs/aiops/AIO_BACKLOG.md`.
> - P0 order remains `OPS-01 -> OPS-03 -> OPS-02`. OPS-04, OPS-07, and OPS-05 are conditional P1. OPS-06 is conditional P2 until Kafka metrics are verified or a live incident/directive promotes it.

---

## Alignment Rules

| Item | Detail |
|---|---|
| Source-of-truth order | Active BTC mandates; Phase 3 rules, SLO, budget, architecture, and incident history; live TF2 evidence; `src/aio/raws/architect.md`; `src/aio/raws/implement_plan.md`; corrected AIOps backlog; Week 1 discovery docs. |
| Repository split | Runtime code, canonical runbooks, production config, tests, and local Grafana assets go under `tf2-corp-platform`. ADRs, evidence, Ops Reviews, postmortems, and evaluation reports go under `tf2-corp-platform/docs/aiops`. Runtime must not read from `tf2-corp-platform/docs/aiops`. |
| Current repo evidence | `tf2-corp-platform/src/aio/` exists with planning notes, but the runtime scaffold, canonical runbooks, tests, and EKS deployment proof are not implemented yet. The separate clean chart clone verifies `tf2-team/tf2-corp-chart` at inspected commit `6c49c645...`; its current revision has no AIOps workload. |
| Status values | `TO DO` means planned work. `IN PROGRESS` means active work with partial evidence. `GATED` means CDO/BTC/live-environment decision or evidence is required. `RECURRING` means daily operational duty. |
| Production realness | Production config cannot contain placeholders, localhost/example URLs, fake adapters, test fixture paths, unverified metrics, floating production tags, or dependencies on `tf2-corp-platform/docs/aiops`. |
| Workload balance | Balance by effort, operational risk, and dependencies rather than row count. Assign no more than two substantial delivery tasks to one member per day; primary on-call duty, incident response, and gated CDO coordination count as workload. P1/P2 work yields to P0 or on-call demand. |

---

## Team Roles & Assignment

| Member | Role | Focus Area | Color |
|---|---|---|---|
| **Member A** | Detection & Data Engineer | SLI mapping, Prometheus signals, signal qualification, feature computation, detectors, anomaly detection, runtime evidence data, detection evaluation | Blue |
| **Member B** | Remediation & Ops Engineer | Domain contracts, durable state, incident lifecycle, runbooks, dry-run engine, safety guardrails, verification, rollback/escalation behavior, postmortems | Green |
| **Member C** | Observability & Runtime Integration Lead | Runtime/API integration, topology validation, Grafana rules/dashboards, alert routing, EKS/Helm coordination with CDO, ADRs, evidence index, Ops Reviews, final readout | Yellow |

---

## On-Call Rotation

| Week | Primary On-Call | Backup |
|---|---|---|
| Week 2 (Jul 13-17) | **Member C** | Member B |
| Week 3 (Jul 20-24) | **Member A** | Member C |

---

## Non-Negotiable Gates

| Gate | Requirement | Evidence required |
|---|---|---|
| Official SLO window | Official operational SLOs use rolling 24h windows. 5m/15m windows are diagnostics and anomaly inputs only. | Signed SLI ADR, Grafana rule exports, query evidence with timestamps, and rule tests. |
| Checkout SLO interpretation | Checkout success >= 99.0% is official. Checkout latency is diagnostic only. | SLI mapping, dashboard labels, detector config, and alert payload proving checkout latency is not treated as an official SLO. |
| Signal quality | Missing, stale, invalid, fallback-only, or unverified signals are never zero or healthy. | Signal registry, qualification tests, no-data replay scenario, and monitoring-loss incident evidence. |
| Protected incident path | AIOps may observe flagd/OpenFeature symptoms but must not disable, redirect, mutate, bypass, or exercise BTC controls without explicit approval. | Safety ADR, policy tests, prohibited-action rejection logs, and runbook warnings. |
| Dry-run now; live remediation later | P0 decision is real continuous dry-run. Live remediation is deferred, not removed, and may enable at most one exact action later only after all safety, approval, separate-executor RBAC, target, cost, error-budget, verification, rollback, cooldown, and audit gates pass. | Signed ADR-SAFETY-001 and ADR-LIVE-001, runtime mode evidence, no-mutation RBAC proof, guardrail tests, and later live evidence if the gate is reopened. |
| Active network mandate | Storefront must remain public while Grafana, Jaeger, ArgoCD/admin UIs, dashboards, and AIOps endpoints remain private through VPN, tunnel, or private networking. | ADR-DEPLOY-001, access proof, mentor access instructions, and SLO-safe cutover evidence. |
| Platform ownership | Production desired state is `https://github.com/tf2-team/tf2-corp-chart.git` (`main`), Argo Application/release `techx-corp`, namespace `techx-corp-prod`. Inspected baseline `6c49c645...` is repository evidence only and currently has no AIOps workload. | Signed ADR-DEPLOY-001, implementing chart revision, CODEOWNER/CDO review, rendered manifests, Argo sync revision, release/pod proof, and private-access evidence. |

---

## WEEK 2 - P0 Detection, Alerting & Dry-Run Response (Jul 13-17)

> **Goal:** Deliver a continuous P0 vertical slice: collect/receive -> qualify -> normalize -> compute features -> detect -> correlate -> incident -> notify/runbook/evidence -> safety-check -> dry-run -> verify/escalate.

### WEEK 2 - Day 1 (Mon Jul 13)

| Task Name | Assignee | Description | Status | Due Date | Priority | Tags |
|---|---|---|---|---|---|---|
| **Create AIOps service scaffold in `tf2-corp-platform`** | **Member A** | Work: Create `tf2-corp-platform/src/aio/` with README, pyproject, Dockerfile, `.dockerignore`, Python package directories, config directories, scripts, canonical runbook directory, and tests aligned to `src/aio/raws/architect.md` Section 15 and `src/aio/raws/implement_plan.md` Section 4. Use one Python modular-monolith service with strict internal module boundaries. Evidence required: directory tree exists, package imports successfully, health app can start locally, dependency lock exists, Dockerfile exists, and no runtime file imports from `tf2-corp-platform/docs/aiops`. | TO DO | Jul 13 (Mon) | P0 Urgent | `scaffold`, `runtime`, `python`, `tf2-corp-platform` |
| **Implement configuration schemas and domain contracts** | **Member B** | Work: Implement typed schemas/models for settings, signals, detectors, topology, action policies, notification routes, observations, normalized features, incidents, actions, approvals, audit events, and runtime mode. Reject duplicate IDs, missing references, placeholder values, hardcoded environment facts, unverified official SLI inputs, unsafe actions, and live mode without approvals. Evidence required: config-check command output, unit tests for invalid configs, canonical config digest output, and sample valid/invalid config fixtures under tests only. | TO DO | Jul 13 (Mon) | P0 Urgent | `config`, `schemas`, `contracts`, `validation` |
| **Finalize official SLI mapping and detector design** | **Member A** | Work: Validate every official numeric SLO against deployed series: browse/search success, storefront p95, cart success, and checkout success. Keep checkout latency diagnostic-only. Define rolling 24h SLO state, error-budget context, early warnings, no-data behavior, detector result states, recovery windows, and minimum sample behavior. Evidence required: signed `ADR-SLI-001`, signed `ADR-DETECT-001`, live Prometheus query output, owner/reviewer names, metric labels, units, query windows, and rule-test results. | TO DO | Jul 13 (Mon) | P0 Urgent | `slo`, `architecture`, `detection`, `adr` |
| **Finalize remediation safety ADR** | **Member B** | Work: Review and sign the recorded dry-run-now/later-live decision. Implement Detect -> Safety Check -> Dry Run -> optional later approved execution -> Verify -> Rollback/Escalate. List allowed recommendations, blocked actions, cooldown, max attempts, one-live-action lock, approval expiry, budget gate, error-budget gate, verification dependency, rollback behavior, and flagd/OpenFeature prohibition. Evidence required: signed `ADR-SAFETY-001` and `ADR-LIVE-001`, blocked-action matrix, policy evaluation order, and no-mutation P0 proof. | IN PROGRESS | Jul 13 (Mon) | P0 Urgent | `remediation`, `safety`, `adr` |
| **Finalize alert routing and EKS integration ADR** | **Member C** | Work: Obtain CDO/CODEOWNER review of the recorded chart and OTLP decisions, then define incident payload, severity, dedup key, real TF2 contact point, direct Grafana route, AIOps webhook route, webhook secret, EKS runtime, resources, storage, RBAC, and chart implementation. Evidence required: signed `ADR-ROUTING-001`, signed `ADR-DEPLOY-001`, redacted alert channel proof, implementing chart revision, rendered manifests, live Argo sync revision, and real namespace/release evidence. | IN PROGRESS | Jul 13 (Mon) | P0 Urgent | `alerting`, `eks`, `adr`, `cdo` |
| **Cross-team P0 dependency review** | `ALL` | Work: Assign owners and due dates for runtime deployment, Helm changes, RBAC, alert channel, webhook secret, cost state, AIE correctness status, instrumentation gaps, and live-action prerequisites. Record blockers that prevent P0 acceptance. Evidence required: dependency matrix with owner, due date, current state, blocking risk, and link to ADR/evidence item. | TO DO | Jul 13 (Mon) | P0 Urgent | `cross-team`, `dependency`, `planning` |

### WEEK 2 - Day 2 (Tue Jul 14)

| Task Name | Assignee | Description | Status | Due Date | Priority | Tags |
|---|---|---|---|---|---|---|
| **Implement storage, migrations, and append-only audit** | **Member B** | Work: Implement SQLite WAL repositories and forward-only migrations for incidents, incident events, observations, notification outbox, notification attempts, actions, approvals, audit events, scheduler checkpoints, config revisions, and evidence metadata. Enforce the incident/event/outbox transaction, immutable audit rows, and action-result transaction boundaries. Pending/executing actions after restart require human review and never replay automatically. Evidence required: migration and repository tests, restart recovery test, SQLite update/delete rejection test for audit rows, schema output, and transaction-boundary tests. | TO DO | Jul 14 (Tue) | P0 Urgent | `storage`, `sqlite`, `audit`, `recovery` |
| **Implement collectors and signal qualification gate** | **Member A** | Work: Implement bounded adapters for Prometheus, Grafana webhook, Jaeger, OpenSearch, Kubernetes read context, optional AIE status, and optional cost status. Return a common observation envelope and qualify freshness, unit, result shape, labels, cardinality, sample count, source errors, stale data, no traffic versus no data, and semantic proof. Evidence required: collector contract tests for success, timeout, empty result, stale result, malformed response, forbidden response, bad webhook secret, and optional-status stale cases. | TO DO | Jul 14 (Tue) | P0 Urgent | `collectors`, `prometheus`, `grafana-webhook`, `qualification` |
| **Build OPS-01 SLO detector inputs** | **Member A** | Work: Implement validated rolling 24h SLO queries, early-warning diagnostic queries, checkout diagnostic panels, and missing/stale signal checks. Official detectors must not consume unverified or fallback-only signals as primary SLI. Evidence required: signal registry YAML, query ID list, PromQL tests, boundary tests, live query capture, and proof that checkout latency is diagnostic-only. | TO DO | Jul 14 (Tue) | P0 Urgent | `ops-01`, `prometheus`, `slo` |
| **Build P0 incident runbooks** | **Member B** | Work: Create versioned canonical runbooks with machine-readable YAML front matter under `tf2-corp-platform/src/aio/runbooks/` for official SLO breach, checkout dependency failure, DB saturation, and monitoring loss. Each runbook must include impact, preconditions/signal quality, evidence, first response, prohibited actions, dry-run recommendation, verification, rollback/escalation, owner, and communication template. Evidence required: runbook files, schema validation, runbook index, matcher test output, and sample incident linking to each runbook. | TO DO | Jul 14 (Tue) | P0 Urgent | `runbook`, `incident-response`, `p0` |
| **Implement runtime startup, scheduler, APIs, and graceful shutdown** | **Member C** | Work: Implement ordered startup after logging/redaction, validated config, migrations, and bounded clients; initialize collectors, feature cache, detectors, incident manager, notifier, evidence builder, and response engine; recover checkpoints, incidents, outbox, and action-review state. Run non-overlapping collection, detection, recovery, notification, and evidence-export loops. Implement liveness, readiness, metrics, authenticated Grafana event, read-only incident, and runtime APIs. Graceful shutdown must stop new work, flush audit/outbox, save checkpoints, close clients, and never begin/replay an action. Evidence required: startup-order test, API contract tests, scheduler non-overlap test, restart recovery test, graceful-shutdown test, and config revision visible through the runtime API. | TO DO | Jul 14 (Tue) | P0 Urgent | `runtime`, `scheduler`, `api`, `shutdown` |
| **Build official SLO dashboard and contact point** | **Member C** | Work: Provision rolling 24h SLO dashboard and Grafana rules for browse/search, storefront p95, cart, checkout, AI correctness dependency/gap, checkout diagnostics, signal freshness, and error-budget state. Preserve direct Grafana-to-on-call route and add authenticated AIOps webhook route. Evidence required: dashboard JSON/YAML, alert rule YAML, rule-test output, screenshot/export, redacted test alert payload, and channel delivery proof. | TO DO | Jul 14 (Tue) | P0 Urgent | `grafana`, `dashboard`, `alerting` |

### WEEK 2 - Day 3 (Wed Jul 15)

| Task Name | Assignee | Description | Status | Due Date | Priority | Tags |
|---|---|---|---|---|---|---|
| **Implement feature computation for SLOs, diagnostics, and baselines** | **Member A** | Work: Build feature computation for rolling 24h official SLOs, 5m/15m diagnostics, QPS, error ratio, latency percentiles, signal freshness, sample volume, median/MAD, EWMA fallback, robust score, trend, previous-window delta, topology distance, and shared affected flow. Raw observations must remain linked for reproducibility. Evidence required: unit tests for ratios, histograms, no traffic, stale data, warm-up, zero MAD, EWMA fallback, and feature provenance. | TO DO | Jul 15 (Wed) | P0 Urgent | `features`, `slo`, `baseline`, `statistics` |
| **Build OPS-03 and OPS-02 detection** | **Member A** | Work: Implement checkout dependency and PostgreSQL pressure detectors using qualified signals. Checkout dependency must output supported likely dependency or `unknown`, include confidence and contributing signals, and attach Jaeger/OpenSearch/Kubernetes evidence when available. DB pressure must use discovered `max_connections`, approved threshold, active backends, trend, and supporting symptoms. Evidence required: detector tests, DB threshold ADR, sample candidate events, and replay output for checkout dependency, unknown checkout failure, and DB pressure. | TO DO | Jul 15 (Wed) | P0 Urgent | `ops-03`, `ops-02`, `correlation`, `db` |
| **Implement incident lifecycle and deduplication** | **Member B** | Work: Implement stable fingerprinting, incident state machine, append-only timelines, reopen/recovery, cooldown/suppression, transactional notification intent, and restart-safe state. Default fingerprint includes environment, detector ID, flow, primary service, and likely dependency. Evidence required: tests for fingerprint stability, illegal transitions, duplicate occurrence updates, reopen, consecutive-check recovery, cooldown, transaction behavior, and restart recovery. | TO DO | Jul 15 (Wed) | P0 Urgent | `incident`, `deduplication`, `lifecycle`, `recovery` |
| **Implement dry-run remediation engine** | **Member B** | Work: Implement incident state machine integration, action registry, dry-run results, safety policy gates, verification checks, rollback/escalation outcomes, and audit events. The runtime must default to dry-run and never execute a live action without all gates. Evidence required: policy tests, dry-run output example, audit event example, verification pass/fail tests, and prohibited-action rejection tests. | TO DO | Jul 15 (Wed) | P0 Urgent | `remediation`, `dry-run`, `engine` |
| **Implement minimum P0 checkout topology and correlation** | **Member C** | Work: Create the versioned minimum checkout topology used by OPS-03 before detector enablement. Record service and dependency edges, owner, customer flow, stateful/stateless status, replica evidence, metric/trace/log query IDs, runbook, remediation restrictions, and escalation path. Validate it against source, bounded Jaeger traces, and deployed Kubernetes state; implement temporal grouping, likely-dependency scoring, confidence contributions, unknown-cause behavior, and cascade handling. Evidence required: topology YAML plus `docs/aiops/topology/` artifact, source/trace/Kubernetes validation, correlation and cascade tests, and config/runbook links. | TO DO | Jul 15 (Wed) | P0 Urgent | `ops-03`, `topology`, `correlation`, `evidence` |
| **Implement alert routing and deduplication** | **Member C** | Work: Route normalized incidents with incident ID, flow/service, signal/value, threshold/baseline, severity, owner, runbook, dashboard, trace/log query, confidence, action mode, verification status, and grouping key. Use transactional outbox, retry/backoff, backup route, and redaction. Evidence required: notification contract tests, outbox retry test, redaction test, sample payload, and real test alert delivery evidence. | TO DO | Jul 15 (Wed) | P0 Urgent | `alerting`, `deduplication`, `integration` |

### WEEK 2 - Day 4 (Thu Jul 16)

| Task Name | Assignee | Description | Status | Due Date | Priority | Tags |
|---|---|---|---|---|---|---|
| **Implement multi-signal anomaly detection** | **Member A** | Work: Implement explainable median/MAD or EWMA anomaly scoring with minimum history, warm-up, zero-MAD fallback, consecutive-cycle rules, corroborating signals, suppression on missing/stale inputs, and contribution output. Statistical anomalies create early warnings but never delay or override hard SLO alerts. Evidence required: tests for warm-up, spikes, drift, zero MAD, stale inputs, corroboration, and explanation fields. | TO DO | Jul 16 (Thu) | P0 Urgent | `anomaly-detection`, `multi-signal`, `engineering` |
| **Implement bounded runtime evidence and independent audit export** | **Member A** | Work: Build bounded redacted incident bundles containing incident, timeline, observations, notifications, actions, verification, queries, links, and a redaction report. Record source, stable query ID, absolute time bounds, capture time, environment, result digest, and adapter status. Emit equivalent structured JSON lifecycle events to OpenSearch as an independent trail; commit only redacted summaries/indexes to Git. Evidence required: evidence-builder/export tests, sample bounded bundle, nested secret/PII redaction report, OpenSearch lifecycle-event capture, and restart/export recovery test. | TO DO | Jul 16 (Thu) | P0 Urgent | `evidence`, `redaction`, `opensearch`, `audit` |
| **Implement remediation guardrails and failure handling** | **Member B** | Work: Enforce blocked actions, one-service scope, stateful/single-replica protection, no flagd/OpenFeature mutation, no DB/Secret mutation, no broad RBAC, cooldown, max attempts, no concurrent live action, approval expiry, dependency-unavailable behavior, verification-inconclusive escalation, and restart-safe action handling. Evidence required: rejection-gate test suite, failure-mode integration tests, sample audit logs, and dry-run recommendation examples. | TO DO | Jul 16 (Thu) | P0 Urgent | `remediation`, `guardrails`, `safety` |
| **Implement security and fail-safe behavior** | **Member B** | Work: Add webhook authentication, body-size limits, schema validation, stable query IDs, parameter allow-lists, notification escaping, secret redaction, PII redaction, no string execution from external data, degraded collector behavior, readiness failure on invalid config/store failure, and direct Grafana route preservation. Evidence required: security tests, redaction tests, invalid payload tests, collector-failure tests, and failure-mode documentation. | TO DO | Jul 16 (Thu) | P0 Urgent | `security`, `fail-safe`, `pii`, `secrets` |
| **Build AIOps operations dashboard** | **Member C** | Work: Expose `aiops_*` metrics for build/config revision, collection, signal freshness/quality, detector evaluations, incidents, notifications, actions, scheduler, store errors, and runtime mode. Build dashboard for runtime health, last collection, signal freshness, alert history, dedup state, dry-run actions, MTTD/MTTR, unresolved incidents, and action mode. Evidence required: `/metrics` output, queryable `aiops_*` in TF2 Prometheus, dashboard export, screenshot, and runtime-loss alert proof. | TO DO | Jul 16 (Thu) | P0 Urgent | `observability`, `dashboard`, `operations` |

### WEEK 2 - Day 5 (Fri Jul 17)

| Task Name | Assignee | Description | Status | Due Date | Priority | Tags |
|---|---|---|---|---|---|---|
| **Package production image and inspect artifact contents** | **Member A** | Work: Build production image with immutable base digest, locked dependencies, non-root runtime, no tests/fixtures/fake adapters/sample config, no `tf2-corp-platform/docs/aiops` runtime dependency, no placeholder endpoints, and explicit build revision. Add artifact inspection that fails if production wiring can select test modules or fixture paths. Evidence required: image digest, build log, inspection output, dependency lock, and CI check output. | TO DO | Jul 17 (Fri) | P0 Urgent | `image`, `ci`, `artifact`, `realness` |
| **Deploy AIOps runtime continuously on EKS** | **Member C** | Work: Deploy as one active EKS workload with ClusterIP service, ConfigMap/Secret references, PVC, Recreate strategy, probes, resource limits, non-root security context, read-only root filesystem, dropped capabilities, seccomp, read-only ServiceAccount, and no public ingress. Local-only execution is not complete. Evidence required: rendered manifests, Helm revision, pod health, PVC proof, runtime endpoint, resource usage, and `kubectl auth can-i` proof showing no secret read and no mutation permissions. | GATED | Jul 17 (Fri) | P0 Urgent | `deployment`, `eks`, `continuous`, `rbac` |
| **Run replay and deployed controlled P0 end-to-end tests** | **Member B** | Work: Run replay scenarios for normal traffic, official SLO breach, checkout dependency, unknown checkout failure, DB pressure, monitoring loss, duplicate cascade, notification failure, runtime restart, prohibited action, verification pass/fail/unavailable, and stale optional dependencies. Separately send one authenticated controlled event through the deployed Grafana contact point and prove the real Prometheus, notification, persistent-store, evidence, and verification adapters were used without changing BTC flags. Evidence required: separate JSON/Markdown replay results plus deployed controlled-event timeline, authenticated webhook proof, real-adapter identifiers, notification delivery, persistence/restart proof, verification result, code/config revisions, absolute start/end time, and raw artifact paths. | GATED | Jul 17 (Fri) | P0 Urgent | `testing`, `deployed-e2e`, `replay`, `real-adapters` |
| **Publish Week 2 Ops Review** | **Member C** | Work: Report official SLO/error-budget state, budget, incidents, P0 coverage, MTTD, false alerts, signal gaps, CDO dependencies, current runtime mode, safety posture, and Week 3 proposal. Evidence required: Ops Review under `tf2-corp-platform/docs/aiops/ops-reviews/`, linked dashboards, linked evaluation results, current risk register, and explicit Week 3 scope recommendation. | TO DO | Jul 17 (Fri) | P0 Urgent | `ops-review`, `evidence`, `deliverable` |
| **Apply Week 3 scope gate** | `ALL` | Work: Admit P1 only if P0 official SLO, checkout dependency, DB pressure, monitoring loss, routing, dry-run, verification, audit, and evidence gates pass. Otherwise keep Week 3 on P0 hardening and final evidence. Evidence required: signed gate decision listing passed checks, failed checks, admitted P1 scope, deferred scope, owners, and dates. | TO DO | Jul 17 (Fri) | P0 Urgent | `planning`, `scope-gate`, `retro` |

> **CDO Note:** AIOps changes to EKS Deployment, Helm, RBAC, replicas, scaling, security, or cost controls require CDO ownership/approval. Scale-up remains a recommendation or human-approved action unless explicitly approved.

---

## WEEK 3 - Harden, Conditional Response, Eval & Readout (Jul 20-24)

> **Goal:** Harden the P0 loop, evaluate it reproducibly, add only evidence-supported P1 work, and prepare the final Service Health Readout.

### WEEK 3 - Day 1 (Mon Jul 20)

| Task Name | Assignee | Description | Status | Due Date | Priority | Tags |
|---|---|---|---|---|---|---|
| **Tune P0 detector thresholds and baseline behavior** | **Member A** | Work: Use Week 2 evidence to tune thresholds, windows, warm-up, minimum sample counts, stale limits, median/MAD or EWMA settings, confirmation, recovery hysteresis, and DB pressure threshold. Every threshold must link to live evidence and ADR-DETECT-001 or ADR-THRESHOLD-DB-001. Evidence required: updated ADRs, config diff, before/after replay results, live baseline evidence, and reviewer sign-off. | TO DO | Jul 20 (Mon) | P0 Urgent | `tuning`, `detection`, `adr`, `thresholds` |
| **Harden remediation dependency and queue handling** | **Member B** | Work: Add retry/backoff, outbox retry, cooldown, concurrent incident queueing, dependency-unavailable handling, stuck-state escalation, scheduler checkpoint recovery, action non-replay after restart, verification timeout, and audit consistency. Evidence required: integration tests for retry, restart, action non-replay, stuck-state escalation, dependency failure, and timeline reconstruction. | TO DO | Jul 20 (Mon) | P0 Urgent | `remediation`, `hardening`, `reliability` |
| **Finalize ADR index and audit format** | **Member C** | Work: Finalize ADR index, evidence index, audit schema, incident timeline format, runbook index, config digest policy, signer/approver attribution, and rollback/revisit conditions. Evidence required: `tf2-corp-platform/docs/aiops/evidence-index.md`, ADR index, audit schema example, sample incident timeline, and links to every signed decision. | TO DO | Jul 20 (Mon) | P0 Urgent | `adr`, `auditability`, `evidence` |

### WEEK 3 - Day 2 (Tue Jul 21)

| Task Name | Assignee | Description | Status | Due Date | Priority | Tags |
|---|---|---|---|---|---|---|
| **Add evidence-supported P1 detectors** | **Member A** | Work: Add high-risk flag symptom signatures and LLM visibility only after P0 gate passes. Observe flag symptoms without reading/changing/exercising protected flag state. Use verified or fallback-only signals appropriately. Show missing `gen_ai_client_*` or token metrics as N/A, not zero. Evidence required: P1 gate decision, qualified signals, detector config, runbook links, tests, and proof that protected flag state is not mutated. | TO DO | Jul 21 (Tue) | P1 High | `ops-04`, `ops-05`, `ai-observability` |
| **Evaluate the later single live-remediation gate** | **Member B** | Work: Keep the selected P0 mode in dry-run, then enable only the exact CDO-approved stateless action when ADR-LIVE-001, real approval provider, approval expiry/digest, separate executor identity, least-privilege RBAC, dry-run evidence, verification, rollback, cost, cooldown, and error-budget gates all pass. Evidence required: revised and signed ADR-LIVE-001, no-mutation P0 RBAC proof, approval evidence, dry-run evidence, verification evidence, rollback plan, and audit example. | GATED | Jul 21 (Tue) | P0 Urgent | `remediation`, `live-gate`, `safety` |
| **Finalize incident and COE workflow** | **Member C** | Work: Create workflow/templates for real incident timeline, customer impact, SLO impact, detection source, evidence, likely cause with confidence, response, verification, prevention, owner, and follow-up. Synthetic/replay scenarios belong in eval reports, not fake postmortems. Evidence required: COE template, incident timeline template, signed workflow, and completed COE for every real incident handled. | TO DO | Jul 21 (Tue) | P0 Urgent | `postmortem`, `coe`, `incident-response` |
| **Incident and mandate watch** | `ALL` | Work: Pause planned P1/stretch work when BTC injects an incident or publishes a directive. Triage, coordinate, respond, verify, update ADRs/backlog, and document evidence without disabling protected incident mechanisms. Evidence required: mandate decision log or incident timeline when triggered, owner assignment, rollback plan for mandates, and COE for real incidents. | RECURRING | Jul 21 (Tue) | P0 Urgent | `on-call`, `incident`, `mandate` |

### WEEK 3 - Day 3 (Wed Jul 22)

| Task Name | Assignee | Description | Status | Due Date | Priority | Tags |
|---|---|---|---|---|---|---|
| **Build and run detection evaluation** | **Member A** | Work: Produce reproducible evaluation for scenario coverage, recall, false alerts per normal observation hour, MTTD, no-data/stale behavior, SLO boundary behavior, likely-dependency accuracy where labels exist, runbook-match accuracy, and precision only when labeled positive/negative windows exist. Evidence required: JSON and Markdown reports with scenario revision, code/config revision, environment, command, start/end time, raw artifact path, and reviewer notes. | TO DO | Jul 22 (Wed) | P0 Urgent | `eval`, `detection`, `repro` |
| **Build and run remediation evaluation** | **Member B** | Work: Evaluate dry-run correctness, guardrail rejection, cooldown, max attempts, approval expiry, dependency-unavailable behavior, verification pass/fail/unavailable, escalation, optional live behavior if admitted, rollback where applicable, and audit/timeline completeness. Evidence required: remediation eval report, guardrail rejection output, dry-run examples, verification examples, and audit timeline reconstruction. | TO DO | Jul 22 (Wed) | P0 Urgent | `eval`, `remediation`, `repro` |
| **Extend checkout topology and evidence map** | **Member C** | Work: After the P0 scope gate passes, extend the validated minimum checkout topology with additional dependency and blast-radius evidence. Add qualified service nodes, owner, metric/trace/log query IDs, stateful/stateless and replica evidence, remediation restrictions, likely symptoms, and escalation paths without weakening the P0 model. Evidence required: P1 gate decision, updated topology artifact under `tf2-corp-platform/docs/aiops/topology/`, source/trace/Kubernetes validation, correlation regression tests, and config/runbook links. | TO DO | Jul 22 (Wed) | P1 High | `ops-07`, `topology`, `evidence` |
| **Verify Kafka signals and conditionally implement OPS-06** | **Member C** | Work: Discover exact TF2 Kafka metric names and labels. Implement lag/error detector only if verified or promoted by incident/directive. If missing, record N/A and keep detector disabled. Do not assume metric names from collector config alone. Evidence required: Kafka signal qualification evidence, live query output, detector config if enabled, or explicit N/A/defer evidence if disabled. | TO DO | Jul 22 (Wed) | P2 Conditional | `ops-06`, `kafka`, `conditional` |

### WEEK 3 - Day 4 (Thu Jul 23)

| Task Name | Assignee | Description | Status | Due Date | Priority | Tags |
|---|---|---|---|---|---|---|
| **Run final detection evaluation and close P0 gaps** | **Member A** | Work: Re-run all P0 scenarios after tuning and hardening. Fix failed P0 cases or record blockers with owners. Export final coverage, recall, MTTD, false-alert, freshness, no-data, likely-dependency, and runbook-match results without unsupported claims. Evidence required: final detection eval report, raw outputs, fixed issue list, remaining risk register, and owner sign-off for any accepted gap. | TO DO | Jul 23 (Thu) | P0 Urgent | `eval`, `detection`, `final` |
| **Finalize runbooks, remediation, and incident evidence** | **Member B** | Work: Complete on-call guide, canonical runbooks, action policy, dry-run examples, guardrail rejection examples, verification evidence, escalation records, rollback evidence where applicable, COEs, and known limitations. Confirm each response ends in verified success, rollback, failure, or escalation. Evidence required: runbook index, action/evidence examples, COEs if applicable, remediation eval, and final safety checklist. | TO DO | Jul 23 (Thu) | P0 Urgent | `runbook`, `remediation`, `final` |
| **Prepare final AIOps evidence pack** | **Member C** | Work: Index SLI mapping, signal inventory, dashboard exports, alert examples, EKS runtime proof, image digest, Helm/chart revision, rendered manifests, RBAC proof, runtime endpoint, alert channel, incidents, ADRs, eval outputs, SLO/budget state, guardrail evidence, gaps, deferred work, and remaining risk. Evidence required: complete `tf2-corp-platform/docs/aiops/evidence-index.md` with links to every artifact needed for final readout. | TO DO | Jul 23 (Thu) | P0 Urgent | `readout`, `evidence`, `final` |

### WEEK 3 - Day 5 (Fri Jul 24)

| Task Name | Assignee | Description | Status | Due Date | Priority | Tags |
|---|---|---|---|---|---|---|
| **Final verification - detection runtime** | **Member A** | Work: Verify continuous EKS runtime, health/readiness, scheduler non-overlap, fresh verified signals, official SLO/no-data/checkout dependency/DB/anomaly detectors, config digest, runtime metrics, and reproducible evaluation. Confirm checkout latency remains diagnostic and AI correctness is AIE-sourced or N/A. Evidence required: final verification checklist, live endpoint proof, `aiops_*` Prometheus proof, detector config, and final eval reports. | TO DO | Jul 24 (Fri) | P0 Urgent | `verification`, `detection`, `final` |
| **Final verification - remediation and alerts** | **Member B** | Work: Verify deployed mode, dry-run behavior, live-action decision, least-privilege RBAC, safety gates, real alert channel, runbook links, audit trail, verification, cooldown, escalation, rollback claims, and prohibited-action rejections. Confirm normal runtime cannot mutate app resources or read secrets. Evidence required: guardrail output, RBAC proof, alert payload proof, audit examples, verification examples, and final safety decision. | TO DO | Jul 24 (Fri) | P0 Urgent | `verification`, `remediation`, `final` |
| **Final verification - dashboards and documents** | **Member C** | Work: Verify official SLO dashboard, AIOps operations dashboard, alert rules, runtime-loss alert, ADRs, COEs, Ops Reviews, runtime endpoint, alert channel, evidence index, runbook index, topology, chart/image evidence, self-metrics ingestion proof, and local/EKS Grafana asset synchronization. Evidence required: final documentation checklist, dashboard exports, ADR index, evidence index, and readout artifact links. | TO DO | Jul 24 (Fri) | P0 Urgent | `verification`, `documentation`, `final` |
| **Service Health Readout - present and defend** | `ALL` | Work: Present delivered outcomes, SLO/error-budget status, budget status, incidents, AIOps runtime behavior, detection/remediation eval, trade-offs, safety constraints, live-action decision, CDO/AIE dependencies, deferred work, known limitations, and next actions. Every claim must link to evidence. Evidence required: readout deck/document, evidence pack, current runtime endpoint/channel, risk register, and stakeholder Q&A notes. | TO DO | Jul 24 (Fri) | P0 Urgent | `readout`, `deliverable`, `final` |

---

## Recurring Tasks - Every Day

| Task Name | Assignee | Description | Status | Due Date | Priority | Tags |
|---|---|---|---|---|---|---|
| **Daily standup and on-call handoff** | `ALL` | Work: Report service state, active incidents, P0 progress, blockers, mandates, CDO/AIE dependencies, cost/SLO status, open risk, and handoff notes. Evidence required: daily handoff note with owner, date, active incidents, blockers, next actions, and on-call transfer. | RECURRING | Daily | Normal | `standup`, `on-call` |
| **Check AIOps runtime and signal health** | Primary On-Call | Work: Verify scheduler last success, signal freshness, signal quality, detector evaluations, incident queue, notification outbox, storage health, runtime mode, action state, and runtime-loss alert. Until runtime exists, report blocked rather than healthy. Evidence required: daily health check record with runtime endpoint, signal freshness summary, incident count, action mode, and gaps. | RECURRING | Daily | P0 Urgent | `monitoring`, `health`, `aiops` |
| **Monitor alerts and respond to incidents** | Primary On-Call | Work: Triage alerts, confirm customer impact, contain safely, coordinate with CDO/AIE, verify recovery, document timeline, and create COE for real incidents. Active incidents preempt planned P1/P2 work. Evidence required: incident timeline, alert payload, evidence links, recovery verification, owner, and COE when real customer-impact incident occurs. | RECURRING | Daily | P0 Urgent | `incident-response`, `operations` |
| **Check BTC mandates** | Primary On-Call | Work: Check `phase3/mandates/` and program channel. For each directive, record requirements, deadline, owners, ADR impact, rollback plan, cost/SLO risk, and evidence needed. Evidence required: mandate check note each day, plus mandate decision log when a directive appears. | RECURRING | Daily | Normal | `mandates`, `compliance` |
| **Capture operational evidence** | `ALL` | Work: Save query, trace/log link, dashboard export, command output, chart revision, image digest, runtime endpoint, alert payload, decision, action, verification result, owner, and timestamp as work happens. Evidence required: updated `tf2-corp-platform/docs/aiops/evidence-index.md` with artifact link, owner, timestamp, and what acceptance criterion it supports. | RECURRING | Daily | Normal | `evidence`, `auditability` |
| **Check TF2 budget state with CDO** | Primary On-Call | Work: Record current AWS cost snapshot, weekly headroom, cost anomaly status, and any cost-changing planned action, with Member C coordinating unresolved CDO dependencies. Unknown or stale cost state blocks live cost-changing action. Evidence required: daily budget entry or CDO cost-feed reference with timestamp, source, current spend, weekly headroom, and owner. | RECURRING | Daily | Normal | `budget`, `cost`, `cdo` |

---

## Deliverables Checklist

| Deliverable | Status | Evidence required |
|---|---|---|
| Validated official SLI mapping and rolling-24h SLO dashboard | TO DO | ADR-SLI-001, live query captures, Grafana dashboard/rules, rule tests, and alert payload proof. |
| Continuous multi-signal AIOps runtime on EKS | TO DO | Runtime source, startup/API/scheduler/shutdown tests, image digest, rendered manifests, pod health, endpoint proof, self-metrics proof, and resource/RBAC evidence. |
| Checkout dependency and DB saturation detection | TO DO | Detector code/config, qualified minimum P0 topology, signal qualification, DB threshold ADR, unit/replay tests, and sample incidents. |
| Missing/stale telemetry detection | TO DO | Qualification gate, no-data detector, monitoring-loss runbook, no-data replay scenario, and incident evidence. |
| Real TF2 alert routing with deduplication and evidence links | TO DO | Alert route config, webhook auth proof, notification payload contract, dedup tests, real test alert delivery, and one deployed authenticated controlled-event timeline. |
| Bounded incident evidence and independent audit trail | TO DO | Evidence builder/exporter, sample redacted incident bundle, redaction report, structured OpenSearch lifecycle-event proof, and evidence-index link. |
| P0 runbooks and dry-run remediation loop with guardrails | TO DO | Canonical runbooks, action policy, dry-run examples, guardrail tests, verification/escalation tests, and audit output. |
| Later transition to at most one live action, only if every approval and safety gate passes | GATED | Current signed dry-run decision, followed by revised ADR-LIVE-001 with one exact action and all proofs before live enablement. |
| Detection and remediation eval scripts/fixtures with reproducible results | TO DO | Eval scripts, fixtures, JSON/Markdown results, command logs, scenario revisions, and raw artifacts. |
| Signed ADRs for SLI, detection, thresholds, safety, routing, and deployment | TO DO | ADR files under `tf2-corp-platform/docs/aiops/adr/` with owners, evidence links, status, decision, and signatures. |
| COE/postmortem for every real incident handled | TO DO | COE template plus completed signed COE for each real incident. |
| Week 2 and Week 3 Ops Reviews | TO DO | Ops Review documents under `tf2-corp-platform/docs/aiops/ops-reviews/` with SLO, budget, incidents, coverage, gaps, and next actions. |
| AIOps runtime endpoint/health and alert channel documented | TO DO | Evidence index entries for endpoint, health checks, alert channel name, test alert, and redacted route proof. |
| Service Health Readout evidence pack | TO DO | Final evidence index, readout deck/document, risk register, known gaps, and stakeholder Q&A notes. |

> [!WARNING]
> **Do not:**
> - Tamper with flagd, OpenFeature hooks, or BTC incident delivery.
> - Treat checkout p95 or p99 latency as an official Phase 3 SLO.
> - Alert on an unverified metric or report a missing series as zero/healthy.
> - Restart stateful or single-replica workloads automatically.
> - Enable broad Kubernetes mutation permissions or broad live remediation.
> - Scale without cost evidence, human approval, and CDO coordination.
> - Put production runtime code, canonical runbooks, production config, or fixture-dependent logic under `tf2-corp-platform/docs/aiops`.
> - Let P1/P2/stretch work delay P0 operation, incident response, Ops Reviews, or final evidence.



