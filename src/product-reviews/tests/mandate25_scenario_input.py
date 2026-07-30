#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Fault injection only for Mandate #25 live scenarios.

Normal runtime settings (provider, timeouts, retry, schema retry, and circuit
breaker) come from ``.env.override``. Keep only the injected incident here.
"""

from __future__ import annotations

SCENARIO_CONFIGS: dict[str, dict[str, str]] = {
    "shopping-copilot/provider-failure": {
        "BEDROCK_FAULT_INJECTION_ENABLED": "true",
        "BEDROCK_FAULT_WORKFLOW_STEP": "retrieval_hint",
        "BEDROCK_FAULT_SEQUENCE": "timeout,timeout",
    },
    "shopping-copilot/sustained-failure": {
        "BEDROCK_FAULT_INJECTION_ENABLED": "true",
        "BEDROCK_FAULT_WORKFLOW_STEP": "retrieval_hint",
        "BEDROCK_FAULT_SEQUENCE": (
            "timeout,timeout,timeout,timeout,timeout,timeout,pass"
        ),
    },
    "shopping-copilot/malformed-tool-call": {
        "BEDROCK_FAULT_INJECTION_ENABLED": "true",
        "BEDROCK_FAULT_WORKFLOW_STEP": "react_round",
        "BEDROCK_FAULT_SEQUENCE": "malformed_tool_call",
    },
    "product-reviews/provider-failure": {
        "BEDROCK_FAULT_INJECTION_ENABLED": "true",
        "BEDROCK_FAULT_WORKFLOW_STEP": "grounded_summary",
        "BEDROCK_FAULT_SEQUENCE": "server_error,server_error",
    },
    "product-reviews/malformed-json": {
        "BEDROCK_FAULT_INJECTION_ENABLED": "true",
        "BEDROCK_FAULT_WORKFLOW_STEP": "grounded_summary",
        "BEDROCK_FAULT_SEQUENCE": "malformed_json",
    },
    "product-reviews/sustained-failure": {
        "BEDROCK_FAULT_INJECTION_ENABLED": "true",
        "BEDROCK_FAULT_WORKFLOW_STEP": "grounded_summary",
        "BEDROCK_FAULT_SEQUENCE": (
            "timeout,timeout,timeout,timeout,timeout,timeout,pass"
        ),
    },
}
