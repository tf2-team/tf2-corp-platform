# AIOps Evidence Index

> Status: Draft. Link real evidence here as work is completed. Do not store secrets, webhook URLs, raw prompts, PII, or unredacted logs.

## Required P0 Evidence

| Area | Artifact | Owner | Status | Notes |
|---|---|---|---|---|
| Official SLI mapping | ADR-SLI-001, live Prometheus captures, rule tests | TBD | TODO | Rolling 24h, official thresholds |
| Runtime deployment | Image digest, rendered manifests, pod health, endpoint | TBD | TODO | EKS evidence only |
| Alert routing | Direct Grafana route, AIOps webhook, redacted payload | TBD | TODO | No secrets in evidence |
| Mandate #1 exposure | Public storefront proof, private ops access proof, mentor access instructions | TBD | TODO | Grafana/Jaeger/ArgoCD private |
| RBAC/security | `kubectl auth can-i`, pod security, no public ingress | TBD | TODO | Read-only normal identity |
| Evaluation | Replay JSON/Markdown, command logs, raw artifact paths | TBD | TODO | Detection and remediation |
| Runbooks | Canonical runbook links under `tf2-corp-platform/src/aio/runbooks/` | TBD | TODO | No duplicate runbooks here |
| Incidents/COE | Real incident timelines and signed postmortems | TBD | TODO | Synthetic scenarios stay in eval |

## Known Gaps

- Runtime scaffold and canonical runbooks are not yet implemented under `tf2-corp-platform/src/aio/`.
- ADRs are draft placeholders until signed with live evidence.

