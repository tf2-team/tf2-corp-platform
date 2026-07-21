# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0


FROM ghcr.io/mlocati/php-extension-installer:2.9.11 AS installer

FROM docker.io/library/composer:2.8.12 AS vendor

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

FROM docker.io/library/php:8.4-cli-alpine3.22

COPY --from=installer /usr/bin/install-php-extensions /usr/local/bin/

RUN install-php-extensions pcntl protobuf-4.33.6 opentelemetry-1.2.1 \
    && php -m | grep -E '^(pcntl|protobuf|opentelemetry)$'

WORKDIR /var/www

USER www-data

COPY --from=vendor /tmp/vendor/ vendor/

COPY ./src/quote/app/ app/
COPY ./src/quote/public/ public/
COPY ./src/quote/src/ src/

EXPOSE ${QUOTE_PORT}

CMD ["php", "public/index.php"]
