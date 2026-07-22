#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
"""Ensure scripts/release_services.json matches docker-bake.hcl release group size/names."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "scripts" / "release_services.json"
BAKE = ROOT / "docker-bake.hcl"


def main() -> int:
    services = json.loads(CATALOG.read_text(encoding="utf-8"))
    if not isinstance(services, list) or not services:
        print("release_services.json must be a non-empty array", file=sys.stderr)
        return 1
    if len(services) != 24:
        print(f"expected 24 release services, got {len(services)}", file=sys.stderr)
        return 1
    if len(set(services)) != len(services):
        print("duplicate entries in release_services.json", file=sys.stderr)
        return 1

    bake = BAKE.read_text(encoding="utf-8")
    # group "release" { targets = [ ... ] }
    match = re.search(
        r'group\s+"release"\s*\{[^}]*targets\s*=\s*\[(.*?)\]',
        bake,
        re.DOTALL,
    )
    if not match:
        print("could not find group \"release\" targets in docker-bake.hcl", file=sys.stderr)
        return 1
    targets = re.findall(r'"([^"]+)"', match.group(1))
    if sorted(services) != sorted(targets):
        print("release_services.json does not match docker-bake.hcl group release", file=sys.stderr)
        print(f"  json only: {sorted(set(services) - set(targets))}", file=sys.stderr)
        print(f"  bake only: {sorted(set(targets) - set(services))}", file=sys.stderr)
        return 1

    print(f"OK: {len(services)} release services match docker-bake.hcl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
# Change trail: @hungxqt - 2026-07-20 - Catalog consistency check for shared release_services.json.
