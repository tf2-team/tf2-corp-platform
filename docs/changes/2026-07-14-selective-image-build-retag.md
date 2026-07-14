# Change: Selective image build and ECR retag in platform CI

## Summary

Platform Build & Push now classifies release services into **build from source** vs **retag from previous runtime tag**, so unchanged services skip multi-arch bake while still publishing the full 21-image set under one new global Helm tag.

## Context

Full 21-service multi-arch bake on every `src/**` change was slow and expensive when only one or a few services changed. ECR `:buildcache` only accelerates BuildKit layers; it does not skip rebuilds. Helm still requires a **single global** `default.image.tag` for every service, so partial catalogs cannot be promoted.

This change keeps the global tag contract by always ensuring all 21 images exist under `NEW_TAG`, while only baking services whose sources (or shared contracts) actually changed.

## Before

* Branch path filter: `src/**` only.
* Any workflow run baked **all 21** services from Dockerfiles and pushed `NEW_TAG`.
* `:buildcache` provided layer reuse only.
* No `PREV_TAG` retag path; no per-service change classification.

## After

* Branch path filter includes image-affecting shared files: `src/**`, `pb/**`, `docker-compose.yml`, `docker-bake.hcl`, `buildkitd.toml`, `.env`.
* `prepare` classifies services into `build_services` and `retag_services` (`mode`: `full` | `selective`).
* `preflight` verifies ECR repositories and moves retag candidates missing `PREV_TAG` into the build list.
* `build` matrix bakes only changed services (still uses `:buildcache`).
* `retag` matrix copies multi-arch manifests `PREV_TAG` → `NEW_TAG` via `docker buildx imagetools create`.
* `verify-ecr` still requires all 21 tags under `NEW_TAG`.
* Chart promote jobs unchanged (still write one global tag).
* `workflow_dispatch` gains `force_full_rebuild` (default `true`) and optional `previous_tag`.

## Technical Design Decisions

| Decision | Rationale |
|---|---|
| Retag unchanged services instead of per-service Helm tags | Preserves existing chart global tag contract and Argo promote path |
| Path map `src/<service>/` → release name | Matches Dockerfiles that `COPY ./src/<service>/…` |
| Shared paths force full bake | `pb/**`, compose, bake, `.env` affect many or all images |
| Preflight ECR existence check for `PREV_TAG` | Avoids retag failures when a prior publish was incomplete |
| Tag pushes and dispatch default to full bake | Safer for releases and manual republish |
| Non-release `src/*` does not force bake | e.g. flagd/grafana config is not a release image; retag-all still refreshes global tag |

Alternatives rejected:

* Per-service chart tags — large Helm/GitOps change, out of scope.
* Rely only on `:buildcache` — still schedules full bake matrix and multi-arch work.
* Skip unchanged services without retag — breaks global tag verify and Helm.

## Implementation Details

1. Extended `on.push.paths` and `workflow_dispatch` inputs in `build-and-push.yml`.
2. `prepare` checkout uses `fetch-depth: 0`; classifies via `git diff` of `github.event.before`…`github.sha`.
3. `PREV_TAG` for branch pushes: `sha-<7-char of before>`.
4. Full mode when: tags `v*`, force full, zero before SHA, shared paths, or missing prev tag for selective dispatch.
5. `preflight` outputs refined `build_services` / `retag_services` used by matrix jobs.
6. New `retag` job (parallel with `build`); no QEMU required.
7. `verify-ecr` and `release-ready` accept `build`/`retag` **skipped** when that side is empty; both skipped is a hard failure.
8. Documented behavior in `docs/CICD.md`.

## Files Changed

**Workflows:**

* `.github/workflows/build-and-push.yml` — Selective classify, refine, build matrix gate, retag job, gate updates, dispatch inputs, path filter.

**Documentation:**

* `docs/CICD.md` — Job graph, path filter, selective rebuild, retag vs buildcache, dispatch inputs, matrix settings.
* `docs/changes/2026-07-14-selective-image-build-retag.md` — This change record.

## Dependencies and Cross-Repository Impact

None. Chart and infra repositories are unchanged. Chart promote still consumes one global tag after all 21 images exist under that tag.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | No runtime code change |
| **Infrastructure** | No Terraform/ECR schema change; more `describe-images` / retag API use |
| **Deployment** | Same Helm global tag promote; faster CI when few services change |
| **Performance** | Large CI time savings on selective path; full rebuilds unchanged |
| **Security** | Same OIDC roles; retag requires existing image pull/push on same repos |
| **Reliability** | Missing `PREV_TAG` falls back to bake for that service; verify still gates promote |
| **Cost** | Lower GitHub Actions / multi-arch bake cost on selective runs |
| **Backward compatibility** | Full rebuild still available (tags, force full, shared paths) |
| **Observability** | Job summaries list build vs retag classification |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Workflow structure | Manual review of job `needs` / `if` / outputs | Implemented |
| Bake catalog (local) | `docker buildx bake … release --print` (operator env) | Optional operator check; bake files unchanged |

### Manual Verification

* Classification logic reviewed for: single-service change, `pb/**` full, empty before SHA full, missing PREV_TAG → move to build.
* Gate logic reviewed so skipped empty matrix side does not block verify when the other side succeeds.

### Remaining Verification (Post-Merge)

* Run on `techx-dev-corp` with a single-service `src/**` change: expect 1 bake + 20 retags; digests of retagged services match previous tag.
* Run with `pb/**` or `force_full_rebuild: true`: expect 21 bakes.
* Confirm chart promote still runs after `release-ready`.

## Migration or Deployment Notes

1. No new secrets or IAM permissions beyond existing ECR push roles (retag uses same registry login).
2. First selective run on a branch requires a prior successful publish under `sha-<before>`; otherwise preflight moves missing services to build (may become full bake).
3. Operators who need a full republish should use `workflow_dispatch` with `force_full_rebuild: true` (default).

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Mis-classified change leaves stale binary under new tag | Low | High | Shared paths force full bake; map only known release dirs |
| Incomplete PREV_TAG set | Medium | Medium | Preflight describe-images; missing → bake |
| Multi-arch retag failure | Low | Medium | Fail that service job; no chart promote until green |
| Both build and retag skipped | Low | High | release-ready hard-fails |

**Rollback procedure:**

```cmd
cd /d techx-corp-platform
git revert <commit-sha>
git push
```

Or restore the previous `build-and-push.yml` / `docs/CICD.md` from git history so every run bakes all 21 services again.
