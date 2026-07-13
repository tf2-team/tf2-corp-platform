# Change: Local Build and Run Documentation

## Summary

Added `docs/LOCAL_BUILD_AND_RUN.md`, an operator/developer guide for building and running the TechX Corp platform stack locally with Docker Compose (full and minimal profiles, single-service rebuilds, URLs, protobuf generation, tests, and optional multi-arch bake).

## Context

The repository README only had a one-line Compose snippet. Contributors needed a single place under `docs/` covering env files, Make targets, Windows-friendly commands, hot-reload frontend workflow, and how local run differs from CI/ECR publish paths already documented in `CICD.md` and `DEPLOYMENT.md`.

* Why now: fill the local development documentation gap for the platform repo.
* Constraints: follow workspace shell presentation (CMD first) and avoid duplicating production deploy content.

## Before

* No dedicated local build/run document under `docs/`.
* Local instructions were split across `README.md`, `Makefile` comments, service READMEs, and workspace agent docs.

## After

* `docs/LOCAL_BUILD_AND_RUN.md` is the canonical local guide: prerequisites, `.env` / `.env.override`, `make start` / `start-minimal` / `stop`, build and redeploy, local URLs, frontend hot-reload, protobuf, tests, optional multi-platform bake, troubleshooting, and Makefile cheat sheet.
* README links to the new guide for discoverability.

## Technical Design Decisions

* Kept the guide in **English** to align with `docs/CICD.md` and the Makefile/README surface; production runbook remains Vietnamese-heavy in `DEPLOYMENT.md`.
* Documented both **Make** and raw **`docker compose --env-file .env --env-file .env.override`** so Windows operators without Make still have runnable steps.
* Did not invent new scripts or change Compose defaults—documentation only of existing behavior.
* Pointed multi-arch / ECR workflows at existing `CICD.md` rather than re-copying CI setup.

## Implementation Details

1. Wrote `docs/LOCAL_BUILD_AND_RUN.md` from `Makefile`, `docker-compose.yml`, `docker-compose.minimal.yml`, `docker-compose-tests.yml`, `.env`, and existing README/service notes.
2. Linked the guide from the root `README.md` “Run locally” section.
3. Recorded this change under `docs/changes/`.

## Files Changed

**Documentation:**

* `docs/LOCAL_BUILD_AND_RUN.md` — New local build and run guide.
* `docs/changes/2026-07-13-local-build-and-run-doc.md` — This change record.
* `README.md` — Link to the local guide under “Run locally”.

## Dependencies and Cross-Repository Impact

None. Local Compose remains self-contained in `techx-corp-platform`. No chart or infra changes.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | No runtime change |
| **Infrastructure** | No change |
| **Deployment** | No change to CI/CD or cluster deploy paths |
| **Performance** | No change |
| **Security** | Documents not committing secrets in `.env.override`; no new credentials |
| **Reliability** | No change |
| **Cost** | No change |
| **Backward compatibility** | Fully backward-compatible (docs only) |
| **Observability** | Documents existing local Grafana/Jaeger URLs |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| N/A | Docs-only change | Not run |

### Manual Verification

* Cross-checked Make targets (`start`, `start-minimal`, `stop`, `build`, `restart`, `redeploy`, protobuf, tests, multiplatform) against `Makefile`.
* Cross-checked local URLs against `make start` echo messages and frontend-proxy routing notes.
* Confirmed Compose env-file pattern matches `DOCKER_COMPOSE_ENV` in the Makefile.

### Remaining Verification (Post-Merge)

* Optional: contributor dry-run of `make start` on a clean machine using only this doc.

## Migration or Deployment Notes

None. No deploy action required. Operators/developers can use the new doc immediately after merge.

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Doc drift if Make/Compose targets change later | Medium | Low | Update this guide in the same PR as Makefile/Compose changes |
| Readers confuse local `latest` tags with CI `sha-*` / `v*` tags | Low | Low | Explicit cross-links to CICD.md |

**Rollback procedure:**

Delete `docs/LOCAL_BUILD_AND_RUN.md`, revert the README link, and remove or revert this change document.
