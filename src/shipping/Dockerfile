# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0



FROM --platform=${BUILDPLATFORM} docker.io/library/rust:1.91@sha256:867f1d1162913c401378a8504fb17fe2032c760dc316448766f150a130204aad AS builder
ARG TARGETARCH
ARG TARGETPLATFORM
ARG BUILDPLATFORM

RUN echo Building on ${BUILDPLATFORM} for ${TARGETPLATFORM}

# Install dependencies - cross-compilation setup for ARM64, native otherwise
RUN apt-get update && \
    if [ "${TARGETPLATFORM}" = "linux/arm64" ] && [ "${BUILDPLATFORM}" != "linux/arm64" ] ; then \
        apt-get install --no-install-recommends -y g++-aarch64-linux-gnu libc6-dev-arm64-cross libprotobuf-dev protobuf-compiler ca-certificates && \
        rustup target add aarch64-unknown-linux-gnu; \
    else \
        apt-get install --no-install-recommends -y g++ libc6-dev libprotobuf-dev protobuf-compiler ca-certificates; \
    fi

WORKDIR /app/

COPY /src/shipping/ /app/

# Build - cross-compile for ARM64 or native build
RUN if [ "${TARGETPLATFORM}" = "linux/arm64" ] && [ "${BUILDPLATFORM}" != "linux/arm64" ] ; then \
        env CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER=aarch64-linux-gnu-gcc \
            CC_aarch64_unknown_linux_gnu=aarch64-linux-gnu-gcc \
            CXX_aarch64_unknown_linux_gnu=aarch64-linux-gnu-g++ \
        cargo build -r --target aarch64-unknown-linux-gnu && \
        cp /app/target/aarch64-unknown-linux-gnu/release/shipping /app/target/release/shipping; \
    else \
        cargo build -r; \
    fi


FROM gcr.io/distroless/cc-debian13:nonroot@sha256:d97bc0a941b8d4be647dc0ee75b264ddbb772f1ac5ba690a4309c00723b23775

WORKDIR /app

COPY --from=builder /app/target/release/shipping shipping

EXPOSE ${SHIPPING_PORT}

# Numeric UID required: kubelet cannot verify runAsNonRoot when USER is a name (e.g. nonroot).
# 65532 is the distroless :nonroot user.
USER 65532
CMD ["./shipping"]
# Change trail: @hungxqt - 2026-07-21 - Use numeric UID 65532 so Kubernetes runAsNonRoot can verify non-root
