#!/bin/sh
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
#
# Keep the Linkerd CNI host configuration authenticated as Kubernetes rotates
# the projected ServiceAccount token. The upstream installer only observes CNI
# config-file CREATE/DELETE events, not token changes.
set -eu

service_account_token=/var/run/secrets/kubernetes.io/serviceaccount/token
host_cni_dir="${CONTAINER_MOUNT_PREFIX:-/host}${DEST_CNI_NET_DIR:-/etc/cni/net.d}"
poll_seconds="${LINKERD_CNI_TOKEN_POLL_SECONDS:-30}"

if [ ! -r "${service_account_token}" ]; then
  echo "Linkerd CNI ServiceAccount token is not readable: ${service_account_token}" >&2
  exit 1
fi

# The upstream script owns installing binaries, rendering the initial config,
# and reacting to CNI config CREATE/DELETE events. Keep it as the owner of
# those operations; this wrapper only creates the event needed after rotation.
install-cni.sh &
installer_pid=$!

cleanup() {
  kill -TERM "${installer_pid}" 2>/dev/null || true
  wait "${installer_pid}" 2>/dev/null || true
}
trap cleanup INT TERM

previous_token_hash="$(sha256sum "${service_account_token}" | awk '{print $1}')"

while kill -0 "${installer_pid}" 2>/dev/null; do
  sleep "${poll_seconds}"

  current_token_hash="$(sha256sum "${service_account_token}" | awk '{print $1}')"
  if [ "${current_token_hash}" = "${previous_token_hash}" ]; then
    continue
  fi

  # Change only the Linkerd CNI entry, using an atomic replacement. The
  # upstream inotify watcher then re-renders both the chained CNI config and
  # its kubeconfig with the newly projected token. Do not rewrite AWS CNI or
  # any other chained plugin configuration.
  cni_config=""
  for candidate in "${host_cni_dir}"/*.conflist; do
    [ -f "${candidate}" ] || continue
    if jq -e 'any(.plugins[]?; .type == "linkerd-cni")' "${candidate}" >/dev/null; then
      cni_config="${candidate}"
      break
    fi
  done
  if [ -z "${cni_config}" ]; then
    echo "Linkerd CNI token rotated but no chained CNI config exists yet; waiting" >&2
    previous_token_hash="${current_token_hash}"
    continue
  fi

  token="$(cat "${service_account_token}")"
  temporary_config="$(mktemp "${host_cni_dir}/.linkerd-cni-token.XXXXXX")"
  if jq --arg token "${token}" '
      (.plugins[] | select(.type == "linkerd-cni").policy.k8s_auth_token) = $token
    ' "${cni_config}" >"${temporary_config}"; then
    chmod --reference="${cni_config}" "${temporary_config}"
    mv "${temporary_config}" "${cni_config}"
    echo "Refreshed Linkerd CNI API token after projected ServiceAccount token rotation"
    previous_token_hash="${current_token_hash}"
  else
    rm -f "${temporary_config}"
    echo "Unable to refresh Linkerd CNI token; retaining existing CNI configuration" >&2
  fi
done

wait "${installer_pid}"
