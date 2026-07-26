# Mandate 10 runtime recovery

## Summary

Fix the three runtime failures introduced by the `sha-39aaa22` image remediation and add PR-time container startup tests for the affected services.

## Changes

- Email dependencies and `Gemfile.lock` now agree on the security-fixed `erb`, `zlib`, `net-imap`, and `puma` versions.
- LLM listens on `APP_PORT`; Kubernetes may inject any value into the reserved service-link name `LLM_PORT` without breaking startup.
- OpenSearch keeps Jackson databind module-local, matching the vendor classloader layout and avoiding global/module duplicate classes.
- PR CI loads and starts email, LLM, and OpenSearch images after their Dockerfiles build.

## Local evidence

| Check | Result |
|---|---|
| Email image build and `bundle check` | PASS |
| Email production startup on `0.0.0.0:8080` | PASS |
| LLM startup with `LLM_PORT=tcp://172.20.78.42:8000` and `APP_PORT=8000` | PASS; `/v1/models` HTTP 200 |
| OpenSearch startup | PASS; cluster health green |
| OpenSearch negative log check | PASS; no `jar hell` or `NoClassDefFoundError` |
| Trivy 0.69.3 HIGH/CRITICAL, ignore-unfixed | PASS; zero findings for all three images |

## Rollback

Revert this change and keep the production service-digest overlays on the previous verified digests. Do not promote `sha-39aaa22` again.

<!-- Change trail: @MinhKhoa2209 - 2026-07-22 - Record Mandate 10 runtime recovery evidence. -->
