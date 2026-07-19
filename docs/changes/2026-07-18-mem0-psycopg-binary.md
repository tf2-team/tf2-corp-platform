# Change: Fix Mem0 psycopg import on slim runtime (bundle libpq)

## Summary

The Mem0 production image failed at import time with `ImportError: no pq wrapper available` because `psycopg` was installed without a binary backend and the `python:slim-bookworm` base image does not ship system `libpq`. The production requirements pin is updated to `psycopg[binary]==3.2.8` so `psycopg_binary` and bundled libpq are installed into the image.

## Context

The migrate Job (`mem0-migrate-*`) runs:

```text
python scripts/bootstrap_rds_iam.py && alembic upgrade head
```

`bootstrap_rds_iam.py` (and the main API) import `psycopg`. On the slim runtime this raised:

```text
ImportError: no pq wrapper available.
- couldn't import psycopg 'c' implementation: No module named 'psycopg_c'
- couldn't import psycopg 'binary' implementation: No module named 'psycopg_binary'
- couldn't import psycopg 'python' implementation: libpq library not found
```

Why now: Mem0 migrate/bootstrap against RDS is in the chart path and depends on a working PostgreSQL client library inside the container.

## Before

* `src/mem0/requirements-production.txt` pinned `psycopg==3.2.8` (pure package only).
* Dockerfile runtime base: `python:${PYTHON_VERSION}-slim-bookworm` with no `apt` install of `libpq5`.
* Import of `psycopg` failed before any DB connection or Alembic migration could run.

## After

* Requirements pin: `psycopg[binary]==3.2.8` (installs `psycopg` + `psycopg-binary` with bundled libpq).
* No Dockerfile OS package change required.
* Unit contract test asserts the binary extra remains pinned while the image stays on slim-bookworm.

## Technical Design Decisions

* **Chosen:** `psycopg[binary]` extra — official path for containers that do not install system libpq; keeps the multi-stage slim image free of apt layers for PostgreSQL client libs.
* **Rejected:** install `libpq5` via `apt-get` on the runtime stage — works with pure `psycopg` but adds OS packages, update/cache cleanup, and CVE surface for a single shared library when the binary wheel already bundles what we need.
* **Rejected:** switch to `psycopg2-binary` — Mem0 stack and scripts use psycopg3 APIs; changing major packages is out of scope for this import fix.
* **Known limitation:** binary wheels are platform-specific; multi-arch bake must continue to build/install for each target arch (existing bake matrix already does this).

## Implementation Details

1. Updated `src/mem0/requirements-production.txt` to `psycopg[binary]==3.2.8` with an inline note that slim has no system libpq.
2. Extended `src/mem0/tests/test_production_image.py` with `test_psycopg_includes_binary_backend_for_slim_runtime` so a future pin of pure `psycopg` fails CI before image publish.
3. No chart or submodule script changes; the failure was purely packaging.

## Files Changed

**Dependencies:**
* `src/mem0/requirements-production.txt` — Pin `psycopg[binary]==3.2.8` instead of pure `psycopg==3.2.8`.

**Tests:**
* `src/mem0/tests/test_production_image.py` — Assert binary extra remains required for slim runtime.

**Documentation:**
* `docs/changes/2026-07-18-mem0-psycopg-binary.md` — This change record.

## Dependencies and Cross-Repository Impact

* **Chart:** no template change. After the new image is published and chart `default.image.tag` / `mem0.image.tag` is promoted, the migrate Job and Deployment pick up the fixed image automatically via Argo CD.
* **Infra:** None.
* **Mem0 submodule (`third-party/mem0`):** None for this packaging fix; bootstrap script remains in the forked server tree.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | `import psycopg` succeeds; migrate bootstrap and API DB access can proceed past import |
| **Infrastructure** | No change |
| **Deployment** | Requires rebuild + push of the `mem0` image and chart image-tag promote |
| **Performance** | Negligible; binary backend is the intended production path |
| **Security** | Bundled libpq from the wheel instead of distro package; still no root runtime |
| **Reliability** | Unblocks Mem0 migrate Job and readiness path that depend on PostgreSQL |
| **Cost** | One selective mem0 image rebuild (not full 22-service bake if only mem0 paths change) |
| **Backward compatibility** | Fully compatible for consumers of the same psycopg 3.2.8 API |
| **Observability** | No change |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Unit tests | `python -m unittest src.mem0.tests.test_production_image` (from platform root after path setup) | Pending operator/CI after commit |
| Image import smoke | rebuild mem0 image, then `python -c "import psycopg; print(psycopg.__version__)"` in container | Pending post-build |

### Manual Verification

* Confirmed error stack matches pure-psycopg-on-slim without `psycopg_binary` or system libpq.
* Confirmed requirements and Dockerfile base combination before the change.

### Remaining Verification (Post-Merge)

1. Rebuild and push the mem0 image (platform CI matrix for `src/mem0/**`, or local bake).
2. Promote chart image tag (dev auto-update / prod PR as usual).
3. Confirm migrate Job completes: bootstrap + `alembic upgrade head`.
4. Confirm Mem0 Deployment readiness (`/health/ready`).

## Migration or Deployment Notes

1. Merge this change in `techx-corp-platform`.
2. Allow (or trigger) image publish so `mem0:<NEW_TAG>` is in ECR for all arches.
3. Update chart values image tag for the target environment (dev may auto-promote; prod via PR).
4. Let Argo CD recreate `mem0-migrate-<tag>` and roll the Deployment.
5. Do **not** use break-glass `helm upgrade` / `kubectl` mutation on auto-synced chart resources.

```cmd
cd /d techx-corp-platform
python -m unittest discover -s src\mem0\tests -p "test_*.py"
```

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Binary wheel unavailable for a target arch in bake | Low | Medium | Bake fails loudly; fall back to install `libpq5` on runtime stage if needed |
| Image size increase from binary wheel | Low | Low | Acceptable vs broken migrate path |

**Rollback procedure:**

1. Revert `src/mem0/requirements-production.txt` (and the test assert) to pure `psycopg==3.2.8` only if an alternative libpq approach is shipped first.
2. Rebuild/retag mem0 and re-promote chart values.
3. Or pin chart to previous known-good image tag that still cannot import psycopg — rollback to pure package alone will restore the failure; prefer keeping binary pin.

<!-- Change trail: @hungxqt - 2026-07-18 - Document mem0 psycopg[binary] slim-image fix. -->
