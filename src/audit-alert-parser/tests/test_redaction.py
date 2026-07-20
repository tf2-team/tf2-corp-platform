#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from audit_alert_parser.redaction import REDACTED, is_sensitive_key, redact, redact_text


def test_sensitive_keys_are_redacted_recursively() -> None:
    payload = {
        "metadata": {
            "name": "safe-name",
            "password": "super-secret-password",
            "clientKeyData": "private-key-material",
        },
        "items": [{"authorization": "Bearer abc123"}, {"value": "safe"}],
    }

    result = redact(payload)

    assert result["metadata"]["name"] == "safe-name"
    assert result["metadata"]["password"] == REDACTED
    assert result["metadata"]["clientKeyData"] == REDACTED
    assert result["items"][0]["authorization"] == REDACTED
    assert result["items"][1]["value"] == "safe"


def test_secret_looking_values_are_redacted_from_text() -> None:
    text = (
        "call https://discord.com/api/webhooks/123/secret "
        "with Bearer abc.def.ghi and AKIA1234567890ABCDEF"
    )

    result = redact_text(text)

    assert "https://discord.com/api/webhooks" not in result
    assert "Bearer abc.def.ghi" not in result
    assert "AKIA1234567890ABCDEF" not in result
    assert result.count(REDACTED) == 3


def test_sensitive_key_detection_handles_common_variants() -> None:
    assert is_sensitive_key("x-api-key") is True
    assert is_sensitive_key("client_secret") is True
    assert is_sensitive_key("sessionToken") is True
    assert is_sensitive_key("request_id") is False
