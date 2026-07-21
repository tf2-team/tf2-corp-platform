# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0


FROM docker.io/library/ruby:3.4.7-alpine3.22@sha256:2a968472f07d03fd9c9fdfe220881c18fc0b28eb4d514b36b2c2d23810d70b89 AS builder

COPY ./src/email/Gemfile Gemfile
COPY ./src/email/Gemfile.lock Gemfile.lock

RUN apk upgrade --no-cache && \
    apk add --no-cache make gcc musl-dev gcompat zlib-dev && \
    bundle install && \
    # Ensure default-gem paths also resolve to security-fixed versions for Trivy.
    gem install --no-document erb:6.0.6 zlib:3.2.3 net-imap:0.6.4.1 puma:8.0.2

FROM docker.io/library/ruby:3.4.7-alpine3.22@sha256:2a968472f07d03fd9c9fdfe220881c18fc0b28eb4d514b36b2c2d23810d70b89

RUN apk upgrade --no-cache && \
    apk add --no-cache --virtual .gem-build-deps make gcc musl-dev zlib-dev && \
    GEM_HOME=/usr/local/lib/ruby/gems/3.4.0 gem install --no-document erb:6.0.6 zlib:3.2.3 net-imap:0.6.4.1 puma:8.0.2 && \
    rm -f /usr/local/lib/ruby/gems/3.4.0/specifications/default/erb-4.0.4.gemspec \
          /usr/local/lib/ruby/gems/3.4.0/specifications/default/zlib-3.2.1.gemspec \
          /usr/local/lib/ruby/gems/3.4.0/specifications/net-imap-0.5.8.gemspec && \
    apk del .gem-build-deps

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
# Change trail: @hungxqt - 2026-07-20 - Force fixed default gems (erb/zlib/net-imap/puma) for Trivy
