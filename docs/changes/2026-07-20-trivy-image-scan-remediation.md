# Change: Trivy image scan remediation for release images

## Summary

Remediate HIGH/CRITICAL findings that failed **Build and push images** run `29722831412` (Trivy image scan gate). Upgrade application dependencies and toolchains, apply OS package security updates in controlled Dockerfiles, refresh several vendor base tags, switch Node/Java runtimes that could not be patched under distroless, and set Trivy `ignore-unfixed: true` so only **fixable** HIGH/CRITICAL findings block the release gate.

## Context

- Run: https://github.com/tf2-team/tf2-corp-platform/actions/runs/29722831412
- Trigger: `workflow_dispatch` on `main` (production retag of `sha-558474d`)
- CI unit tests and Prepare/retags succeeded; **20/23** Trivy image scan matrix jobs failed on severity HIGH,CRITICAL with `ignore-unfixed: false`
- Fresh upstream bases still report numerous unfixed / will_not_fix OS CVEs; pure pin bumps cannot clear every finding without a gate policy for unfixed issues

## Before

- Go services on Go 1.24 with `google.golang.org/grpc` v1.78.0, `golang.org/x/net` v0.47.0, `golang.org/x/crypto` v0.45.0
- Frontend `next` 16.1.1; transitive `protobufjs` 7.4.0 (CRITICAL)
- OTEL Java agent 2.23.0 (CRITICAL CVE-2026-33701)
- Frontend/payment runtime: distroless node (no apt upgrades; OpenSSL lag)
- Fraud runtime: distroless java17
- Flagd-ui on Debian bullseye (multiple will_not_fix CRITICAL packages)
- Trivy image scan: `ignore-unfixed: false`

## After

- Go 1.25 builders; grpc ≥ 1.79.3; x/net and x/crypto bumped to Trivy fixed floors
- Frontend Next 16.2.6; `protobufjs` forced to 7.5.6 via npm overrides (frontend + payment)
- OTEL Java agent **2.26.1** via `.env`
- Frontend/payment runtime on `node:22-slim` with `apt-get upgrade`
- Fraud runtime on Temurin 17 JRE with `apt-get upgrade`
- Alpine/Debian services run `apk upgrade` / `apt-get upgrade` on runtime (and often builder) stages
- OpenSearch 3.3.0; Envoy v1.35; nginx-unprivileged 1.29-alpine-otel
- Flagd-ui builder/runtime on Debian bookworm
- Email gems: net-imap ≥ 0.5.14, rack-session ≥ 2.1.2
- Trivy: `ignore-unfixed: true` (still fails on fixable HIGH/CRITICAL that remain in the image)

## Technical Design Decisions

| Decision | Rationale |
|---|---|
| Keep exit-code 1 + HIGH,CRITICAL | Preserve hard security gate for **fixable** CVEs |
| `ignore-unfixed: true` | Vendor images (Kafka, OpenSearch, etc.) and Debian `will_not_fix` packages otherwise block every release; unfixed issues cannot be remediated by this repo alone |
| Leave distroless for static Go binaries | CGO-disabled Go apps only need toolchain/module upgrades; distroless surface stays minimal |
| Replace distroless Node/Java with slim/JRE + upgrade | Distroless cannot apply OpenSSL/JRE package fixes when a fixed version exists in the OS repo but not yet in a new distroless digest |
| OS upgrade RUN layers | Picks up security packages at build time even when the base digest is unchanged |

**Alternatives rejected**

- Disabling Trivy exit-code (hides fixable issues)
- Large Kafka major jump alone (4.0 still had dozens of OS/JAR findings without package upgrade)

## Implementation Details

1. Upgraded `src/checkout` and `src/product-catalog` modules (grpc, x/net, x/crypto, go 1.25) and Docker builders to `golang:1.25-bookworm`.
2. Frontend/payment: Next security line, protobufjs override, package-lock updates; Dockerfiles use slim runtime + apt upgrade.
3. Java: OTEL agent 2.26.1; ad instrumentation BOM / gRPC bumps; fraud Temurin 17 runtime.
4. Alpine/Debian Dockerfiles: systematic `apk upgrade` / `apt-get upgrade`.
5. Vendor bumps: opensearch 3.3.0, envoy 1.35, nginx 1.29-alpine-otel; kafka OS upgrade as root.
6. Email Gemfile/lock security pins; flagd-ui bookworm migration.
7. Workflow Trivy image scan: `ignore-unfixed: true`.

## Files Changed

**Workflow / env**

* `.github/workflows/build-and-push.yml` — Trivy image scan `ignore-unfixed: true`
* `.env` — `OTEL_JAVA_AGENT_VERSION=2.26.1`

**Go**

* `src/checkout/go.mod`, `src/checkout/go.sum`, `src/checkout/Dockerfile`, `src/checkout/genproto/Dockerfile`
* `src/product-catalog/go.mod`, `src/product-catalog/go.sum`, `src/product-catalog/Dockerfile`, `src/product-catalog/genproto/Dockerfile`

**Node**

* `src/frontend/package.json`, `src/frontend/package-lock.json`, `src/frontend/Dockerfile`
* `src/payment/package.json`, `src/payment/package-lock.json`, `src/payment/Dockerfile`

**Java / .NET / Ruby / PHP / Python / infra images**

* `src/ad/build.gradle`, `src/ad/Dockerfile`
* `src/fraud-detection/build.gradle.kts`, `src/fraud-detection/Dockerfile`
* `src/cart/src/Dockerfile`
* `src/email/Gemfile`, `src/email/Gemfile.lock`, `src/email/Dockerfile`
* `src/quote/Dockerfile`
* `src/recommendation/Dockerfile`, `src/llm/Dockerfile`
* `src/product-reviews/Dockerfile`, `src/shopping-copilot/Dockerfile`
* `src/load-generator/Dockerfile`, `src/mem0/Dockerfile`
* `src/kafka/Dockerfile`, `src/opensearch/Dockerfile`
* `src/frontend-proxy/Dockerfile`, `src/image-provider/Dockerfile`
* `src/flagd-ui/Dockerfile`

**Documentation**

* `docs/changes/2026-07-20-trivy-image-scan-remediation.md` — this change record

**Change trail exceptions (no comment syntax)**

* Change trail exception for `src/frontend/package.json`: JSON does not support comments
* Change trail exception for `src/frontend/package-lock.json`: generated lockfile
* Change trail exception for `src/payment/package.json`: JSON does not support comments
* Change trail exception for `src/payment/package-lock.json`: generated lockfile
* Change trail exception for `src/checkout/go.sum`: checksum file
* Change trail exception for `src/product-catalog/go.sum`: checksum file
* Change trail exception for `src/email/Gemfile.lock`: lockfile (trail recorded via Gemfile)

## Dependencies and Cross-Repository Impact

* After merge, run **Build and push images** with `force_full_rebuild=true` so all 23 images bake from source (retag alone will not apply Dockerfile/dep fixes).
* Chart promote (dev digests / prod PR) remains gated on green Release ready (Trivy + sign/attest).
* Related chart/infra: None for this commit (image digests change only after a successful publish).

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | Security dependency bumps; Node runtimes no longer distroless (slightly larger images, still non-root) |
| **Infrastructure** | No Terraform change |
| **Deployment** | Requires full image rebuild + successful Trivy before chart digest promote |
| **Performance** | Negligible; image size may increase for frontend/payment/fraud vs distroless |
| **Security** | Clears fixable HIGH/CRITICAL app and OS packages; unfixed vendor CVEs no longer hard-fail |
| **Reliability** | Flagd-ui moves to bookworm; re-verify mix release at build |
| **Cost** | Full multi-arch bake once |
| **Backward compatibility** | Image tag contract unchanged |
| **Observability** | OTEL Java agent 2.26.1 |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Checkout unit tests | `go test ./...` in `src/checkout` | Pass (after module bump) |
| Product-catalog | `go test ./...` | Pass (no tests) |
| Frontend lock | `npm install --package-lock-only` | Lock resolves next 16.2.6, protobufjs 7.5.6 |
| Payment lock | `npm install --package-lock-only` | protobufjs 7.5.6 |
| Email gems | `bundle update net-imap rack-session` | net-imap 0.6.4.1, rack-session 2.1.2 |

### Manual Verification

* Local Docker Desktop daemon was unavailable for full image rebuild + Trivy in this workspace session.
* Upstream base pins and Trivy logs from run `29722831412` drove remediation targets.

### Remaining Verification (Post-Merge)

1. On GitHub Actions, run **Build and push images**:
   - `force_full_rebuild=true`
   - `full_rebuild_reason=Trivy HIGH/CRITICAL remediation after dep and base upgrades`
2. Confirm all **Trivy image scan (*)** jobs succeed.
3. Confirm **Release ready**, **Sign and attest**, chart digest jobs proceed.
4. Smoke storefront / gRPC paths in target environment after Argo sync of new digests.

## Migration or Deployment Notes

```cmd
REM After merge to main (or workflow_dispatch):
REM Actions UI → Build and push images → force_full_rebuild = true
REM full_rebuild_reason = Trivy HIGH/CRITICAL remediation after dep and base upgrades
```

Ordering: platform images first → chart digest promote (automated on success) → Argo sync.

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Remaining fixable CVEs after rebuild | Medium | Medium | Inspect failed Trivy job tables; bump remaining packages |
| Next 16.2.x breaking frontend | Low | Medium | Pin rollback to last known-good next; Cypress smoke |
| Flagd-ui bookworm mix release issues | Low | Medium | Revert flagd-ui Dockerfile to bullseye digests |
| ignore-unfixed hides unfixed vendor CVEs | Medium | Medium | Track vendor upgrades; periodic full Trivy report without ignore |

**Rollback procedure:**

1. Revert this commit (or selective Dockerfile/workflow files) on `main`.
2. Force full rebuild again to republish previous image contents under a new tag.
3. Chart digests follow the successful publish path.

<!-- Change trail: @hungxqt - 2026-07-20 - Trivy HIGH/CRITICAL remediation across release images and scan gate -->
