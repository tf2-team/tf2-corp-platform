# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import os
import re
from pathlib import Path


def test_content_capture_disabled_in_compose():
    platform_dir = Path(__file__).resolve().parents[3]
    compose_files = list(platform_dir.glob("docker-compose*.yml"))
    assert len(compose_files) > 0

    pattern = re.compile(r"OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT\s*=\s*(true|1)", re.IGNORECASE)

    violations = []
    for cf in compose_files:
        content = cf.read_text(encoding="utf-8")
        matches = pattern.findall(content)
        if matches:
            violations.append(f"{cf.name}: contains OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true")

    assert not violations, f"Content capture must be false in all Compose files: {violations}"


# Change trail: @hungxqt - 2026-07-29 - Regression test asserting message content capture is disabled in compose files.
