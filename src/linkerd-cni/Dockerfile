# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
#
# Linkerd CNI v1.3.0 writes the ServiceAccount token into the host CNI
# configuration only at startup. Kubernetes rotates bound tokens, so wrap the
# upstream installer and trigger a safe re-render whenever that token changes.
FROM cr.l5d.io/linkerd/cni-plugin:v1.3.0@sha256:e0ea2c672b361d583c69540c18e85b2aed674610907761c4180d38b0cc053caa

COPY src/linkerd-cni/linkerd-cni-token-aware-install.sh /linkerd/linkerd-cni-token-aware-install.sh

RUN chmod 0755 /linkerd/linkerd-cni-token-aware-install.sh

# The installer writes CNI binaries and configuration into hostPath mounts.
# It must therefore run as root, while the DaemonSet remains non-privileged.
USER root

CMD ["linkerd-cni-token-aware-install.sh"]
