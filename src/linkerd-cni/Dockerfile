# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
#
# Linkerd CNI's published v1.7.0-alpha.1 artifact was built with Go 1.26.4,
# which contains fixed HIGH CVE-2026-39822. Rebuild only the two Go binaries
# from Linkerd's signed source tag with Go 1.26.5, retaining the upstream
# runtime image and its repair controller unchanged.
FROM --platform=$BUILDPLATFORM golang:1.26.5-alpine@sha256:0178a641fbb4858c5f1b48e34bdaabe0350a330a1b1149aabd498d0699ff5fb2 AS cni-go-builder

ARG TARGETARCH
ARG LINKERD_CNI_SOURCE_REV=5709c111e349ec578ba0c8cb033ccdfebe936ee9

RUN apk add --no-cache git

WORKDIR /build

# Fetch one immutable commit from Linkerd's cni-plugin/v1.7.0-alpha.1 tag.
# Checking out the SHA (not the mutable tag) makes the custom rebuild auditable.
RUN git init . \
    && git remote add origin https://github.com/linkerd/linkerd2-proxy-init.git \
    && git fetch --depth 1 origin "${LINKERD_CNI_SOURCE_REV}" \
    && git checkout --detach "${LINKERD_CNI_SOURCE_REV}" \
    && test "$(git rev-parse HEAD)" = "${LINKERD_CNI_SOURCE_REV}"

RUN --mount=type=cache,target=/go/pkg/mod go mod download

RUN CGO_ENABLED=0 GOOS=linux GOARCH="${TARGETARCH}" GO111MODULE=on \
    go build -o /out/linkerd-cni -mod=readonly -ldflags "-s -w" -v ./cni-plugin/ \
    && CGO_ENABLED=0 GOOS=linux GOARCH="${TARGETARCH}" GO111MODULE=on \
    go build -o /out/linkerd2-cni-install -mod=readonly -ldflags "-s -w" -v ./cni-install/

# Linkerd CNI v1.7.0-alpha.1 writes the ServiceAccount token into the host CNI
# configuration only at startup. Kubernetes rotates bound tokens, so wrap the
# upstream installer and trigger a safe re-render whenever that token changes.
FROM cr.l5d.io/linkerd/cni-plugin:v1.7.0-alpha.1@sha256:44a882ca2f3ffa2a11a5c4bef306a9af5edfb317afa7e15163a06cd6fb77d308

COPY --from=cni-go-builder /out/linkerd-cni /opt/cni/bin/linkerd-cni
COPY --from=cni-go-builder /out/linkerd2-cni-install /usr/bin/linkerd2-cni-install

COPY src/linkerd-cni/linkerd-cni-token-aware-install.sh /linkerd/linkerd-cni-token-aware-install.sh

RUN chmod 0755 /linkerd/linkerd-cni-token-aware-install.sh

# The installer writes CNI binaries and configuration into hostPath mounts.
# It must therefore run as root, while the DaemonSet remains non-privileged.
# nosemgrep: dockerfile.security.last-user-is-root.last-user-is-root -- CNI hostPath writes require UID 0.
USER root

CMD ["linkerd-cni-token-aware-install.sh"]
