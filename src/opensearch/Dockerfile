# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

FROM opensearchproject/opensearch:3.3.0@sha256:d96afaf6cbd2a6a3695aeb2f1d48c9a16ad5c8918eb849e5cbf43475f0f8e146

USER 0

# Apply available OS security updates for Trivy HIGH/CRITICAL on the vendor base.
RUN if command -v microdnf >/dev/null 2>&1; then \
      microdnf upgrade -y && microdnf clean all; \
    elif command -v yum >/dev/null 2>&1; then \
      yum upgrade -y && yum clean all; \
    elif command -v dnf >/dev/null 2>&1; then \
      dnf upgrade -y && dnf clean all; \
    fi

# Remove plugins in dependency order - remove dependent plugins first
# These plugins are not needed for basic log storage and retrieval in the demo
# Remove plugins in dependency order
RUN rm -rf \
    /usr/share/opensearch/plugins/opensearch-security-analytics \
    /usr/share/opensearch/plugins/opensearch-alerting \
    /usr/share/opensearch/plugins/opensearch-anomaly-detection \
    /usr/share/opensearch/plugins/opensearch-asynchronous-search \
    /usr/share/opensearch/plugins/opensearch-cross-cluster-replication \
    /usr/share/opensearch/plugins/opensearch-custom-codecs \
    /usr/share/opensearch/plugins/opensearch-flow-framework \
    /usr/share/opensearch/plugins/opensearch-geospatial \
    /usr/share/opensearch/plugins/opensearch-neural-search \
    /usr/share/opensearch/plugins/opensearch-knn \
    /usr/share/opensearch/plugins/opensearch-ltr \
    /usr/share/opensearch/plugins/opensearch-skills \
    /usr/share/opensearch/plugins/opensearch-ml \
    /usr/share/opensearch/plugins/opensearch-notifications \
    /usr/share/opensearch/plugins/opensearch-notifications-core \
    /usr/share/opensearch/plugins/opensearch-observability \
    /usr/share/opensearch/plugins/opensearch-performance-analyzer \
    /usr/share/opensearch/plugins/opensearch-reports-scheduler \
    /usr/share/opensearch/plugins/opensearch-search-relevance \
    /usr/share/opensearch/plugins/opensearch-system-templates \
    /usr/share/opensearch/plugins/opensearch-ubi \
    /usr/share/opensearch/plugins/query-insights

# Keep only these essential plugins:
# - opensearch-security (authentication/authorization) - already disabled via env var
# - opensearch-index-management (index lifecycle management)
# - opensearch-sql (SQL query support for Grafana PPL queries)
# - opensearch-job-scheduler (task scheduling)

USER 1000
# Change trail: @hungxqt - 2026-07-20 - Trivy HIGH/CRITICAL remediation (base upgrades, OS package updates, dep bumps)
