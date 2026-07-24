# Change: Restore the OpenSearch SEC-06 runtime contract

## Summary

Retain `opensearch-security` in the first-party OpenSearch image so production
continues to provide HTTPS and basic authentication required by Grafana and the
OpenTelemetry Collector. The CI smoke test now exercises that production-mode
HTTPS/auth path instead of disabling security.

## Root cause

The production image removed `opensearch-security`, leaving port 9200 on plain
HTTP while the reviewed chart contract still requires HTTPS. Grafana datasource
health failed and the Collector could not export current logs. An earlier repair
also replaced Jackson 3.x dependencies with 2.x and failed startup with
`ClassNotFoundException`.

## Implementation

- Keep `opensearch-security`; continue removing unrelated optional plugins.
- Preserve Jackson 2.x/3.x families while pinning their fixed patch versions.
- Scrub stale Jackson metadata in OpenSAML fat jars so Trivy does not attribute
  removed vulnerable components to the image.
- Fail the image build if required plugins or pinned dependencies are absent.
- Smoke-test authenticated HTTPS with the demo TLS bootstrap enabled.

No chart endpoint, production credential, Kubernetes policy, or live resource is
changed by this commit.

## Validation and promotion

1. CI must build the OpenSearch image, pass authenticated HTTPS smoke, and pass
   blocking Trivy HIGH/CRITICAL checks before publishing.
2. After review and merge, promote only the immutable OpenSearch digest through
   the chart `service-digest/values-opensearch.yaml` overlay.
3. After Argo sync, require the plugin to exist, HTTPS health to pass, Collector
   TLS errors to stop, a current `otel-logs-*` index to exist, and Grafana
   OpenSearch datasource health to return `OK`.

## Rollback

Revert the chart digest to the previous immutable value. This restores the old
image but also restores the known loss of SEC-06 HTTPS/log observability; prefer
fix-forward if CI or runtime validation fails.

<!-- Change trail: @MinhKhoa2209 - 2026-07-23 - Restore OpenSearch SEC-06 HTTPS runtime. -->
