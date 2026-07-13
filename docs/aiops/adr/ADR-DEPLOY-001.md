# ADR-DEPLOY-001 - Deployment, Network Exposure, And Runtime Ownership

> Status: Proposed - direction selected; CDO sign-off and live EKS evidence pending
> Owner: AIO4 AIOps sub-team
> Required reviewers: TF2 CDO chart owner; chart CODEOWNER `@hungxqt`; one AIO4 reviewer
> Last updated: 2026-07-13

## Context

Phase 3 requires the AIOps capability to run continuously in the TF2 environment, use real infrastructure, remain within the TF budget, preserve private operational endpoints, and leave important changes attributable. Application source and deployment desired state are intentionally separated between `tf2-corp-platform` and the CDO-owned chart repository.

On 2026-07-13 the team inspected a clean clone of `https://github.com/tf2-team/tf2-corp-chart.git` at commit `6c49c645a03922d763dd77e54cfe1db6227eaf16` on branch `main`. This proves repository configuration at that revision; it does not by itself prove the live Argo or EKS state.

The inspected chart records:

- production Argo CD Application and Helm release: `techx-corp`;
- target branch: `main`;
- target namespace: `techx-corp-prod`;
- Helm values layers: `values.yaml`, `values-public-alb.yaml`, and `values-prod.yaml`;
- production chart paths owned by `@hungxqt` through `CODEOWNERS`;
- an OpenTelemetry Collector OTLP receiver in the metrics pipeline, exporting to the Prometheus OTLP endpoint;
- no AIOps Deployment, Service, PVC, ConfigMap, NetworkPolicy, or dedicated AIOps RBAC at the inspected revision.

Repository evidence:

- [Production Argo Application](https://github.com/tf2-team/tf2-corp-chart/blob/6c49c645a03922d763dd77e54cfe1db6227eaf16/gitops/clusters/prod/application.yaml)
- [Chart deployment ownership and environment map](https://github.com/tf2-team/tf2-corp-chart/blob/6c49c645a03922d763dd77e54cfe1db6227eaf16/docs/DEPLOYMENT.md)
- [Chart CODEOWNERS](https://github.com/tf2-team/tf2-corp-chart/blob/6c49c645a03922d763dd77e54cfe1db6227eaf16/CODEOWNERS)
- [Collector configuration in chart values](https://github.com/tf2-team/tf2-corp-chart/blob/6c49c645a03922d763dd77e54cfe1db6227eaf16/values.yaml)

## Decision

### Runtime and chart ownership

- Keep AIOps runtime source, image build definition, typed production configuration, tests, canonical runbooks, and local Grafana assets in `tf2-corp-platform`.
- Deploy AIOps only through the CDO-owned `tf2-corp-chart` GitOps repository.
- Add dedicated, schema-validated resources gated by `.Values.aiops.enabled`: Deployment, ClusterIP Service, immutable/checksum-mounted ConfigMap, PVC, NetworkPolicy, read-only ServiceAccount/Role/RoleBinding, and Grafana provisioning mounts.
- Use a single active pod with `Recreate` while the baseline uses SQLite WAL on a PVC.
- Do not place an executor or mutation RBAC in the current dry-run chart configuration.
- Production changes use a reviewed chart PR and Argo CD synchronization. The Phase 3 reference chart is not a production write target.

### Self-metrics ingestion

Select this production path:

```text
aiops-runtime -> OTLP -> existing OpenTelemetry Collector -> Prometheus -> Grafana
```

The runtime also exposes `/metrics`, but that endpoint is a diagnostic/compatibility surface rather than the selected production ingestion path. Production acceptance requires real `aiops_*` series in TF2 Prometheus and a Grafana runtime-loss alert routed independently of AIOps.

### Network exposure

- AIOps HTTP endpoints have no public Ingress.
- The Service is `ClusterIP` only.
- Operator access follows the TF2 private VPN/tunnel/internal-network path required by Mandate #1.
- NetworkPolicy permits only the required Grafana webhook ingress and bounded egress to the collector, Prometheus, Jaeger, OpenSearch, Kubernetes API, and approved notification/status dependencies.

## Acceptance Evidence Still Required

- CDO and CODEOWNER review/sign-off on this ADR and the chart PR.
- Implementing chart commit, rendered manifests, schema/lint results, and Argo CD `status.sync.revision`.
- Live Argo Application `techx-corp` shows `Synced` and `Healthy` at the recorded revision.
- Live namespace/release identity and immutable AIOps image digest.
- Pod health, PVC persistence, resource usage, private endpoint access, and absence of public ingress.
- `kubectl auth can-i` evidence that the normal identity cannot read Secrets or mutate workloads.
- Deployed collector configuration revision and timestamped Prometheus query returning qualified `aiops_*` series.
- Independent runtime-loss alert test and redacted delivery evidence.
- Confirmation that current TF2 cost remains within budget.

Until these items exist, the deployment gate is open and documentation must say `pending`, not `deployed` or `verified live`.

## Consequences

- The implementation follows the existing TF2 OTLP path and avoids introducing a second scrape configuration solely for AIOps.
- A chart change and CDO review are required before the platform repository work can run on EKS.
- The ordinary runtime remains least-privilege and cannot silently acquire mutation authority.
- Repository commit `6c49c...` is the inspected baseline, not a claim that this is the current live Argo revision.

## Rollback And Revisit Conditions

- Roll back deployment changes by reverting the chart commit and allowing Argo CD to synchronize the known-good desired state.
- Force the AIOps mode to `dry-run` and keep mutation RBAC absent, or remove it if a later live boundary had been installed, whenever safety evidence becomes unavailable.
- Revisit the OTLP choice only if live collector evidence shows that the declared OTLP metrics pipeline is unavailable or operationally unsafe. Any alternative scrape path requires an ADR revision and the same end-to-end Prometheus/alert proof.
