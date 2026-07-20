# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

FROM envoyproxy/envoy:v1.35-latest@sha256:a707c3821b4cecb5db43d8e86e983e0f57b81010fefbabc01feeb071fb8cc08e

RUN apt-get update && \
    apt-get upgrade -y --no-install-recommends && \
    apt-get install --no-install-recommends -y gettext-base && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

USER envoy

WORKDIR /home/envoy

COPY ./src/frontend-proxy/envoy.tmpl.yaml envoy.tmpl.yaml

EXPOSE ${ENVOY_PORT}
EXPOSE ${ENVOY_ADMIN_PORT}
ENTRYPOINT ["/bin/sh", "-c", "envsubst < envoy.tmpl.yaml > /tmp/envoy.yaml && exec envoy -c /tmp/envoy.yaml"]
# Change trail: @hungxqt - 2026-07-20 - Trivy HIGH/CRITICAL remediation (base upgrades, OS package updates, dep bumps)
