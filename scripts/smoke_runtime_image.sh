#!/bin/sh
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

set -eu

service="${1:?service is required}"
image="${2:?image is required}"
name="mandate10-${service}-${GITHUB_RUN_ID:-local}-smoke"

cleanup() {
  docker rm -f "${name}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

wait_for_http() {
  wait_url="$1"
  wait_expected="$2"
  wait_attempts="${3:-30}"
  wait_code=""
  wait_i=1
  while [ "${wait_i}" -le "${wait_attempts}" ]; do
    wait_code="$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 2 "${wait_url}" || true)"
    if [ "${wait_code}" = "${wait_expected}" ]; then
      return 0
    fi
    sleep 3
    wait_i=$((wait_i + 1))
  done
  docker logs "${name}" >&2 || true
  echo "${service} smoke test failed: ${wait_url} returned ${wait_code:-none}, expected ${wait_expected}" >&2
  return 1
}

case "${service}" in
  email)
    docker run --detach --name "${name}" \
      --env APP_ENV=production --env EMAIL_PORT=8080 \
      --publish 127.0.0.1::8080 "${image}" >/dev/null
    port="$(docker port "${name}" 8080/tcp | awk -F: 'NR == 1 {print $NF}')"
    wait_for_http "http://127.0.0.1:${port}/" 404 20
    docker run --rm --entrypoint bundle "${image}" check
    ;;
  llm)
    docker run --detach --name "${name}" \
      --env 'LLM_PORT=tcp://172.20.78.42:8000' --env APP_PORT=8000 \
      --publish 127.0.0.1::8000 "${image}" >/dev/null
    port="$(docker port "${name}" 8000/tcp | awk -F: 'NR == 1 {print $NF}')"
    wait_for_http "http://127.0.0.1:${port}/v1/models" 200 20
    ;;
  opensearch)
    smoke_admin_password="CiSmoke-${GITHUB_RUN_ID:-local}-A9!"
    docker run --detach --name "${name}" \
      --env 'discovery.type=single-node' \
      --env DISABLE_INSTALL_DEMO_CONFIG=false \
      --env OPENSEARCH_INITIAL_ADMIN_PASSWORD="${smoke_admin_password}" \
      --env 'OPENSEARCH_JAVA_OPTS=-Xms512m -Xmx512m' \
      --publish 127.0.0.1::9200 "${image}" >/dev/null
    port="$(docker port "${name}" 9200/tcp | awk -F: 'NR == 1 {print $NF}')"
    wait_i=1
    wait_code=""
    while [ "${wait_i}" -le 40 ]; do
      wait_code="$(curl --insecure --user "admin:${smoke_admin_password}" --silent --output /dev/null --write-out '%{http_code}' --max-time 2 "https://127.0.0.1:${port}/_cluster/health" || true)"
      [ "${wait_code}" = 200 ] && break
      sleep 3
      wait_i=$((wait_i + 1))
    done
    if [ "${wait_code}" != 200 ]; then
      docker logs "${name}" >&2 || true
      echo "${service} HTTPS smoke failed with ${wait_code:-none}" >&2
      exit 1
    fi
    health="$(curl --insecure --user "admin:${smoke_admin_password}" --silent --show-error "https://127.0.0.1:${port}/_cluster/health")"
    printf '%s\n' "${health}" | grep -Eq '"status":"(green|yellow)"'
    ! docker logs "${name}" 2>&1 | grep -Eq 'jar hell|NoClassDefFoundError|ClassNotFoundException'
    ;;
  *)
    echo "No runtime smoke test defined for ${service}" >&2
    exit 2
    ;;
esac

echo "Runtime smoke test passed for ${service}."
