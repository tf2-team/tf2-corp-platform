#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
"""Fail when a Dockerfile uses an external base image without a SHA-256 digest."""

from __future__ import annotations

import re
from pathlib import Path

FROM = re.compile(r"^FROM\s+(?:--platform=\S+\s+)?(\S+)", re.IGNORECASE)
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")


def main() -> None:
    failures: list[str] = []
    for dockerfile in sorted(Path("src").rglob("Dockerfile*")):
        stages: set[str] = set()
        for lineno, line in enumerate(dockerfile.read_text(encoding="utf-8").splitlines(), 1):
            match = FROM.match(line.strip())
            if not match:
                continue
            image = match.group(1)
            if image.lower() in stages:
                continue
            if not DIGEST.search(image):
                failures.append(f"{dockerfile}:{lineno}: unpinned base image: {image}")
            stage_match = re.search(r"\s+AS\s+(\S+)\s*$", line, re.IGNORECASE)
            if stage_match:
                stages.add(stage_match.group(1).lower())
    if failures:
        raise SystemExit("\n".join(failures))
    print("All external Dockerfile base images are pinned by sha256 digest.")


if __name__ == "__main__":
    main()
