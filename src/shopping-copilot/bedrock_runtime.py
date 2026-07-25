#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Compatibility imports for the shared Bedrock Converse adapter."""

from techx_ai_common.bedrock import (
    BedrockDeadlineExceededError,
    BedrockUnavailableError,
    CircuitBreakerOpenError,
    InvalidModelOutputError,
    converse_json,
    get_breaker_state,
    is_bedrock_provider,
)

__all__ = [
    "BedrockDeadlineExceededError",
    "BedrockUnavailableError",
    "CircuitBreakerOpenError",
    "InvalidModelOutputError",
    "converse_json",
    "get_breaker_state",
    "is_bedrock_provider",
]
