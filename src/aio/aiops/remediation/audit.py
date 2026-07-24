#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pathlib import Path

from aiops.schemas import RemediationDecision, RemediationLifecycle


class RemediationAuditLog:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, decision: RemediationDecision) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(decision.model_dump_json() + "\n")

    def append_lifecycle(self, lifecycle: RemediationLifecycle) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(lifecycle.model_dump_json() + "\n")
