# Change: Local Grafana — Remove First-Login Forced Password Change

## Summary

Stop Grafana’s first-login change-password screen in the local Docker Compose stack by setting a non-default initial admin password in `src/grafana/grafana.ini`. Grafana’s UI hardcodes that interstitial when the typed password is the literal string `admin`; there is no configuration flag to disable it.

## Context

Local Grafana (`grafana/grafana:12.3.1` via Compose) used the default admin password `admin`, which always triggers the change-password view after login. Operators/developers expect to open dashboards immediately at `http://localhost:8080/grafana/` after `make start`.

* Needed for smoother local demo and day-to-day development.
* Related chart/cluster work: `techx-corp-chart/docs/changes/2026-07-14-grafana-disable-force-password-change.md`.

## Before

`src/grafana/grafana.ini` left `admin_user` / `admin_password` commented, so Grafana defaults applied:

```ini
;admin_user = admin
;admin_password = admin
```

First login with user `admin` / password `admin` showed the change-password form (Skip available unless strong password policy is on).

## After

```ini
[security]
admin_user = admin
admin_password = otel
```

New local stacks create the admin user with password `otel`, so login does not open the change-password interstitial.

## Technical Design Decisions

* **Chosen:** Set `admin_password = otel` in the mounted `grafana.ini` (aligned with other local demo credentials such as Postgres `otel`).
* **Rejected:** Keeping password `admin` and relying on Skip — still shows the interstitial every login.
* **Rejected:** Invented ini keys such as `disable_initial_admin_password_change` — not present in Grafana source.
* **Limitation:** Setting only affects **first** admin user creation. Existing Compose volumes with a previous `grafana.db` keep the old password until the volume is removed or the password is reset.

## Implementation Details

1. Uncomment and set `admin_user` / `admin_password` under `[security]` in `src/grafana/grafana.ini`.
2. No Compose service definition changes; the file is already mounted at `/etc/grafana/grafana.ini`.
3. Document local credentials for operators (this change record).

## Files Changed

**Configuration:**

* `src/grafana/grafana.ini` — Set `admin_user = admin`, `admin_password = otel`.

**Documentation:**

* `docs/changes/2026-07-14-grafana-disable-force-password-change.md` — This change record.

## Dependencies and Cross-Repository Impact

* Related cluster fix and operator notes: `techx-corp-chart` values + `docs/operations/external-secrets.md` (ASM must not use `admin-password: admin`).
* No infra changes.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | Local Grafana login with `admin` / `otel` skips change-password UI on fresh data |
| **Infrastructure** | No change |
| **Deployment** | Restart Grafana container / recreate volume if DB already initialized |
| **Performance** | No change |
| **Security** | Local-only non-default password; still a demo credential, not for production |
| **Reliability** | Fewer login friction steps for local demos |
| **Cost** | No change |
| **Backward compatibility** | Existing local `grafana` volumes still use old password until wiped/reset |
| **Observability** | No change |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Config present | Grep `admin_password = otel` in `src/grafana/grafana.ini` | ✅ Present |

### Manual Verification

* Config review only in this change. Post-change local check:

```cmd
cd /d techx-corp-platform
make start
REM open http://localhost:8080/grafana/  login admin / otel
```

### Remaining Verification (Post-Merge)

1. Fresh start (no old Grafana volume) and confirm no change-password screen.
2. If an old volume exists and password is still `admin`, either:

```cmd
docker volume ls
REM remove the grafana data volume if safe for local-only data, then make start
```

or:

```cmd
docker exec -it grafana grafana cli admin reset-admin-password otel
```

## Migration or Deployment Notes

1. Restart Grafana after pulling this change:

```cmd
cd /d techx-corp-platform
make restart service=grafana
```

2. If the change-password UI still appears, the SQLite DB was created earlier with password `admin` — reset or wipe as above.
3. Local credentials after this change: **user `admin`, password `otel`** (fresh volume).

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Developers still try password `admin` | Medium | Low | Document `otel` in this change record; reset CLI if needed |
| Existing volume keeps old password | High for long-lived local stacks | Low | Reset password or remove volume |

**Rollback procedure:**

1. Revert `src/grafana/grafana.ini` to commented defaults (`;admin_password = admin`).
2. Reset password or recreate volume if needed.

<!-- Change trail: @hungxqt - 2026-07-14 - Local Grafana non-default admin_password to skip change-password UI. -->
