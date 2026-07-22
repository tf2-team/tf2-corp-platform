# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

# 3.7.0 vendor base ships newer Amazon Linux packages for Trivy HIGH OS CVEs.
FROM opensearchproject/opensearch:3.7.0@sha256:44ba7ea58a319adf61c33ab16873f9ef5dbb30b291a832d375172f0b2d24e3c9

USER 0

# Rotate when rebuilding the secure-delivery baseline so package-manager security
# updates are not silently restored from an older BuildKit cache layer.
ARG SECURITY_UPDATE_EPOCH=2026-07-22-jackson-core-ghsa-r7wm

# Trivy HIGH GHSA-r7wm-3cxj-wff9: jackson-core async maxNumberLength bypass (incomplete prior fix).
# Vendor 3.7.0 ships jackson-core 2.21.3 + tools.jackson.core 3.1.3; pin fixed floors in-tree.
ADD --chmod=644 https://repo1.maven.org/maven2/com/fasterxml/jackson/core/jackson-core/2.21.4/jackson-core-2.21.4.jar /tmp/jackson-core-2.21.4.jar
ADD --chmod=644 https://repo1.maven.org/maven2/tools/jackson/core/jackson-core/3.1.4/jackson-core-3.1.4.jar /tmp/jackson-core-3.1.4.jar
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

# Remove plugins in dependency order - remove dependent plugins first
# These plugins are not needed for basic log storage and retrieval in the demo
# Remove plugins in dependency order
RUN rm -rf \
    /usr/share/opensearch/plugins/opensearch-security \
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

# Replace vulnerable jackson-core (2.21.3 / 3.1.3) wherever OpenSearch ships them (lib, modules, plugins).
RUN set -eu \
    && found2=0 \
    && found3=0 \
    && for jar in \
         /usr/share/opensearch/lib/jackson-core-*.jar \
         /usr/share/opensearch/modules/*/jackson-core-*.jar \
         /usr/share/opensearch/plugins/*/jackson-core-*.jar; do \
         [ -e "${jar}" ] || continue; \
         dir=$(dirname "${jar}"); \
         base=$(basename "${jar}"); \
         case "${base}" in \
           jackson-core-2.*) \
             rm -f "${jar}"; \
             cp /tmp/jackson-core-2.21.4.jar "${dir}/jackson-core-2.21.4.jar"; \
             found2=1 ;; \
           jackson-core-3.*) \
             rm -f "${jar}"; \
             cp /tmp/jackson-core-3.1.4.jar "${dir}/jackson-core-3.1.4.jar"; \
             found3=1 ;; \
           *) \
             echo "Unexpected jackson-core jar: ${jar}" >&2; \
             exit 1 ;; \
         esac; \
       done \
    && test "${found2}" -eq 1 \
    && test "${found3}" -eq 1 \
    && test -z "$(find /usr/share/opensearch \( -name 'jackson-core-2.21.3.jar' -o -name 'jackson-core-3.1.3.jar' \) -print -quit)" \
    && test -n "$(find /usr/share/opensearch -name 'jackson-core-2.21.4.jar' -print -quit)" \
    && test -n "$(find /usr/share/opensearch -name 'jackson-core-3.1.4.jar' -print -quit)" \
    && rm -f /tmp/jackson-core-*.jar

RUN rm -f /usr/share/opensearch/lib/jackson-databind-*.jar \
    /usr/share/opensearch/modules/ingest-geoip/jackson-databind-*.jar \
    /usr/share/opensearch/plugins/opensearch-sql/jackson-databind-*.jar \
    && cp /tmp/jackson-databind-2.21.4.jar /usr/share/opensearch/modules/ingest-geoip/ \
    && cp /tmp/jackson-databind-2.21.4.jar /usr/share/opensearch/plugins/opensearch-sql/ \
    && rm -f /tmp/jackson-databind-*.jar \
    && for jar in /usr/share/opensearch/lib/jackson-databind-*.jar; do \
         test ! -e "${jar}" || { echo "Jackson databind must remain module-local: ${jar}" >&2; exit 1; }; \
       done \
    && set -- /usr/share/opensearch/modules/*/jackson-databind-*.jar /usr/share/opensearch/plugins/*/jackson-databind-*.jar \
    && test "$#" -eq 2 \
    && test -f /usr/share/opensearch/modules/ingest-geoip/jackson-databind-2.21.4.jar \
    && test -f /usr/share/opensearch/plugins/opensearch-sql/jackson-databind-2.21.4.jar

# Keep only these essential plugins:
# - opensearch-index-management (index lifecycle management)
# - opensearch-sql (SQL query support for Grafana PPL queries)
# - opensearch-job-scheduler (task scheduling)

USER 1000
# Change trail: @hungxqt - 2026-07-22 - Pin jackson-core 2.21.4 and 3.1.4 for GHSA-r7wm-3cxj-wff9
