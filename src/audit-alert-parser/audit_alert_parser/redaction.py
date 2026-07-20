#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Redaction helpers for alert-safe output."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

SENSITIVE_KEY_FRAGMENTS = (
    "accesskey",
    "authorization",
    "apikey",
    "api_key",
    "clientsecret",
    "cookie",
    "credential",
    "password",
    "secret",
    "sessiontoken",
    "token",
    "webhook",
    "privatekey",
    "clientkeydata",
    "certificate",
)

REDACTED = "[REDACTED]"

SECRET_VALUE_PATTERNS = (
    # Discord/webhook URLs must never leave the parser in alert text.
    re.compile(r"https://discord(?:app)?\.com/api/webhooks/[^\s\"']+", re.IGNORECASE),
    re.compile(r"https://hooks\.slack\.com/services/[^\s\"']+", re.IGNORECASE),
    # Common auth header formats.
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"\bBasic\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    # AWS access key IDs. Secret access keys are normally caught by key-name
    # redaction, but this protects accidental free-text leaks too.
    re.compile(r"\bA(?:KIA|SIA)[A-Z0-9]{16}\b"),
)


def is_sensitive_key(key: str) -> bool:
    normalized = key.replace("_", "").replace("-", "").lower()
    return any(fragment in normalized for fragment in SENSITIVE_KEY_FRAGMENTS)


def redact(value: Any) -> Any:
    """Recursively redact sensitive keys and known secret value patterns."""

    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, nested_value in value.items():
            text_key = str(key)
            redacted[text_key] = REDACTED if is_sensitive_key(text_key) else redact(nested_value)
        return redacted

    if isinstance(value, list):
        return [redact(item) for item in value]

    if isinstance(value, str):
        return redact_text(value)

    return value


def redact_text(value: str) -> str:
    """Redact secret-looking values from free text without hiding safe context."""

    redacted = value
    for pattern in SECRET_VALUE_PATTERNS:
        redacted = pattern.sub(REDACTED, redacted)
    return redacted
