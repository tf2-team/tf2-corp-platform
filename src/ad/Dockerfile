# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0


FROM --platform=${BUILDPLATFORM} eclipse-temurin:21-jdk@sha256:da9d3a4f7650db39b918fc5a2c3da76556fb8cc8e5f3767cdea0bb409286951a AS builder
ARG _JAVA_OPTIONS
WORKDIR /usr/src/app/

COPY ./src/ad/gradlew* ./src/ad/settings.gradle* ./src/ad/build.gradle ./
COPY ./src/ad/gradle ./gradle

RUN chmod +x ./gradlew
RUN ./gradlew
RUN ./gradlew downloadRepos

COPY ./src/ad/ ./
COPY ./pb/ ./proto
RUN chmod +x ./gradlew
RUN ./gradlew installDist -PprotoSourceDir=./proto

# -----------------------------------------------------------------------------

FROM eclipse-temurin:21-jre@sha256:273396ed5998598ed1091e8d72711c2d36980a0e65103859c55a4e977a41ffd3

ARG OTEL_JAVA_AGENT_VERSION
ARG _JAVA_OPTIONS

# Apply OS security updates for Trivy HIGH/CRITICAL on the JRE base.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    # Temurin image ships /usr/bin/pebble (Go) with HIGH x/net and stdlib CVEs; not used by this service.
    && rm -f /usr/bin/pebble

WORKDIR /usr/src/app/

RUN groupadd -g 10001 appgroup && \
    useradd -r -u 10001 -g appgroup appuser

COPY --from=builder --chown=appuser:appgroup \
    /usr/src/app/build/install/techx-corp-ad/ \
    /usr/src/app/build/install/techx-corp-ad/
ADD --chmod=644 --chown=appuser:appgroup https://github.com/open-telemetry/opentelemetry-java-instrumentation/releases/download/v$OTEL_JAVA_AGENT_VERSION/opentelemetry-javaagent.jar /usr/src/app/opentelemetry-javaagent.jar
ENV JAVA_TOOL_OPTIONS=-javaagent:/usr/src/app/opentelemetry-javaagent.jar

RUN chown -R appuser:appgroup /usr/src/app

USER 10001

EXPOSE ${AD_PORT}
ENTRYPOINT [ "./build/install/techx-corp-ad/bin/Ad" ]
# Change trail: @hungxqt - 2026-07-20 - Remove pebble gobinary; Netty/jackson fixes via build.gradle
