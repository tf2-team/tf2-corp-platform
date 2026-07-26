# Change: Numeric USER for Distroless Checkout, Product-Catalog, Shipping

## Summary

Changed the final-stage `USER` instruction in the checkout, product-catalog, and shipping Dockerfiles from the named user `nonroot` to numeric UID `65532` so Kubernetes can verify `runAsNonRoot` when the pod security context does not supply `runAsUser`.

## Context

Pods for checkout, product-catalog, and shipping failed at container create with:

```text
Error: container has runAsNonRoot and image has non-numeric user (nonroot), cannot verify user is non-root
```

A prior Semgrep hardening change (2026-07-20) added explicit `USER nonroot` before each process entrypoint. Distroless `:nonroot` bases map that name to UID 65532, but kubelet only accepts a **numeric** image user (or an explicit numeric `runAsUser` in the pod spec) when `runAsNonRoot: true` is set.

## Before

* Final stages used distroless `:nonroot` bases with `USER nonroot`.
* Chart default component `securityContext` set `runAsNonRoot: true` without a numeric `runAsUser`.
* Kubelet rejected the create path for the three services.

## After

* Dockerfiles use `USER 65532` (distroless nonroot UID) immediately before `ENTRYPOINT`/`CMD`.
* Static non-root intent remains explicit for Semgrep-style checks; the value is numeric so kubelet can verify.

## Technical Design Decisions

* **Numeric UID 65532 vs name `nonroot`.** Same identity as distroless nonroot; only the form of the instruction changes. Numeric form is required by kubelet’s runAsNonRoot check when the pod does not set `runAsUser`.
* **Keep explicit `USER` before process instruction.** Preserves the Semgrep `missing-user` / `missing-user-entrypoint` intent from the 2026-07-20 change.
* **Do not invent a different UID (e.g. 10001).** These images do not create a 10001 user; 65532 matches the base image.

## Implementation Details

1. `src/checkout/Dockerfile` — `USER nonroot` → `USER 65532`.
2. `src/product-catalog/Dockerfile` — same.
3. `src/shipping/Dockerfile` — same.
4. Added a short Dockerfile comment explaining why the UID must be numeric.

## Files Changed

**Dockerfiles:**
* `src/checkout/Dockerfile` — numeric nonroot UID before `ENTRYPOINT`.
* `src/product-catalog/Dockerfile` — numeric nonroot UID before `ENTRYPOINT`.
* `src/shipping/Dockerfile` — numeric nonroot UID before `CMD`.

**Documentation:**
* `docs/changes/2026-07-21-fix-distroless-numeric-user.md` — This change record.

## Dependencies and Cross-Repository Impact

* Related chart change: `techx-corp-chart/docs/changes/2026-07-21-fix-distroless-runasuser.md` sets component `securityContext.runAsUser: 65532` for the same three services so existing images can start before rebuild, and so pod specs remain explicit after redeploy.
* Images must be rebuilt and retagged for the Dockerfile `USER` layer to appear in registries. Chart-side `runAsUser` can unblock pods before that rebuild.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | No process logic change; process still runs as distroless nonroot UID 65532 |
| **Infrastructure** | No change |
| **Deployment** | Rebuild and promote checkout, product-catalog, shipping images; chart overlay optional but recommended |
| **Performance** | None |
| **Security** | Same non-root runtime; fixes create failure under hardened pod security |
| **Reliability** | Restores pod startup for the three services under `runAsNonRoot: true` |
| **Cost** | None |
| **Backward compatibility** | Fully compatible with distroless nonroot base images |
| **Observability** | No change |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Grep USER | Inspect final `USER` lines in the three Dockerfiles | ✅ `USER 65532` |
| Unit tests | Not re-run (Dockerfile-only) | N/A |

### Manual Verification

* Confirmed only checkout, product-catalog, and shipping production Dockerfiles used `USER nonroot`.
* Confirmed other services already use numeric `USER` (e.g. `10001`) or chart `runAsUser`.

### Remaining Verification (Post-Merge)

* Rebuild and push the three images.
* Confirm pods leave `CreateContainerConfigError` and become Ready after chart sync and/or image roll.

## Migration or Deployment Notes

1. Merge platform Dockerfile change and rebuild:

```cmd
cd /d techx-corp-platform
REM rebuild/push checkout, product-catalog, shipping via bake or CI
```

2. Merge chart `runAsUser: 65532` (related change) so Argo CD can start pods even before the new image layer is live.
3. Smoke-test checkout, product-catalog, and shipping readiness.

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Semgrep still expects username `nonroot` | Low | Low | Numeric USER still satisfies non-root rules; re-check CI if a custom rule appears |
| Wrong UID if base image changes nonroot mapping | Low | Medium | Distroless documents 65532 for nonroot; pin base digests already |

**Rollback procedure:**

Revert the three Dockerfiles to `USER nonroot` only if paired with a chart `runAsUser` numeric override; otherwise pods will fail again under default `runAsNonRoot: true`.

<!-- Change trail: @hungxqt - 2026-07-21 - Document numeric USER 65532 fix for checkout, product-catalog, shipping -->
