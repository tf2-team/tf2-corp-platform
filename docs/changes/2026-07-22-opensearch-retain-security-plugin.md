# Change: Retain OpenSearch Security Plugin in Custom Image (SEC-06)

## Summary

The customized OpenSearch image no longer removes the vendor `opensearch-security` plugin. Chart SEC-06 clients already use `https://opensearch:9200` with basic auth; stripping the plugin left the node on plain HTTP, so OTel Collectors failed TLS handshakes, dropped all logs, and Grafana traces→logs drilldown had no recent data.

## Context

* Production diagnosis (2026-07-22, `techx-corp-prod`): OpenSearch answered HTTP 200 on `:9200` and rejected HTTPS (`wrong version number` / `packet length too long`).
* Collectors logged continuous `tls: first record does not look like a TLS handshake` on the `opensearch` exporter and dropped log batches.
* Log indices stopped after `otel-logs-2026-07-14`; no `otel-logs-*` for 2026-07-15 onward.
* Root cause: `src/opensearch/Dockerfile` deleted `opensearch-security` while chart values required HTTPS + basic auth (SEC-06).
* Option B (chosen): keep the security plugin in the image so the chart HTTPS contract works; continue stripping unrelated heavy plugins.

## Before

* Dockerfile `rm -rf` included `/usr/share/opensearch/plugins/opensearch-security`.
* Live image plugins: only `opensearch-index-management`, `opensearch-job-scheduler`, `opensearch-sql`.
* Node served plain HTTP; demo TLS PEMs were never installed.
* Bake/CICD docs described a generic “unused plugins removed” image without calling out security as required.

## After

* Dockerfile keeps `opensearch-security` and asserts the directory remains after the slim step.
* Still strips ML, k-NN, alerting, security-analytics, observability UI plugins, etc.
* Jackson databind pin replaces any module/plugin-local copies found (including security if present); never installs into global `lib/`.
* CICD and bake comments document that security is retained for SEC-06.

## Technical Design Decisions

* **Keep security vs flip clients to HTTP (Option A):** Option A would restore logs faster without an image rebuild but abandons SEC-06 auth/TLS. Option B restores the intended security posture and matches existing chart/Grafana/OTel config.
* **Keep demo TLS (chart-side):** Chart already sets `DISABLE_INSTALL_DEMO_CONFIG=false` and HTTPS skip-verify; no chart protocol change required once the image includes the plugin.
* **Jackson pin:** Generalize replace-all plugin/module copies so retaining security does not reintroduce an unpinned jackson-databind jar if the vendor ships one inside the plugin.
* **Local Compose:** Still may set `DISABLE_SECURITY_PLUGIN=true` for lightweight local stacks; that is independent of plugin presence in the image.

## Implementation Details

1. Remove `opensearch-security` from the Dockerfile plugin deletion list.
2. Fail the image build if `opensearch-security` (or SQL / ILM / job-scheduler) is missing after slim.
3. Replace jackson-databind in every `modules/*` and `plugins/*` path that ships a copy; assert global `lib/` has none.
4. Update `docker-bake.hcl` and `docs/CICD.md` image contract language.

## Files Changed

**Image:**
* `src/opensearch/Dockerfile` — Retain `opensearch-security`; assert essential plugins; generalize jackson pin.

**Build / docs:**
* `docker-bake.hcl` — Comment that security is retained.
* `docs/CICD.md` — Document security retention and base version 3.7.0.
* `docs/changes/2026-07-22-opensearch-retain-security-plugin.md` — This change record.

## Dependencies and Cross-Repository Impact

* **Requires chart contract (already present):** HTTPS OpenSearch exporter + Grafana datasource, `DISABLE_INSTALL_DEMO_CONFIG=false`, ESO secret `techx-corp-opensearch`.
* Related: `techx-corp-chart/docs/changes/2026-07-22-opensearch-security-image-contract.md`
* After merge: rebuild/push the full release image set (global tag), verify ECR `opensearch` tag, then promote chart `default.image.tag` (dev auto-promote if applicable; prod via chart PR).

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | No storefront change |
| **Infrastructure** | OpenSearch container image includes security plugin again (~larger image vs fully stripped) |
| **Deployment** | New image tag required; OpenSearch pod restart; first start may install demo TLS certs |
| **Security** | Restores TLS + basic auth on the log store when chart SEC-06 env is active |
| **Observability** | Restores OTel → OpenSearch log export; Grafana Explore logs and traces→logs drilldown can work again after data resumes |
| **Reliability** | Removes permanent TLS handshake drop loop on log pipeline |
| **Backward compatibility** | Clients that still use plain HTTP to `:9200` will fail once security+HTTPS is active (intended) |
| **Cost** | Negligible (single-node log store; slightly larger image pull) |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Dockerfile static review | Manual review of plugin keep/assert + jackson pin | ✅ Implemented |
| Image build | `docker buildx bake -f docker-compose.yml -f docker-bake.hcl opensearch` (or full `release`) | Pending operator / CI |
| Runtime plugin list | `ls plugins` in running container must include `opensearch-security` | Pending post-deploy |

### Manual Verification

* Pre-fix prod evidence: HTTPS fail, HTTP 200, collector TLS drop errors, no `otel-logs` after 2026-07-14.
* Post-deploy (operator):
  * `curl -sk -u admin:<password> https://localhost:9200/_cluster/health` → green/yellow
  * New `otel-logs-YYYY-MM-DD` index appears and grows
  * Collector logs free of sustained `tls: first record does not look like a TLS handshake`
  * Grafana Explore OpenSearch returns recent logs; Jaeger span “Logs for this span” returns correlated rows when apps emit `traceId`/`spanId`

### Remaining Verification (Post-Merge)

1. CI bake + push of release images including `opensearch`.
2. Promote image tag to chart (dev then prod).
3. Confirm secret `techx-corp-opensearch` password meets OpenSearch strength rules.
4. Smoke Grafana logs + traces→logs drilldown.

## Migration or Deployment Notes

1. Merge platform change and wait for image CI (or manual bake/push of `opensearch` at least; release group uses global tag so full set is typical).
2. Ensure ASM/ESO OpenSearch password is set (upper, lower, digit, special).
3. Promote chart image tag so StatefulSet pulls the new digest/tag.
4. Watch `opensearch-0` Ready (startup probe allows ~6.5 minutes).
5. Verify HTTPS + auth from inside the pod; confirm collectors resume exports.
6. If node CrashLoops with `No SSL configuration found`, confirm `DISABLE_INSTALL_DEMO_CONFIG=false` (chart) and that demo install can write certs (not blocked by a broken volume mount). Do not re-strip the security plugin.

```cmd
cd /d techx-corp-platform
REM After env files are set for the target registry/project:
docker buildx bake -f docker-compose.yml -f docker-bake.hcl opensearch --push
```

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Demo TLS bootstrap fails on existing PVC | Low | High | Check pod logs; ensure chart demo-config env; restore previous image tag if needed |
| Admin password mismatch after security re-enable | Medium | Medium | Align ASM password with security index; follow SEC-06 secret runbook |
| Image size / cold start increase | Medium | Low | Acceptable; startupProbe already sized for security bootstrap |
| Local compose with security disabled still works | Low | Low | `DISABLE_SECURITY_PLUGIN=true` remains valid when plugin is present |

**Rollback procedure:**

1. Rebuild/redeploy previous OpenSearch image tag that stripped security **only if** chart clients are also switched back to HTTP (otherwise log pipeline stays broken).
2. Prefer rolling forward: fix password/TLS bootstrap rather than re-stripping security.

<!-- Change trail: @hungxqt - 2026-07-22 - Retain opensearch-security in custom image for SEC-06. -->
