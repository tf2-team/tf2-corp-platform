# Change: Frontend-proxy Envoy route for Argo CD (`/argocd`)

## Summary

Added Envoy path routing so the storefront frontend-proxy proxies `/argocd/` to the in-cluster Argo CD server (`argocd-server.argocd.svc.cluster.local:80`), enabling `https://internal.hungtran.id.vn/argocd/` for VPN operators after the matching infra/chart config is live.

## Context

Operator admin UIs are reached through the internal ALB → frontend-proxy path surface. Argo CD previously required port-forward. Infra configures Argo CD with `server.rootpath=/argocd` and `server.insecure=true`; the proxy must forward that path without stripping the prefix.

## Before

* `envoy.tmpl.yaml` had no `/argocd` routes or cluster.
* Compose / `.env` had no `ARGOCD_*` variables.

## After

* Exact `/argocd` → redirect `/argocd/`; prefix `/argocd/` → cluster `argocd` with WebSocket upgrade (UI live updates).
* Cluster targets `${ARGOCD_HOST}:${ARGOCD_PORT}` (no path rewrite — rootpath keeps `/argocd`).
* Docker Compose and `.env` pass `ARGOCD_HOST` / `ARGOCD_PORT` for envsubst.

## Technical Design Decisions

* **Keep path prefix (no `prefix_rewrite`):** Matches Argo CD `server.rootpath=/argocd` (same idea as Grafana/Jaeger, not loadgen).
* **WebSocket upgrade:** Argo CD UI uses websockets for streaming updates.
* **`timeout: 0s`:** Avoid Envoy cutting long-lived UI/API streams.
* **Local compose host `argocd-server`:** Placeholder so envsubst succeeds; local stack does not run Argo CD unless operators add it.

## Implementation Details

1. Routes + cluster in `src/frontend-proxy/envoy.tmpl.yaml`.
2. Compose environment list includes `ARGOCD_HOST` / `ARGOCD_PORT`.
3. `.env` defaults for local envsubst.

## Files Changed

* `src/frontend-proxy/envoy.tmpl.yaml` — `/argocd` routes and cluster.
* `docker-compose.yml` — frontend-proxy env.
* `.env` — `ARGOCD_HOST`, `ARGOCD_PORT` defaults.
* `docs/changes/2026-07-14-frontend-proxy-argocd-route.md` — this change record.

## Dependencies and Cross-Repository Impact

* **techx-corp-infra:** Argo CD must use `server.insecure=true` + `server.rootpath=/argocd`; CloudFront blocks `/argocd`.
* **techx-corp-chart:** Set `ARGOCD_HOST=argocd-server.argocd.svc.cluster.local`, `ARGOCD_PORT=80` on frontend-proxy; promote image tag after bake.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | New path `/argocd/` on the proxy; storefront routes unchanged |
| **Deployment** | Requires multi-arch bake + ECR push + chart image tag update |
| **Security** | Path only useful with cluster Argo CD; public block is CloudFront’s job |
| **Backward compatibility** | Fully additive for other routes |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Config syntax | Manual review of Envoy YAML + envsubst vars | ✅ Present |

### Manual Verification

After image deploy:

```cmd
curl -i https://internal.hungtran.id.vn/argocd/
```

### Remaining Verification (Post-Merge)

* Bake/push release image set including frontend-proxy.
* Chart promote `default.image.tag` (dev auto or prod PR).
* VPN smoke for Argo login.

## Migration or Deployment Notes

```cmd
cd /d techx-corp-platform
REM Publish full release set (global tag), then promote chart values tag
make build-multiplatform-and-push
```

Ensure infra Argo CD rootpath apply is completed (or complete it before expecting UI success).

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Image not promoted | Medium | Low | Port-forward until tag rolls out |
| Argo CD still TLS-only | Low | Medium | Apply infra `server.insecure=true` first |

**Rollback procedure:** Revert Envoy route commit and redeploy previous frontend-proxy image tag.
