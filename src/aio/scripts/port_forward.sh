#!/usr/bin/env bash
set -euo pipefail

namespace="${AIOPS_SMOKE_NAMESPACE:-techx-corp-prod}"
startup_timeout_seconds="${STARTUP_TIMEOUT_SECONDS:-20}"
proxy_port=8001
pids=()

forwards=(
  "prometheus 9090 9090 http"
  "jaeger 16686 16686 http"
  "opensearch 9200 9200 https"
  "grafana 3000 80 http"
)

has_port() {
  timeout 1 bash -c "</dev/tcp/127.0.0.1/$1" >/dev/null 2>&1
}

cleanup() {
  if ((${#pids[@]})); then
    kill "${pids[@]}" >/dev/null 2>&1 || true
    wait "${pids[@]}" >/dev/null 2>&1 || true
  fi
}

die() {
  echo "error: $*" >&2
  exit 1
}

trap cleanup EXIT INT TERM

command -v kubectl >/dev/null 2>&1 || die "kubectl is not installed or is not available on PATH"

context="$(kubectl config current-context 2>/dev/null || true)"
[[ -n "$context" ]] || die "kubectl current-context is not set. Run: kubectl config use-context <context>"

printf 'AIOps live port-forward\n'
printf 'Context: %s\n' "$context"
printf 'Namespace: %s\n' "$namespace"

kubectl get namespace "$namespace" -o name >/dev/null

for forward in "${forwards[@]}"; do
  read -r name _ _ _ <<<"$forward"
  kubectl -n "$namespace" get service "$name" -o name >/dev/null
done

for forward in "${forwards[@]}"; do
  read -r _ local_port _ _ <<<"$forward"
  has_port "$local_port" && die "Local port $local_port is already in use. Stop the old forward or choose a free port."
done
has_port "$proxy_port" && die "Local port $proxy_port is already in use. Stop the old forward or choose a free port."

for forward in "${forwards[@]}"; do
  read -r name local_port remote_port _ <<<"$forward"
  kubectl -n "$namespace" port-forward "service/$name" "$local_port:$remote_port" &
  pids+=("$!")
done

kubectl proxy "--port=$proxy_port" &
pids+=("$!")

required_ports=()
for forward in "${forwards[@]}"; do
  read -r _ local_port _ _ <<<"$forward"
  required_ports+=("$local_port")
done
required_ports+=("$proxy_port")

deadline=$((SECONDS + startup_timeout_seconds))
while ((SECONDS < deadline)); do
  ready=0
  for port in "${required_ports[@]}"; do
    has_port "$port" && ((ready += 1))
  done
  ((ready == ${#required_ports[@]})) && break

  for pid in "${pids[@]}"; do
    kill -0 "$pid" >/dev/null 2>&1 || die "A port-forward stopped during startup."
  done
  sleep 0.3
done

missing=()
for port in "${required_ports[@]}"; do
  has_port "$port" || missing+=("$port")
done
((${#missing[@]} == 0)) || die "Timed out waiting for local port(s): ${missing[*]}"

printf '\nEndpoints ready:\n'
for forward in "${forwards[@]}"; do
  read -r name local_port _ scheme <<<"$forward"
  printf '  %-12s %s://localhost:%s\n' "$name" "$scheme" "$local_port"
done
printf '  %-12s http://localhost:%s\n' "kubernetes" "$proxy_port"
printf '  aiops       http://localhost:8000 (start separately for Grafana inbound test)\n'

printf '\nCredential requirements:\n'
printf '  Prometheus, Jaeger, Kubernetes proxy, Grafana health: no service credential\n'
printf '  OpenSearch: Basic Auth username/password is required\n'
printf '  Grafana inbound webhook: shared secret must match the AIOps process\n'
printf '  Notification: external webhook URL; it cannot be port-forwarded\n'
printf '\nPress Ctrl+C to stop only the processes created by this script.\n'

while true; do
  for pid in "${pids[@]}"; do
    kill -0 "$pid" >/dev/null 2>&1 || die "A port-forward stopped unexpectedly."
  done
  sleep 5
done
