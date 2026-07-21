# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

FROM nginxinc/nginx-unprivileged:1.29-alpine-otel@sha256:5aebabed78e4f579f520950bafe0766a21259b51911474307aed03065e1a1042

USER root
RUN apk upgrade --no-cache
USER 101

COPY src/image-provider/static/ /static/
COPY src/image-provider/nginx.conf.template /nginx.conf.template

EXPOSE ${IMAGE_PROVIDER_PORT}

STOPSIGNAL SIGQUIT

# Start nginx
CMD ["/bin/sh" , "-c" , "mkdir -p /tmp/nginx/client_body /tmp/nginx/proxy /tmp/nginx/fastcgi /tmp/nginx/uwsgi /tmp/nginx/scgi && envsubst '$OTEL_COLLECTOR_HOST $IMAGE_PROVIDER_PORT $OTEL_COLLECTOR_PORT_GRPC $OTEL_SERVICE_NAME' < /nginx.conf.template > /tmp/nginx.conf && cat /tmp/nginx.conf && exec nginx -c /tmp/nginx.conf -g 'daemon off;'"]
# Change trail: @hungxqt - 2026-07-20 - Trivy HIGH/CRITICAL remediation (base upgrades, OS package updates, dep bumps)
