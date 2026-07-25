# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
#
# Linkerd CNI v1.6.8 writes the ServiceAccount token into the host CNI
# configuration only at startup. Kubernetes rotates bound tokens, so wrap the
# upstream installer and trigger a safe re-render whenever that token changes.
FROM cr.l5d.io/linkerd/cni-plugin:v1.6.8@sha256:87a04dccc4e94f66a6f6e625b227b65d1261efadee7c6df6f26116a055cfe280

COPY src/linkerd-cni/linkerd-cni-token-aware-install.sh /linkerd/linkerd-cni-token-aware-install.sh

RUN chmod 0755 /linkerd/linkerd-cni-token-aware-install.sh

# The installer writes CNI binaries and configuration into hostPath mounts.
# It must therefore run as root, while the DaemonSet remains non-privileged.
# nosemgrep: dockerfile.security.last-user-is-root.last-user-is-root -- CNI hostPath writes require UID 0.
USER root

CMD ["linkerd-cni-token-aware-install.sh"]
