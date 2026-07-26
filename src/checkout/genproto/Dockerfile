# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

FROM golang:1.25-alpine@sha256:56961d79ea8129efddcc0b8643fd8a5416b4e6228cfd477e3fd61deb2672c587

WORKDIR /build

RUN apk add --no-cache protobuf-dev

COPY ./src/checkout/go.mod go.mod
COPY ./src/checkout/go.sum go.sum

RUN go install tool
USER nobody
# Change trail: @hungxqt - 2026-07-20 - Trivy HIGH/CRITICAL remediation (base upgrades, OS package updates, dep bumps)
