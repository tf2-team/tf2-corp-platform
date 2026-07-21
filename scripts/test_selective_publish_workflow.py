#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
"""Policy tests for BUILD_SET-only publishing in build-and-push.yml."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "build-and-push.yml"
RELEASE = json.loads((ROOT / "scripts" / "release_services.json").read_text())


def expected_build_set(paths: list[str]) -> list[str]:
    """Reference cases for the workflow's path classifier."""
    full_triggers = ("pb/", "buildkitd.toml", ".env", ".gitmodules")
    if any(path in full_triggers or path.startswith("pb/") for path in paths):
        return RELEASE

    selected: set[str] = set()
    for path in paths:
        if path == "third-party/mem0" or path.startswith("third-party/mem0/"):
            selected.add("mem0")
        elif path.startswith("src/"):
            service = path.split("/", 2)[1]
            if service in RELEASE:
                selected.add(service)
    return [service for service in RELEASE if service in selected]


class SelectivePublishWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_single_service_selects_only_llm(self) -> None:
        self.assertEqual(expected_build_set(["src/llm/app.py"]), ["llm"])

    def test_docs_only_selects_nothing(self) -> None:
        self.assertEqual(expected_build_set(["docs/CICD.md"]), [])

    def test_three_services_select_exactly_three(self) -> None:
        paths = ["src/email/Gemfile", "src/llm/app.py", "src/opensearch/Dockerfile"]
        self.assertEqual(expected_build_set(paths), ["email", "llm", "opensearch"])

    def test_global_retag_paths_are_removed(self) -> None:
        self.assertNotIn("\n  retag:\n", self.workflow)
        self.assertNotIn("previous_tag:", self.workflow)
        self.assertNotIn("PREV_TAG", self.workflow)

    def test_security_and_promotion_use_build_set(self) -> None:
        self.assertGreaterEqual(
            self.workflow.count("needs.preflight.outputs.build_services"), 8
        )
        self.assertIn("needs.preflight.outputs.build_count != '0'", self.workflow)
        self.assertIn("needs.release-ready.result == 'success'", self.workflow)

    def test_force_full_requires_reason(self) -> None:
        self.assertIn(
            "full_rebuild_reason is required when force_full_rebuild=true",
            self.workflow,
        )


if __name__ == "__main__":
    unittest.main()
