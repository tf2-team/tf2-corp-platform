# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0


FROM docker.io/library/ruby:3.4.7-alpine3.22@sha256:2a968472f07d03fd9c9fdfe220881c18fc0b28eb4d514b36b2c2d23810d70b89 AS builder

COPY ./src/email/Gemfile Gemfile
COPY ./src/email/Gemfile.lock Gemfile.lock

RUN apk upgrade --no-cache && \
    apk add --no-cache make gcc musl-dev gcompat && \
    bundle install

FROM docker.io/library/ruby:3.4.7-alpine3.22@sha256:2a968472f07d03fd9c9fdfe220881c18fc0b28eb4d514b36b2c2d23810d70b89

RUN apk upgrade --no-cache

COPY --from=builder /usr/local/bundle/ /usr/local/bundle/

WORKDIR /email_server

RUN addgroup -g 10001 -S appgroup && \
    adduser -u 10001 -S -G appgroup appuser

COPY --chown=appuser:appgroup ./src/email/views/ views/

COPY --chown=appuser:appgroup ./src/email/.ruby-version .ruby-version
COPY --chown=appuser:appgroup ./src/email/Gemfile Gemfile
COPY --chown=appuser:appgroup ./src/email/Gemfile.lock Gemfile.lock
COPY --chown=appuser:appgroup ./src/email/email_server.rb email_server.rb

RUN chown -R appuser:appgroup /email_server

USER 10001

EXPOSE ${EMAIL_PORT}
ENTRYPOINT ["bundle", "exec", "ruby", "email_server.rb"]
# Change trail: @hungxqt - 2026-07-20 - apk upgrade and gem security bumps for Trivy
