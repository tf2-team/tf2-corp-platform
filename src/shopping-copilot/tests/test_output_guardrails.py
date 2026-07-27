#!/usr/bin/python

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
