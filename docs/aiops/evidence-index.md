# AIOps Evidence Index

> Status: Draft. Link real evidence here as work is completed. Do not store secrets, webhook URLs, raw prompts, PII, or unredacted logs.

## Recorded Repository Evidence And Decisions

Repository inspection selects the implementation direction but does not prove live EKS state.

| Area | Artifact | Owner | Status | Notes |
|---|---|---|---|---|
| Chart identity | `https://github.com/tf2-team/tf2-corp-chart.git` at `6c49c645a03922d763dd77e54cfe1db6227eaf16` | Member C + CDO | VERIFIED REPOSITORY | Clean `main` clone inspected 2026-07-13; live Argo revision still required |
| Production GitOps declaration | Chart `gitops/clusters/prod/application.yaml`, `docs/DEPLOYMENT.md`, and `CODEOWNERS` | Member C + CDO | VERIFIED REPOSITORY | Declares app/release `techx-corp`, namespace `techx-corp-prod`, branch `main`, owner `@hungxqt` |
| Self-metrics path | Chart `values.yaml` OTLP receiver, metrics pipeline, and Prometheus OTLP exporter; `ADR-DEPLOY-001` | Member C | SELECTED / LIVE PROOF PENDING | OTLP selected; real `aiops_*` query and runtime-loss alert still required |
| Remediation mode | `ADR-SAFETY-001` and `ADR-LIVE-001` | Member B | SELECTED / SIGNATURES PENDING | P0 dry-run now; later live remediation only after every gate passes |

## Required P0 Evidence

| Area | Artifact | Owner | Status | Notes |
|---|---|---|---|---|
| Official SLI mapping | ADR-SLI-001, live Prometheus captures, rule tests | TBD | TODO | Rolling 24h, official thresholds |
| Runtime deployment | Implementing chart commit, image digest, rendered manifests, Argo sync revision, pod health, endpoint | Member C + CDO | GATED | Inspected chart currently has no AIOps workload; EKS evidence required |
| Alert routing | Direct Grafana route, AIOps webhook, redacted payload | TBD | TODO | No secrets in evidence |
| Mandate #1 exposure | Public storefront proof, private ops access proof, mentor access instructions | TBD | TODO | Grafana/Jaeger/ArgoCD private |
| RBAC/security | `kubectl auth can-i`, pod security, no public ingress, no mutation identity in P0 | Member C + CDO | TODO | Read-only normal identity |
| Evaluation | Replay JSON/Markdown, command logs, raw artifact paths | TBD | TODO | Detection and remediation |
| Runbooks | Canonical runbook links under `tf2-corp-platform/src/aio/runbooks/` | TBD | TODO | No duplicate runbooks here |
| Incidents/COE | Real incident timelines and signed postmortems | TBD | TODO | Synthetic scenarios stay in eval |

## Known Gaps

- Runtime scaffold and canonical runbooks are not yet implemented under `tf2-corp-platform/src/aio/`.
- The inspected chart revision has no AIOps workload or dedicated AIOps resources.
- `ADR-DEPLOY-001`, `ADR-SAFETY-001`, and `ADR-LIVE-001` now record selected decisions but still require named reviewer signatures and live evidence before acceptance.
- The inspected Git revision is not yet proven to be the live Argo CD `status.sync.revision`.

