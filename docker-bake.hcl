# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
#
# CI release definition layered over docker-compose.yml.
# Usage:
#   docker buildx bake -f docker-compose.yml -f docker-bake.hcl release --push
#   docker buildx bake -f docker-compose.yml -f docker-bake.hcl release --print
#
# Cache contract: GitHub Actions BuildKit cache (type=gha, scope=<service>, mode=max).
# Runtime tag:    ${IMAGE_NAME}/<service>:${DEMO_VERSION}
# GHA cache is not an ECR tag and is safe with image_tag_mutability=IMMUTABLE.
# Outside GitHub Actions, clear cache-from/cache-to (see Makefile multiplatform push).

variable "IMAGE_NAME" {
  default = ""
}

variable "DEMO_VERSION" {
  default = "dev"
}

# Exactly the 23 deployable services pushed to ECR by CI (includes customized OpenSearch).
group "release" {
  targets = [
    "accounting",
    "ad",
    "cart",
    "checkout",
    "currency",
    "email",
    "flagd-ui",
    "fraud-detection",
    "frontend",
    "frontend-proxy",
    "image-provider",
    "kafka",
    "llm",
    "load-generator",
    "mem0",
    "opensearch",
    "payment",
    "product-catalog",
    "product-reviews",
    "quote",
    "recommendation",
    "shipping",
    "shopping-copilot",
  ]
}

target "_release-common" {
  platforms = ["linux/amd64", "linux/arm64"]
}

target "accounting" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/accounting:${DEMO_VERSION}"]
  cache-from = ["type=gha,scope=accounting"]
  cache-to   = ["type=gha,mode=max,scope=accounting"]
}

target "ad" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/ad:${DEMO_VERSION}"]
  cache-from = ["type=gha,scope=ad"]
  cache-to   = ["type=gha,mode=max,scope=ad"]
}

target "cart" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/cart:${DEMO_VERSION}"]
  cache-from = ["type=gha,scope=cart"]
  cache-to   = ["type=gha,mode=max,scope=cart"]
}

target "checkout" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/checkout:${DEMO_VERSION}"]
  cache-from = ["type=gha,scope=checkout"]
  cache-to   = ["type=gha,mode=max,scope=checkout"]
}

target "currency" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/currency:${DEMO_VERSION}"]
  cache-from = ["type=gha,scope=currency"]
  cache-to   = ["type=gha,mode=max,scope=currency"]
}

target "email" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/email:${DEMO_VERSION}"]
  cache-from = ["type=gha,scope=email"]
  cache-to   = ["type=gha,mode=max,scope=email"]
}

target "flagd-ui" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/flagd-ui:${DEMO_VERSION}"]
  cache-from = ["type=gha,scope=flagd-ui"]
  cache-to   = ["type=gha,mode=max,scope=flagd-ui"]
}

target "fraud-detection" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/fraud-detection:${DEMO_VERSION}"]
  cache-from = ["type=gha,scope=fraud-detection"]
  cache-to   = ["type=gha,mode=max,scope=fraud-detection"]
}

target "frontend" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/frontend:${DEMO_VERSION}"]
  cache-from = ["type=gha,scope=frontend"]
  cache-to   = ["type=gha,mode=max,scope=frontend"]
}

target "frontend-proxy" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/frontend-proxy:${DEMO_VERSION}"]
  cache-from = ["type=gha,scope=frontend-proxy"]
  cache-to   = ["type=gha,mode=max,scope=frontend-proxy"]
}

target "image-provider" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/image-provider:${DEMO_VERSION}"]
  cache-from = ["type=gha,scope=image-provider"]
  cache-to   = ["type=gha,mode=max,scope=image-provider"]
}

target "kafka" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/kafka:${DEMO_VERSION}"]
  cache-from = ["type=gha,scope=kafka"]
  cache-to   = ["type=gha,mode=max,scope=kafka"]
}

target "llm" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/llm:${DEMO_VERSION}"]
  cache-from = ["type=gha,scope=llm"]
  cache-to   = ["type=gha,mode=max,scope=llm"]
}

target "load-generator" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/load-generator:${DEMO_VERSION}"]
  cache-from = ["type=gha,scope=load-generator"]
  cache-to   = ["type=gha,mode=max,scope=load-generator"]
}

target "mem0" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/mem0:${DEMO_VERSION}"]
  cache-from = ["type=gha,scope=mem0"]
  cache-to   = ["type=gha,mode=max,scope=mem0"]
}

target "payment" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/payment:${DEMO_VERSION}"]
  cache-from = ["type=gha,scope=payment"]
  cache-to   = ["type=gha,mode=max,scope=payment"]
}

target "product-catalog" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/product-catalog:${DEMO_VERSION}"]
  cache-from = ["type=gha,scope=product-catalog"]
  cache-to   = ["type=gha,mode=max,scope=product-catalog"]
}

target "product-reviews" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/product-reviews:${DEMO_VERSION}"]
  cache-from = ["type=gha,scope=product-reviews"]
  cache-to   = ["type=gha,mode=max,scope=product-reviews"]
}

target "quote" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/quote:${DEMO_VERSION}"]
  cache-from = ["type=gha,scope=quote"]
  cache-to   = ["type=gha,mode=max,scope=quote"]
}

target "recommendation" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/recommendation:${DEMO_VERSION}"]
  cache-from = ["type=gha,scope=recommendation"]
  cache-to   = ["type=gha,mode=max,scope=recommendation"]
}

target "shipping" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/shipping:${DEMO_VERSION}"]
  cache-from = ["type=gha,scope=shipping"]
  cache-to   = ["type=gha,mode=max,scope=shipping"]
}

target "shopping-copilot" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/shopping-copilot:${DEMO_VERSION}"]
  cache-from = ["type=gha,scope=shopping-copilot"]
  cache-to   = ["type=gha,mode=max,scope=shopping-copilot"]
}

# Customized OpenSearch (unused plugins stripped in src/opensearch/Dockerfile;
# opensearch-security retained for SEC-06 HTTPS + basic auth). Used by Compose and Helm.
target "opensearch" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/opensearch:${DEMO_VERSION}"]
  cache-from = ["type=gha,scope=opensearch"]
  cache-to   = ["type=gha,mode=max,scope=opensearch"]
}
# Change trail: @hungxqt - 2026-07-22 - Note opensearch-security retained in slim OpenSearch image.
