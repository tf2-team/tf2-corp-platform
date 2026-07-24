# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

# 3.7.0 vendor base ships newer Amazon Linux packages for Trivy HIGH OS CVEs.
FROM opensearchproject/opensearch:3.7.0@sha256:44ba7ea58a319adf61c33ab16873f9ef5dbb30b291a832d375172f0b2d24e3c9

USER 0

# Rotate when rebuilding the secure-delivery baseline so package-manager security
# updates are not silently restored from an older BuildKit cache layer.
ARG SECURITY_UPDATE_EPOCH=2026-07-23-sec06-security-plugin

# Trivy HIGH GHSA-r7wm-3cxj-wff9: jackson-core async maxNumberLength bypass (incomplete prior fix).
# Vendor 3.7.0 ships jackson-core 2.21.3 + tools.jackson.core 3.1.3; pin fixed floors in-tree.
ADD --chmod=644 https://repo1.maven.org/maven2/com/fasterxml/jackson/core/jackson-core/2.21.4/jackson-core-2.21.4.jar /tmp/jackson-core-2.21.4.jar
ADD --chmod=644 https://repo1.maven.org/maven2/tools/jackson/core/jackson-core/3.1.4/jackson-core-3.1.4.jar /tmp/jackson-core-3.1.4.jar
ADD --chmod=644 https://repo1.maven.org/maven2/com/fasterxml/jackson/core/jackson-databind/2.21.4/jackson-databind-2.21.4.jar /tmp/jackson-databind-2.21.4.jar
ADD --chmod=644 https://repo1.maven.org/maven2/tools/jackson/core/jackson-databind/3.1.4/jackson-databind-3.1.4.jar /tmp/jackson-databind-3.1.4.jar

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

# Strip optional plugins while retaining the SEC-06 security plugin. Production
# Grafana and OTel clients require its HTTPS and basic-auth endpoints.
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

# Replace vulnerable jackson-core in global lib (vendor ships both 2.21.3 and 3.1.3 there only).
# Image has no findutils; keep this step as plain shell globs + fixed paths (same style as databind).
RUN ls -la /usr/share/opensearch/lib/jackson-core-*.jar \
    && rm -f /usr/share/opensearch/lib/jackson-core-*.jar \
    && cp /tmp/jackson-core-2.21.4.jar /usr/share/opensearch/lib/jackson-core-2.21.4.jar \
    && cp /tmp/jackson-core-3.1.4.jar /usr/share/opensearch/lib/jackson-core-3.1.4.jar \
    && rm -f /tmp/jackson-core-*.jar \
    && test -f /usr/share/opensearch/lib/jackson-core-2.21.4.jar \
    && test -f /usr/share/opensearch/lib/jackson-core-3.1.4.jar \
    && test ! -e /usr/share/opensearch/lib/jackson-core-2.21.3.jar \
    && test ! -e /usr/share/opensearch/lib/jackson-core-3.1.3.jar \
    && ls -la /usr/share/opensearch/lib/jackson-core-*.jar

# Keep Jackson databind module/plugin-local and preserve its 2.x versus 3.x
# family. Scrub stale Jackson Maven/service metadata from the OpenSAML fat jars;
# replacing every copy with 2.x caused the previous security-plugin image to
# fail at startup with ClassNotFoundException.
RUN set -eux; \
    ROOT=/usr/share/opensearch; \
    JAR_BIN="${ROOT}/jdk/bin/jar"; \
    test -x "${JAR_BIN}"; \
    rm -f "${ROOT}"/lib/jackson-databind-*.jar; \
    found_db=0; \
    for old in "${ROOT}"/modules/*/jackson-databind-*.jar "${ROOT}"/plugins/*/jackson-databind-*.jar; do \
      test -f "${old}" || continue; \
      found_db=1; \
      dir=$(dirname "${old}"); \
      base=$(basename "${old}"); \
      rm -f "${old}"; \
      case "${base}" in \
        jackson-databind-3.*) cp /tmp/jackson-databind-3.1.4.jar "${dir}/jackson-databind-3.1.4.jar" ;; \
        *) cp /tmp/jackson-databind-2.21.4.jar "${dir}/jackson-databind-2.21.4.jar" ;; \
      esac; \
    done; \
    test "${found_db}" -eq 1; \
    if ls "${ROOT}"/lib/jackson-databind-*.jar >/dev/null 2>&1; then \
      echo "jackson-databind must remain module-local" >&2; exit 1; \
    fi; \
    found_osaml=0; \
    for osaml in "${ROOT}"/plugins/*/opensaml-*-all.jar; do \
      test -f "${osaml}" || continue; \
      found_osaml=1; \
      work=$(mktemp -d); \
      ( cd "${work}" && "${JAR_BIN}" xf "${osaml}" ); \
      rm -rf \
        "${work}/META-INF/maven/com.fasterxml.jackson.core" \
        "${work}/META-INF/maven/com.fasterxml.jackson.datatype"; \
      rm -f \
        "${work}/META-INF/services/com.fasterxml.jackson.core.JsonFactory" \
        "${work}/META-INF/services/com.fasterxml.jackson.databind.Module" \
        "${work}/META-INF/services/com.fasterxml.jackson.core.ObjectCodec"; \
      if [ -f "${work}/META-INF/MANIFEST.MF" ]; then \
        ( cd "${work}" && "${JAR_BIN}" cfm "${osaml}.new" META-INF/MANIFEST.MF . ); \
      else \
        ( cd "${work}" && "${JAR_BIN}" cf "${osaml}.new" . ); \
      fi; \
      mv -f "${osaml}.new" "${osaml}"; \
      rm -rf "${work}"; \
      if "${JAR_BIN}" tf "${osaml}" | grep -E 'META-INF/maven/com\.fasterxml\.jackson|META-INF/services/com\.fasterxml\.jackson' >/dev/null; then \
        echo "opensaml still contains jackson metadata: ${osaml}" >&2; exit 1; \
      fi; \
    done; \
    test "${found_osaml}" -eq 1; \
    test -f "${ROOT}/modules/ingest-geoip/jackson-databind-2.21.4.jar"; \
    test -f "${ROOT}/plugins/opensearch-sql/jackson-databind-2.21.4.jar"; \
    test -f "${ROOT}/plugins/opensearch-security/jackson-databind-2.21.4.jar"; \
    test -f "${ROOT}/plugins/opensearch-security/jackson-databind-3.1.4.jar"; \
    rm -f /tmp/jackson-databind-*.jar

# Keep only these essential plugins:
# - opensearch-security (SEC-06 HTTPS and basic auth)
# - opensearch-index-management (index lifecycle management)
# - opensearch-sql (SQL query support for Grafana PPL queries)
# - opensearch-job-scheduler (task scheduling)

USER 1000
# Change trail: @MinhKhoa2209 - 2026-07-23 - Restore SEC-06 security plugin with Jackson 2/3-safe pins.
