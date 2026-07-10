# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
#
# CI release definition layered over docker-compose.yml.
# Usage:
#   docker buildx bake -f docker-compose.yml -f docker-bake.hcl release --push
#   docker buildx bake -f docker-compose.yml -f docker-bake.hcl release --print
#
# Cache contract: ${IMAGE_NAME}/<service>:buildcache (registry cache, mode=max).
# Runtime tag:    ${IMAGE_NAME}/<service>:${DEMO_VERSION}
# buildcache is never a Helm-deployable runtime tag.

variable "IMAGE_NAME" {
  default = ""
}

variable "DEMO_VERSION" {
  default = "dev"
}

# Exactly the 20 deployable services pushed to ECR by CI.
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
    "payment",
    "product-catalog",
    "product-reviews",
    "quote",
    "recommendation",
    "shipping",
  ]
}

# Compose builds a customized OpenSearch image for local demos.
# Helm deploys the external OpenSearch chart dependency — not this image.
group "local-only" {
  targets = ["opensearch"]
}

target "_release-common" {
  platforms = ["linux/amd64", "linux/arm64"]
}

target "accounting" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/accounting:${DEMO_VERSION}"]
  cache-from = ["type=registry,ref=${IMAGE_NAME}/accounting:buildcache"]
  cache-to   = ["type=registry,ref=${IMAGE_NAME}/accounting:buildcache,mode=max,oci-mediatypes=true,image-manifest=true"]
}

target "ad" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/ad:${DEMO_VERSION}"]
  cache-from = ["type=registry,ref=${IMAGE_NAME}/ad:buildcache"]
  cache-to   = ["type=registry,ref=${IMAGE_NAME}/ad:buildcache,mode=max,oci-mediatypes=true,image-manifest=true"]
}

target "cart" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/cart:${DEMO_VERSION}"]
  cache-from = ["type=registry,ref=${IMAGE_NAME}/cart:buildcache"]
  cache-to   = ["type=registry,ref=${IMAGE_NAME}/cart:buildcache,mode=max,oci-mediatypes=true,image-manifest=true"]
}

target "checkout" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/checkout:${DEMO_VERSION}"]
  cache-from = ["type=registry,ref=${IMAGE_NAME}/checkout:buildcache"]
  cache-to   = ["type=registry,ref=${IMAGE_NAME}/checkout:buildcache,mode=max,oci-mediatypes=true,image-manifest=true"]
}

target "currency" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/currency:${DEMO_VERSION}"]
  cache-from = ["type=registry,ref=${IMAGE_NAME}/currency:buildcache"]
  cache-to   = ["type=registry,ref=${IMAGE_NAME}/currency:buildcache,mode=max,oci-mediatypes=true,image-manifest=true"]
}

target "email" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/email:${DEMO_VERSION}"]
  cache-from = ["type=registry,ref=${IMAGE_NAME}/email:buildcache"]
  cache-to   = ["type=registry,ref=${IMAGE_NAME}/email:buildcache,mode=max,oci-mediatypes=true,image-manifest=true"]
}

target "flagd-ui" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/flagd-ui:${DEMO_VERSION}"]
  cache-from = ["type=registry,ref=${IMAGE_NAME}/flagd-ui:buildcache"]
  cache-to   = ["type=registry,ref=${IMAGE_NAME}/flagd-ui:buildcache,mode=max,oci-mediatypes=true,image-manifest=true"]
}

target "fraud-detection" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/fraud-detection:${DEMO_VERSION}"]
  cache-from = ["type=registry,ref=${IMAGE_NAME}/fraud-detection:buildcache"]
  cache-to   = ["type=registry,ref=${IMAGE_NAME}/fraud-detection:buildcache,mode=max,oci-mediatypes=true,image-manifest=true"]
}

target "frontend" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/frontend:${DEMO_VERSION}"]
  cache-from = ["type=registry,ref=${IMAGE_NAME}/frontend:buildcache"]
  cache-to   = ["type=registry,ref=${IMAGE_NAME}/frontend:buildcache,mode=max,oci-mediatypes=true,image-manifest=true"]
}

target "frontend-proxy" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/frontend-proxy:${DEMO_VERSION}"]
  cache-from = ["type=registry,ref=${IMAGE_NAME}/frontend-proxy:buildcache"]
  cache-to   = ["type=registry,ref=${IMAGE_NAME}/frontend-proxy:buildcache,mode=max,oci-mediatypes=true,image-manifest=true"]
}

target "image-provider" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/image-provider:${DEMO_VERSION}"]
  cache-from = ["type=registry,ref=${IMAGE_NAME}/image-provider:buildcache"]
  cache-to   = ["type=registry,ref=${IMAGE_NAME}/image-provider:buildcache,mode=max,oci-mediatypes=true,image-manifest=true"]
}

target "kafka" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/kafka:${DEMO_VERSION}"]
  cache-from = ["type=registry,ref=${IMAGE_NAME}/kafka:buildcache"]
  cache-to   = ["type=registry,ref=${IMAGE_NAME}/kafka:buildcache,mode=max,oci-mediatypes=true,image-manifest=true"]
}

target "llm" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/llm:${DEMO_VERSION}"]
  cache-from = ["type=registry,ref=${IMAGE_NAME}/llm:buildcache"]
  cache-to   = ["type=registry,ref=${IMAGE_NAME}/llm:buildcache,mode=max,oci-mediatypes=true,image-manifest=true"]
}

target "load-generator" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/load-generator:${DEMO_VERSION}"]
  cache-from = ["type=registry,ref=${IMAGE_NAME}/load-generator:buildcache"]
  cache-to   = ["type=registry,ref=${IMAGE_NAME}/load-generator:buildcache,mode=max,oci-mediatypes=true,image-manifest=true"]
}

target "payment" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/payment:${DEMO_VERSION}"]
  cache-from = ["type=registry,ref=${IMAGE_NAME}/payment:buildcache"]
  cache-to   = ["type=registry,ref=${IMAGE_NAME}/payment:buildcache,mode=max,oci-mediatypes=true,image-manifest=true"]
}

target "product-catalog" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/product-catalog:${DEMO_VERSION}"]
  cache-from = ["type=registry,ref=${IMAGE_NAME}/product-catalog:buildcache"]
  cache-to   = ["type=registry,ref=${IMAGE_NAME}/product-catalog:buildcache,mode=max,oci-mediatypes=true,image-manifest=true"]
}

target "product-reviews" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/product-reviews:${DEMO_VERSION}"]
  cache-from = ["type=registry,ref=${IMAGE_NAME}/product-reviews:buildcache"]
  cache-to   = ["type=registry,ref=${IMAGE_NAME}/product-reviews:buildcache,mode=max,oci-mediatypes=true,image-manifest=true"]
}

target "quote" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/quote:${DEMO_VERSION}"]
  cache-from = ["type=registry,ref=${IMAGE_NAME}/quote:buildcache"]
  cache-to   = ["type=registry,ref=${IMAGE_NAME}/quote:buildcache,mode=max,oci-mediatypes=true,image-manifest=true"]
}

target "recommendation" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/recommendation:${DEMO_VERSION}"]
  cache-from = ["type=registry,ref=${IMAGE_NAME}/recommendation:buildcache"]
  cache-to   = ["type=registry,ref=${IMAGE_NAME}/recommendation:buildcache,mode=max,oci-mediatypes=true,image-manifest=true"]
}

target "shipping" {
  inherits   = ["_release-common"]
  tags       = ["${IMAGE_NAME}/shipping:${DEMO_VERSION}"]
  cache-from = ["type=registry,ref=${IMAGE_NAME}/shipping:buildcache"]
  cache-to   = ["type=registry,ref=${IMAGE_NAME}/shipping:buildcache,mode=max,oci-mediatypes=true,image-manifest=true"]
}

# Local-only: no multi-arch / registry cache contract required for CI release.
target "opensearch" {
  tags = ["${IMAGE_NAME}/opensearch:${DEMO_VERSION}"]
}
