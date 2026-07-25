# Linkerd CNI v1.3.0 writes the ServiceAccount token into the host CNI
# configuration only at startup. Kubernetes rotates bound tokens, so wrap the
# upstream installer and trigger a safe re-render whenever that token changes.
FROM cr.l5d.io/linkerd/cni-plugin:v1.3.0

COPY src/linkerd-cni/linkerd-cni-token-aware-install.sh /linkerd/linkerd-cni-token-aware-install.sh

RUN chmod 0755 /linkerd/linkerd-cni-token-aware-install.sh

CMD ["linkerd-cni-token-aware-install.sh"]
