#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Shared AI runtime primitives used by TechX AI services."""

from .observability import (
    ai_context_scope,
    bedrock_converse_adapter,
    calculate_cost,
    chat_completions_create,
    get_ai_context,
    get_hmac_key,
    get_model_pricing,
    instructor_create,
    pseudonymize_session,
    pseudonymize_user,
    record_chat_telemetry,
    set_ai_context,
    trace_subspan,
)

__all__ = [
    "ai_context_scope",
    "bedrock_converse_adapter",
    "calculate_cost",
    "chat_completions_create",
    "get_ai_context",
    "get_hmac_key",
    "get_model_pricing",
    "instructor_create",
    "pseudonymize_session",
    "pseudonymize_user",
    "record_chat_telemetry",
    "set_ai_context",
    "trace_subspan",
]

# Change trail: @hungxqt - 2026-07-29 - Export shared observability primitives in __init__.py.

