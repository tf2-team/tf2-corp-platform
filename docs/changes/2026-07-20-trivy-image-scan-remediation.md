# Change: Trivy image scan remediation for release images

## Summary

Remediate HIGH/CRITICAL findings that failed **Build and push images** Trivy gates (runs `29722831412` then `29728062895`). Upgrade application dependencies and toolchains, apply OS package security updates in controlled Dockerfiles, refresh vendor bases (Kafka, OpenSearch), force Jackson/Netty and Node/Python/Ruby/Go floors, remove unused Temurin `pebble` gobinary, and keep Trivy `ignore-unfixed: true` so only **fixable** HIGH/CRITICAL findings block the release gate.

## Context

- Primary follow-up run: https://github.com/tf2-team/tf2-corp-platform/actions/runs/29728062895
- Prior run (first remediation wave): https://github.com/tf2-team/tf2-corp-platform/actions/runs/29722831412
- Trigger: `workflow_dispatch` on `main`
- CI unit tests and Prepare/build succeeded; Trivy image scan matrix failed on severity HIGH,CRITICAL for fixable library and OS findings
- Gate: `ignore-unfixed: true`, exit-code 1 on remaining fixable HIGH/CRITICAL

## Before

**After first remediation wave (still failing run 29728062895):**

| Service | Representative fixable findings |
|---|---|
| checkout, product-catalog | OTEL Go `v1.39.0` (CVE-2026-29181/24051/39883), flagd/core `v0.12.1` (GHSA-4c5f-9mj4-m247) |
| frontend, payment | `@grpc/grpc-js` 1.12.6, otel auto-instrumentations 0.67.3, protobufjs 7.5.6, fast-uri 3.0.x, picomatch 4.0.3, lodash 4.17.21 |
| ad, fraud-detection | jackson-databind 2.20.1, Netty 4.1.130 / mixed 4.2.7; Temurin `/usr/bin/pebble` Go HIGH |
| email | default gems erb/zlib/net-imap/puma below fixed floors (CRITICAL on net-imap, zlib) |
| mem0 | python-jose 3.3.0 CRITICAL, cryptography 46.x, starlette 0.45.x |
| product-reviews, shopping-copilot | torch 2.3.1 CRITICAL, transformers 4.41.x, json_repair 0.23.x; copilot also langchain-core / langgraph-checkpoint |
| kafka | apache/kafka 3.9.1 JARs (jackson 2.16.2, netty 4.1.119, kafka-clients 3.9.1) |
| opensearch | vendor 3.3.0 Amazon Linux package storm (100+ HIGH) |

## After

| Area | Remediation |
|---|---|
| Go (checkout, product-catalog) | OTEL `v1.43.0` (+ matching exporters/sdk), flagd provider `v0.6.0` / flagd/core `v0.16.0`, go `1.25.5` |
| Node (frontend, payment) | `@grpc/grpc-js` 1.12.7, `@opentelemetry/auto-instrumentations-node` 0.75.0; overrides for protobufjs 7.6.1, fast-uri 3.1.2, picomatch 4.0.4, sigstore 4.1.1, lodash 4.18.0, grpc-js |
| Java (ad, fraud-detection) | jackson 2.21.4 + Netty BOM/force `4.1.135.Final`; remove `/usr/bin/pebble` from Temurin runtime |
| Ruby (email) | Gemfile pins erb ≥4.0.4.1, zlib ≥3.2.3, puma ≥7.2.1; lock erb 6.0.6 / puma 8.0.2 / zlib 3.2.3; Docker `gem install` fixed default gems |
| mem0 | cryptography 48.0.1, python-jose 3.5.0, fastapi 0.139.2, starlette 1.3.1 |
| ai-common (+ reviews/copilot images) | torch 2.6.0, transformers 5.5.0, json-repair 0.60.1, cryptography 48.0.1 |
| shopping-copilot | langgraph 1.2.9, langchain-core 1.4.9, langgraph-checkpoint 4.1.1 |
| kafka | base `apache/kafka:4.3.1@sha256:77e3df90…` (+ existing apk upgrade) |
| opensearch | base `opensearchproject/opensearch:3.7.0@sha256:44ba7ea5…` (+ package upgrade) |
| OTEL Java agent | `.env` `OTEL_JAVA_AGENT_VERSION=2.29.0` |
| Trivy policy | `ignore-unfixed: true` retained (only fixable HIGH/CRITICAL block) |

## Technical Design Decisions

| Decision | Rationale |
|---|---|
| Keep exit-code 1 + HIGH,CRITICAL | Preserve hard security gate for **fixable** CVEs |
| `ignore-unfixed: true` | Vendor images still expose unfixed/will_not_fix OS CVEs that this repo cannot patch |
| Force Netty 4.1.135 line (not 4.2.x mix) | gRPC-Java brings mixed Netty lines; BOM + `resolutionStrategy.force` collapses to one fixed floor |
| Remove Temurin `pebble` | Unused gobinary on JRE image contributes HIGH x/net/stdlib; not required by ad/fraud |
| Kafka 4.3.1 (KRaft already in use) | Dockerfile already uses controller+broker roles; 4.1.2+ fixes kafka-clients CVE-2026-35554 and refreshes Jackson/Netty |
| OpenSearch 3.7.0 vendor jump | OS package volume cannot be fixed via app deps alone |
| langgraph 1.x | checkpoint CVE only fixed in ≥3.0.0; langgraph 1.2.x requires checkpoint ≥4.1 and langchain-core ≥1.4.7 |
| Default gem reinstall in email image | Trivy scans Ruby default gemspecs even when Bundler has newer locked gems |

**Alternatives rejected**

- Disabling Trivy exit-code (hides fixable issues)
- Leaving Kafka/OpenSearch on old tags with trivyignore only (no actual reduction of fixable surface)

## Implementation Details

1. **Go:** `go get` OTEL 1.43.x and flagd/core 0.16 via providers/flagd v0.6.0; `go mod tidy`; checkout unit tests pass.
2. **Node:** Bump direct pins + npm `overrides`; regenerate package-lock for frontend and payment.
3. **Java:** jackson/netty floors + force resolution; Dockerfile removes pebble.
4. **Email:** Gemfile security pins; `bundle update`; Docker installs matching default gems.
5. **Python:** ai-common torch/transformers/json-repair/cryptography; mem0 jose/fastapi/starlette; copilot langgraph stack.
6. **Vendor images:** Kafka 4.3.1 and OpenSearch 3.7.0 multi-arch digests from Docker Hub; retain OS upgrade RUN layers.
7. **Agent:** OTEL Java agent 2.29.0 via `.env`.

## Files Changed

**Env / agent**

* `.env` — `OTEL_JAVA_AGENT_VERSION=2.29.0`

**Go**

* `src/checkout/go.mod`, `src/checkout/go.sum`
* `src/product-catalog/go.mod`, `src/product-catalog/go.sum`

**Node**

* `src/frontend/package.json`, `src/frontend/package-lock.json`
* `src/payment/package.json`, `src/payment/package-lock.json`

**Java**

* `src/ad/build.gradle`, `src/ad/Dockerfile`
* `src/fraud-detection/build.gradle.kts`, `src/fraud-detection/Dockerfile`

**Ruby**

* `src/email/Gemfile`, `src/email/Gemfile.lock`, `src/email/Dockerfile`

**Python**

* `src/ai-common/pyproject.toml`
* `src/mem0/requirements-production.txt`
* `src/shopping-copilot/requirements.txt`

**Vendor images**

* `src/kafka/Dockerfile` — apache/kafka 4.3.1
* `src/opensearch/Dockerfile` — opensearch 3.7.0

**Documentation**

* `docs/changes/2026-07-20-trivy-image-scan-remediation.md` — this change record (updated for run 29728062895)

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
* Kafka client services already on kafka-clients 4.x for fraud-detection; verify compose smoke after Kafka 4.3.1 base.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | Security dependency bumps; langgraph 1.x for copilot; puma 8 for email; possible minor API surface changes in OTEL/flagd |
| **Infrastructure** | No Terraform change |
| **Deployment** | Requires full image rebuild + successful Trivy before chart digest promote |
| **Performance** | Negligible; torch 2.6 and transformers 5.5 may change AI memory profile |
| **Security** | Clears fixable HIGH/CRITICAL from failed matrix services; vendor OS residual may remain unfixed |
| **Reliability** | Kafka 4.3.1 / OpenSearch 3.7.0 need post-deploy smoke |
| **Cost** | Full multi-arch bake once |
| **Backward compatibility** | Image tag contract unchanged |
| **Observability** | OTEL Java agent 2.29.0 |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Checkout unit tests | `go test ./...` in `src/checkout` | ✅ Pass |
| Product-catalog | `go test ./...` | ✅ Pass (no tests) |
| Frontend/payment locks | `npm install --package-lock-only` | ✅ grpc-js 1.12.7, protobufjs 7.6.1, overrides applied |
| Email gems | `bundle update` | ✅ erb 6.0.6, puma 8.0.2, zlib 3.2.3, net-imap 0.6.4.1 |
| Langgraph import | `from langgraph.graph import StateGraph, START, END` | ✅ Pass |
| Pip resolve mem0 | dry-run fastapi/starlette/jose/cryptography | ✅ Resolves |
| Pip resolve torch stack | dry-run torch 2.6 / transformers 5.5 | ✅ Resolves |

### Manual Verification

* Local Docker Desktop daemon was unavailable for full image rebuild + Trivy in this workspace session.
* CVE fixed-version floors taken from Trivy tables in run `29728062895`.

### Remaining Verification (Post-Merge)

1. On GitHub Actions, run **Build and push images**:
   - `force_full_rebuild=true`
   - `full_rebuild_reason=Trivy HIGH/CRITICAL remediation run 29728062895`
2. Confirm all **Trivy image scan (*)** jobs succeed (especially opensearch/kafka if residual fixable CVEs remain on vendor libs).
3. Confirm **Release ready**, **Sign and attest**, chart digest jobs proceed.
4. Smoke storefront, checkout, Kafka consume (fraud-detection), OpenSearch log path, product-reviews/copilot guardrails after Argo sync.

If OpenSearch/Kafka still report fixable HIGH after 3.7.0/4.3.1, capture residual CVE list and either bump again or document vendor-only residual with tracked follow-up (do not weaken the gate without explicit approval).

## Migration or Deployment Notes

```cmd
REM After merge to main (or workflow_dispatch):
REM Actions UI → Build and push images → force_full_rebuild = true
REM full_rebuild_reason = Trivy HIGH/CRITICAL remediation run 29728062895
```

Ordering: platform images first → chart digest promote (automated on success) → Argo sync.

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Residual fixable CVEs on vendor Kafka/OpenSearch after base bump | Medium | Medium | Inspect failed Trivy job tables; bump base again or vendor-track |
| langgraph 1.x behavioral change in copilot | Medium | Medium | Unit tests + CI shopping-copilot job; pin rollback to 0.3.34 only if gate allows exception |
| torch/transformers major jump breaks llm-guard scanners | Medium | Medium | product-reviews CI; pin to last good if load fails at import |
| Netty force breaks gRPC native epoll | Low | High | Integration smoke; loosen force to BOM-only if needed |
| puma 8 config differences for email | Low | Medium | Smoke email path; pin puma 7.2.x if needed |

**Rollback procedure:**

1. Revert this commit (or selective Dockerfile/dep files) on `main`.
2. Force full rebuild again to republish previous image contents under a new tag.
3. Chart digests follow the successful publish path.

<!-- Change trail: @hungxqt - 2026-07-20 - Second-wave Trivy fixes for run 29728062895 (Go/Node/Java/Ruby/Python/Kafka/OpenSearch) -->
