# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0


FROM --platform=${BUILDPLATFORM} gradle:8-jdk17@sha256:b7d2b978cad21a07a1192b9112029bc1a80ffe58db7ec828c3f399f833a468cb AS builder

WORKDIR /usr/src/app/

COPY ./src/fraud-detection/ ./
COPY ./pb/ ./src/main/proto/

RUN gradle shadowJar

# -----------------------------------------------------------------------------
# Temurin JRE (not distroless) so apt security upgrades apply for Trivy.

FROM eclipse-temurin:17-jre@sha256:92999aea37688157a53a40bfcb187c30f317422e028045fd5fc5c548fde9e626

ARG OTEL_JAVA_AGENT_VERSION
WORKDIR /usr/src/app/

RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 10001 appgroup \
    && useradd -r -u 10001 -g appgroup appuser

ADD --chmod=644 --chown=appuser:appgroup https://github.com/open-telemetry/opentelemetry-java-instrumentation/releases/download/v$OTEL_JAVA_AGENT_VERSION/opentelemetry-javaagent.jar /usr/src/app/opentelemetry-javaagent.jar
ENV JAVA_TOOL_OPTIONS=-javaagent:/usr/src/app/opentelemetry-javaagent.jar

COPY --from=builder --chown=appuser:appgroup /usr/src/app/build/libs/fraud-detection-1.0-all.jar fraud-detection-1.0-all.jar

USER 10001
ENTRYPOINT [ "java", "-jar", "fraud-detection-1.0-all.jar" ]
# Change trail: @hungxqt - 2026-07-20 - Switch to Temurin 17 JRE with apt upgrade and OTEL agent 2.26.1 for Trivy
