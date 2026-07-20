# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

FROM envoyproxy/envoy:v1.34-latest@sha256:cfc0678bc03cca19cbb031688acb31d510bff501ff97e163026a375fe0515d69

RUN apt-get update && \
    apt-get install --no-install-recommends -y gettext-base && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

USER envoy

WORKDIR /home/envoy

COPY ./src/frontend-proxy/envoy.tmpl.yaml envoy.tmpl.yaml

EXPOSE ${ENVOY_PORT}
EXPOSE ${ENVOY_ADMIN_PORT}
ENTRYPOINT ["/bin/sh", "-c", "envsubst < envoy.tmpl.yaml > /tmp/envoy.yaml && exec envoy -c /tmp/envoy.yaml"]
