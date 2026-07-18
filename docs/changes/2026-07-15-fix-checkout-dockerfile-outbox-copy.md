# Change: Fix checkout Dockerfile missing outbox package copy

## Summary

The checkout image build failed in CI after the durable outbox feature landed because the multi-stage Dockerfile never copied the new `outbox` package into the builder stage. This change adds `COPY ./src/checkout/outbox/ outbox/` so `go build` can resolve the local import.

## Context

Merge of PR #18 (`feat/directive-03-checkout-outbox`) introduced package `github.com/open-telemetry/techx-corp/src/checkout/outbox` and wired it from `main.go`. Unit tests and local `go build` succeeded (full source tree present), but the production image path only copies explicitly listed subdirectories.

CI failure on `main` (Build and push images run after PR #18 merge):

```text
main.go:60:2: no required module provides package
github.com/open-telemetry/techx-corp/src/checkout/outbox
ERROR: failed to solve: process "/bin/sh -c CGO_ENABLED=0 GOOS=linux go build ..."
exit code: 1
```

## Before

Builder stage copied only:

* `genproto/oteldemo/`
* `kafka/`
* `money/`
* `main.go`

`outbox/` existed in the repo but was omitted from the image build context, so Docker `go build` could not compile `main.go`.

## After

Builder stage also copies:

* `outbox/`

`go build` resolves the local outbox import the same way as local development.

## Technical Design Decisions

* Minimal fix: add one `COPY` line rather than switching to a broad `COPY ./src/checkout/ .` so test files and docs are still excluded from the build context (same pattern as sibling packages).
* No change to the Go module, outbox implementation, or runtime configuration.

## Implementation Details

1. Identified CI failure as missing package copy (not a dependency or Go version issue).
2. Added `COPY ./src/checkout/outbox/ outbox/` before `main.go` and the build `RUN`.
3. Left runtime stage and entrypoint unchanged.

## Files Changed

**Build:**

* `src/checkout/Dockerfile` — Copy `outbox/` into the builder stage so image compile succeeds.

**Documentation:**

* `docs/changes/2026-07-15-fix-checkout-dockerfile-outbox-copy.md` — This change record.

## Dependencies and Cross-Repository Impact

None. Chart and infra already describe the outbox table / IRSA path separately; this is an image build fix only.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | No runtime change once the image builds; restores the intended outbox feature path from PR #18 |
| **Infrastructure** | No change |
| **Deployment** | Unblocks checkout image bake/push so GitOps can promote a new tag |
| **Performance** | Negligible (one extra small package layer in builder) |
| **Security** | No change (outbox package was already intended for the image) |
| **Reliability** | Restores ability to ship checkout after outbox merge |
| **Cost** | No change |
| **Backward compatibility** | Fully backward-compatible |
| **Observability** | No change |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Local unit tests | `go test ./...` in `src/checkout` | ✅ Pass (prior to Dockerfile-only change; code unchanged) |
| Local package build | `go build .` in `src/checkout` | ✅ Pass |
| CI image bake | GitHub Actions `build-and-push` for `checkout` | ⏳ Remaining post-merge |

### Manual Verification

* Confirmed failed CI log line points at missing `outbox` package import during Docker `go build`.
* Confirmed `origin/main` contains `src/checkout/outbox/` while Dockerfile previously omitted it.

### Remaining Verification (Post-Merge)

* Re-run Build and push images for `checkout` on `main` (or merge this fix and confirm matrix job succeeds).
* Optional: `docker build -f src/checkout/Dockerfile .` when Docker Desktop is available.

## Migration or Deployment Notes

None beyond normal image publish → chart tag promote flow after CI succeeds.

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Unrelated compile error still present in image | Low | Medium | Local `go test`/`go build` already green; CI will surface next error if any |
| Broader COPY pattern preferred later | Low | Low | Can refactor Dockerfile separately |

**Rollback procedure:**

```cmd
cd /d techx-corp-platform
git revert <this-commit-sha>
```

Or restore the previous Dockerfile without the `outbox/` `COPY` line (image build would fail again for this feature).

<!-- Change trail: @hungxqt - 2026-07-15 - Document Dockerfile fix for missing outbox package copy -->
