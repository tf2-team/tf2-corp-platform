# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

# 3.7.0 vendor base ships newer Amazon Linux packages for Trivy HIGH OS CVEs.
FROM opensearchproject/opensearch:3.7.0@sha256:44ba7ea58a319adf61c33ab16873f9ef5dbb30b291a832d375172f0b2d24e3c9

USER 0

# Rotate when rebuilding the secure-delivery baseline so package-manager security
# updates are not silently restored from an older BuildKit cache layer.
ARG SECURITY_UPDATE_EPOCH=2026-07-22-jackson-core-opensaml

# Fixed Jackson pins (Trivy HIGH):
# - com.fasterxml.jackson.core:jackson-core / jackson-databind 2.21.3 → 2.21.4
# - tools.jackson.core:jackson-core / jackson-databind 3.1.3 → 3.1.4
# - opensaml-*-all.jar carries stale Jackson 2.21.3 Maven metadata (no classes)
ARG JACKSON2_VERSION=2.21.4
ARG JACKSON3_VERSION=3.1.4

ADD --chmod=644 https://repo1.maven.org/maven2/com/fasterxml/jackson/core/jackson-core/${JACKSON2_VERSION}/jackson-core-${JACKSON2_VERSION}.jar /tmp/pins/jackson-core-2.jar
ADD --chmod=644 https://repo1.maven.org/maven2/com/fasterxml/jackson/core/jackson-databind/${JACKSON2_VERSION}/jackson-databind-${JACKSON2_VERSION}.jar /tmp/pins/jackson-databind-2.jar
ADD --chmod=644 https://repo1.maven.org/maven2/tools/jackson/core/jackson-core/${JACKSON3_VERSION}/jackson-core-${JACKSON3_VERSION}.jar /tmp/pins/jackson-core-3.jar
ADD --chmod=644 https://repo1.maven.org/maven2/tools/jackson/core/jackson-databind/${JACKSON3_VERSION}/jackson-databind-${JACKSON3_VERSION}.jar /tmp/pins/jackson-databind-3.jar

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

# Pin freestanding Jackson jars + scrub opensaml fat-jar Maven metadata that
# Trivy attributes to GHSA-r7wm-3cxj-wff9 / CVE-2026-54512 / CVE-2026-54513.
# jackson-core lives under lib/; jackson-databind must stay module/plugin-local.
# opensaml-*-all.jar is rewritten with the bundled JDK jar tool (Python zipfile
# rejects its overlapped zip entries).
RUN set -eux; \
    ROOT=/usr/share/opensearch; \
    JACKSON2=2.21.4; \
    JACKSON3=3.1.4; \
    PIN2_CORE=/tmp/pins/jackson-core-2.jar; \
    PIN2_DB=/tmp/pins/jackson-databind-2.jar; \
    PIN3_CORE=/tmp/pins/jackson-core-3.jar; \
    PIN3_DB=/tmp/pins/jackson-databind-3.jar; \
    JAR_BIN="${ROOT}/jdk/bin/jar"; \
    test -x "${JAR_BIN}"; \
    # --- jackson-core in global lib/ ---
    for old in "${ROOT}"/lib/jackson-core-2.*.jar; do \
      test -f "${old}"; \
      rm -f "${old}"; \
    done; \
    cp "${PIN2_CORE}" "${ROOT}/lib/jackson-core-${JACKSON2}.jar"; \
    for old in "${ROOT}"/lib/jackson-core-3.*.jar; do \
      test -f "${old}"; \
      rm -f "${old}"; \
    done; \
    cp "${PIN3_CORE}" "${ROOT}/lib/jackson-core-${JACKSON3}.jar"; \
    # --- jackson-databind module/plugin local only ---
    found_db=0; \
    for old in "${ROOT}"/modules/*/jackson-databind-*.jar "${ROOT}"/plugins/*/jackson-databind-*.jar; do \
      test -f "${old}" || continue; \
      found_db=1; \
      dir=$(dirname "${old}"); \
      base=$(basename "${old}"); \
      rm -f "${old}"; \
      case "${base}" in \
        jackson-databind-3.*) cp "${PIN3_DB}" "${dir}/jackson-databind-${JACKSON3}.jar" ;; \
        *) cp "${PIN2_DB}" "${dir}/jackson-databind-${JACKSON2}.jar" ;; \
      esac; \
    done; \
    test "${found_db}" -eq 1; \
    # Fail if databind ever lands on the global lib classpath.
    if ls "${ROOT}"/lib/jackson-databind-*.jar >/dev/null 2>&1; then \
      echo "jackson-databind must remain module-local" >&2; exit 1; \
    fi; \
    # --- scrub opensaml fat-jar Jackson metadata (no shaded classes present) ---
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
    # --- asserts for Trivy findings ---
    test -f "${ROOT}/lib/jackson-core-${JACKSON2}.jar"; \
    test -f "${ROOT}/lib/jackson-core-${JACKSON3}.jar"; \
    test ! -e "${ROOT}/lib/jackson-core-2.21.3.jar"; \
    test ! -e "${ROOT}/lib/jackson-core-3.1.3.jar"; \
    test ! -e "${ROOT}/modules/ingest-geoip/jackson-databind-2.21.3.jar"; \
    test ! -e "${ROOT}/plugins/opensearch-sql/jackson-databind-2.21.3.jar"; \
    test ! -e "${ROOT}/plugins/opensearch-security/jackson-databind-2.21.3.jar"; \
    test ! -e "${ROOT}/plugins/opensearch-security/jackson-databind-3.1.3.jar"; \
    test -f "${ROOT}/modules/ingest-geoip/jackson-databind-${JACKSON2}.jar"; \
    test -f "${ROOT}/plugins/opensearch-sql/jackson-databind-${JACKSON2}.jar"; \
    test -f "${ROOT}/plugins/opensearch-security/jackson-databind-${JACKSON2}.jar"; \
    test -f "${ROOT}/plugins/opensearch-security/jackson-databind-${JACKSON3}.jar"; \
    rm -rf /tmp/pins; \
    echo "jackson pin + opensaml scrub OK"

# Essential plugins retained after slim:
# - opensearch-security (SEC-06 TLS + basic auth; required for chart HTTPS clients)
# - opensearch-index-management (index lifecycle management)
# - opensearch-sql (SQL/PPL for Grafana)
# - opensearch-job-scheduler (task scheduling for ILM)

USER 1000
# Change trail: @hungxqt - 2026-07-22 - Pin Jackson 2.21.4/3.1.4 and scrub opensaml metadata for Trivy HIGH.
