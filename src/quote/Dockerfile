# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0


FROM docker.io/mlocati/php-extension-installer:2.9.11@sha256:693f97d7f4c9ea8022bbddeb45abdbd1599714ff1f187fe5d13c12b2e95eb5f9 AS installer

FROM docker.io/library/composer:2.8.12@sha256:5248900ab8b5f7f880c2d62180e40960cd87f60149ec9a1abfd62ac72a02577c AS vendor

WORKDIR /tmp/

COPY ./src/quote/composer.json ./src/quote/composer.lock ./
COPY ./src/quote/src/ src/

RUN composer install \
    --ignore-platform-req=ext-pcntl \
    --ignore-platform-req=ext-opentelemetry \
    --no-interaction \
    --no-plugins \
    --no-scripts \
    --no-dev \
    --prefer-dist \
    --classmap-authoritative

FROM docker.io/library/php:8.4-cli-alpine3.22@sha256:191228671fb45eb35d0fa53d909b2bdd4c01dc5077c9005dda3695b07154c6f6

COPY --from=installer /usr/bin/install-php-extensions /usr/local/bin/

RUN apk upgrade --no-cache \
    && install-php-extensions pcntl protobuf-4.33.6 opentelemetry-1.2.1 \
    && php -m | grep -E '^(pcntl|protobuf|opentelemetry)$'

WORKDIR /var/www

USER www-data

COPY --from=vendor /tmp/vendor/ vendor/

COPY ./src/quote/app/ app/
COPY ./src/quote/public/ public/
COPY ./src/quote/src/ src/

EXPOSE ${QUOTE_PORT}

CMD ["php", "public/index.php"]
# Change trail: @hungxqt - 2026-07-20 - Trivy HIGH/CRITICAL remediation (base upgrades, OS package updates, dep bumps)
