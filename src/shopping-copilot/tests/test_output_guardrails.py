#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "ai-common"))

from techx_ai_common.contracts import GuardrailAction
from techx_ai_common import guardrails


def test_output_allows_astronomy_location_names(monkeypatch):
    analyzer = MagicMock()
    analyzer.analyze.return_value = []
    monkeypatch.setattr(guardrails, "_get_presidio_engines", lambda: (analyzer, None))

    result = guardrails.scan_output("Jupiter is visible through a refractor telescope.")

    assert result.action == GuardrailAction.ALLOW
    assert analyzer.analyze.call_args.kwargs["entities"] == ["EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD"]


def test_output_blocks_detected_sensitive_data(monkeypatch):
    analyzer = MagicMock()
    analyzer.analyze.return_value = [MagicMock()]
    monkeypatch.setattr(guardrails, "_get_presidio_engines", lambda: (analyzer, None))

    result = guardrails.scan_output("Contact a customer by email.")

    assert result.action == GuardrailAction.BLOCK


def test_input_preserves_product_names_but_redacts_contact_details(monkeypatch):
    analyzer = MagicMock()
    anonymizer = MagicMock()
    analyzer.analyze.return_value = []
    anonymizer.anonymize.side_effect = lambda **kwargs: type(
        "Result", (), {"text": kwargs["text"]}
    )()
    monkeypatch.setattr(guardrails, "_get_presidio_engines", lambda: (analyzer, anonymizer))

    assert guardrails.redact_pii("Roof Binoculars") == "Roof Binoculars"
    assert "LOCATION" not in analyzer.analyze.call_args.kwargs["entities"]
    assert "[REDACTED]" in guardrails.redact_pii("Email me at user@example.com")
