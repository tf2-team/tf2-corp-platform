# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0


FROM docker.io/library/ruby:3.4.7-alpine3.22 AS builder

COPY ./src/email/Gemfile Gemfile
COPY ./src/email/Gemfile.lock Gemfile.lock

RUN apk update && \
    apk add make gcc musl-dev gcompat && \
    bundle install

FROM docker.io/library/ruby:3.4.7-alpine3.22

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
