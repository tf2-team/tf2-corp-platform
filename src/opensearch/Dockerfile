# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

# 3.7.0 vendor base ships newer Amazon Linux packages for Trivy HIGH OS CVEs.
FROM opensearchproject/opensearch:3.7.0@sha256:44ba7ea58a319adf61c33ab16873f9ef5dbb30b291a832d375172f0b2d24e3c9

USER 0

# Rotate when rebuilding the secure-delivery baseline so package-manager security
# updates are not silently restored from an older BuildKit cache layer.
ARG SECURITY_UPDATE_EPOCH=2026-07-21-cve-refresh-2

ADD --chmod=644 https://repo1.maven.org/maven2/com/fasterxml/jackson/core/jackson-databind/2.21.4/jackson-databind-2.21.4.jar /tmp/jackson-databind-2.21.4.jar

# Apply available OS security updates for Trivy HIGH/CRITICAL on the vendor base.
RUN echo "security update baseline: ${SECURITY_UPDATE_EPOCH}" >/dev/null \
    && if command -v microdnf >/dev/null 2>&1; then \
      microdnf clean all \
      && microdnf --releasever=latest makecache \
      && microdnf --releasever=latest upgrade -y glib2 libacl python3 python3-libs \
      && microdnf clean all; \
    elif command -v yum >/dev/null 2>&1; then \
      yum clean all \
      && yum --releasever=latest makecache \
      && yum --releasever=latest upgrade -y glib2 libacl python3 python3-libs \
      && yum clean all; \
    elif command -v dnf >/dev/null 2>&1; then \
      dnf clean all \
      && dnf --releasever=latest makecache \
      && dnf --releasever=latest upgrade -y glib2 libacl python3 python3-libs \
      && dnf clean all; \
    else \
      echo "No supported package manager found" >&2; \
      exit 1; \
    fi \
    && rpm -q glib2-2.82.2-770.amzn2023 \
    && rpm -q libacl-2.4.0-1.amzn2023.0.1 \
    && rpm -q python3-3.9.25-1.amzn2023.0.8 \
    && rpm -q python3-libs-3.9.25-1.amzn2023.0.8

# Strip unused plugins to shrink the image. KEEP opensearch-security:
# chart SEC-06 expects the security plugin + demo TLS so OTel/Grafana can use
# https://opensearch:9200 with basic auth. Removing the plugin left the node on
# plain HTTP and broke the log pipeline (TLS handshake failures / empty Grafana logs).
# Remove dependent / optional plugins first; leave security, SQL, ILM, job-scheduler.
RUN test -d /usr/share/opensearch/plugins/opensearch-security \
    && rm -rf \
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
    /usr/share/opensearch/plugins/query-insights \
    && test -d /usr/share/opensearch/plugins/opensearch-security \
    && test -d /usr/share/opensearch/plugins/opensearch-sql \
    && test -d /usr/share/opensearch/plugins/opensearch-index-management \
    && test -d /usr/share/opensearch/plugins/opensearch-job-scheduler

# Pin jackson-databind in every module/plugin that ships a copy (CVE baseline).
# Never place it in the global lib/ (OpenSearch classpath rules).
# After keeping opensearch-security, replace any security-plugin copy as well.
RUN rm -f /usr/share/opensearch/lib/jackson-databind-*.jar \
    && for jar in /usr/share/opensearch/modules/*/jackson-databind-*.jar \
                  /usr/share/opensearch/plugins/*/jackson-databind-*.jar; do \
         if [ -f "${jar}" ]; then \
           dir="$(dirname "${jar}")"; \
           rm -f "${dir}"/jackson-databind-*.jar; \
           cp /tmp/jackson-databind-2.21.4.jar "${dir}/jackson-databind-2.21.4.jar"; \
         fi; \
       done \
    && rm -f /tmp/jackson-databind-*.jar \
    && for jar in /usr/share/opensearch/lib/jackson-databind-*.jar; do \
         test ! -e "${jar}" || { echo "Jackson databind must remain module-local: ${jar}" >&2; exit 1; }; \
       done \
    && test -f /usr/share/opensearch/modules/ingest-geoip/jackson-databind-2.21.4.jar \
    && test -f /usr/share/opensearch/plugins/opensearch-sql/jackson-databind-2.21.4.jar

# Essential plugins retained after slim:
# - opensearch-security (SEC-06 TLS + basic auth; required for chart HTTPS clients)
# - opensearch-index-management (index lifecycle management)
# - opensearch-sql (SQL/PPL for Grafana)
# - opensearch-job-scheduler (task scheduling for ILM)

USER 1000
# Change trail: @hungxqt - 2026-07-22 - Keep opensearch-security for SEC-06 HTTPS log pipeline.
