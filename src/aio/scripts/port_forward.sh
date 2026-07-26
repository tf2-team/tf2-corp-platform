#!/bin/sh
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
set -eu

namespace="${AIOPS_SMOKE_NAMESPACE:-techx-corp-prod}"
startup_timeout_seconds="${STARTUP_TIMEOUT_SECONDS:-20}"
proxy_port=8001
pids=""
forwards='prometheus 9090 9090 http
jaeger 16686 16686 http
opensearch 9200 9200 https
grafana 3000 80 http'

has_port() {
  python3 - "$1" <<'PY' >/dev/null 2>&1
import socket
import sys

with socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=1):
    pass
PY
}

cleanup() {
  if [ -n "$pids" ]; then
    # shellcheck disable=SC2086
    kill $pids >/dev/null 2>&1 || true
    # shellcheck disable=SC2086
    wait $pids >/dev/null 2>&1 || true
  fi
}

die() {
  echo "error: $*" >&2
  exit 1
}

trap cleanup EXIT INT TERM

command -v kubectl >/dev/null 2>&1 || die "kubectl is not installed or is not available on PATH"
command -v python3 >/dev/null 2>&1 || die "python3 is not installed or is not available on PATH"

context="$(kubectl config current-context 2>/dev/null || true)"
[ -n "$context" ] || die "kubectl current-context is not set. Run: kubectl config use-context <context>"

printf 'AIOps live port-forward\n'
printf 'Context: %s\n' "$context"
printf 'Namespace: %s\n' "$namespace"

kubectl get namespace "$namespace" -o name >/dev/null

printf '%s\n' "$forwards" | while read -r name _ _ _; do
  kubectl -n "$namespace" get service "$name" -o name >/dev/null
done

printf '%s\n' "$forwards" | while read -r _ local_port _ _; do
  if has_port "$local_port"; then
    die "Local port $local_port is already in use. Stop the old forward or choose a free port."
  fi
done
has_port "$proxy_port" && die "Local port $proxy_port is already in use. Stop the old forward or choose a free port."

while IFS=' ' read -r name local_port remote_port _; do
  kubectl -n "$namespace" port-forward "service/$name" "$local_port:$remote_port" &
  pids="${pids} $!"
done <<EOF
$forwards
EOF

kubectl proxy "--port=$proxy_port" &
pids="${pids} $!"

deadline=$(( $(date +%s) + startup_timeout_seconds ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  ready=0
  total=1
  while IFS=' ' read -r _ local_port _ _; do
    total=$((total + 1))
    if has_port "$local_port"; then
      ready=$((ready + 1))
    fi
  done <<EOF
$forwards
EOF
  if has_port "$proxy_port"; then
    ready=$((ready + 1))
  fi
  [ "$ready" -eq "$total" ] && break

  for pid in $pids; do
    kill -0 "$pid" >/dev/null 2>&1 || die "A port-forward stopped during startup."
  done
  sleep 1
done

missing=""
while IFS=' ' read -r _ local_port _ _; do
  has_port "$local_port" || missing="${missing} ${local_port}"
done <<EOF
$forwards
EOF
has_port "$proxy_port" || missing="${missing} ${proxy_port}"
[ -z "$missing" ] || die "Timed out waiting for local port(s):$missing"

printf '\nEndpoints ready:\n'
while IFS=' ' read -r name local_port _ scheme; do
  printf '  %-12s %s://localhost:%s\n' "$name" "$scheme" "$local_port"
done <<EOF
$forwards
EOF
printf '  %-12s http://localhost:%s\n' "kubernetes" "$proxy_port"
printf '  aiops       http://localhost:8000 (start separately for Grafana inbound test)\n'

printf '\nCredential requirements:\n'
printf '  Prometheus, Jaeger, Kubernetes proxy, Grafana health: no service credential\n'
printf '  OpenSearch: Basic Auth username/password is required\n'
printf '  Grafana inbound webhook: shared secret must match the AIOps process\n'
printf '  Notification: external webhook URL; it cannot be port-forwarded\n'
printf '\nPress Ctrl+C to stop only the processes created by this script.\n'

while true; do
  for pid in $pids; do
    kill -0 "$pid" >/dev/null 2>&1 || die "A port-forward stopped unexpectedly."
  done
  sleep 5
done
