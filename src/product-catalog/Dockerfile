# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0


FROM golang:1.25-bookworm@sha256:ea341baa9bd5ba6784f6d7161ace70544349a6242d54d34a0fbfd2c4d51c9d58 AS builder

WORKDIR /usr/src/app/

COPY ./src/product-catalog/go.mod go.mod
COPY ./src/product-catalog/go.sum go.sum

RUN go mod download

COPY ./src/product-catalog/genproto/oteldemo/ genproto/oteldemo/
COPY ./src/product-catalog/main.go main.go

RUN CGO_ENABLED=0 GOOS=linux GO111MODULE=on go build -ldflags "-s -w" -o product-catalog main.go

FROM gcr.io/distroless/static-debian12:nonroot@sha256:aef9602f8710ec12bde19d593fed1f76c708531bb7aba205110f1029786ead7b

WORKDIR /usr/src/app/

COPY --from=builder /usr/src/app/product-catalog/ ./

EXPOSE ${PRODUCT_CATALOG_PORT}
# Numeric UID required: kubelet cannot verify runAsNonRoot when USER is a name (e.g. nonroot).
USER 65532
ENTRYPOINT [ "./product-catalog" ]
# Change trail: @hungxqt - 2026-07-21 - Use numeric UID 65532 so Kubernetes runAsNonRoot can verify non-root
