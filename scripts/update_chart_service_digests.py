#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
"""Update only per-service Helm values files for images rebuilt in this run."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
COMPONENT_ALIASES = {"load-generator": ("load-generator", "load-generator-worker")}
TOP_LEVEL_IMAGES = {"mem0"}


def render(service: str, digest: str) -> str:
    header = "# Managed by tf2-corp-platform secure delivery pipeline.\n"
    if service in TOP_LEVEL_IMAGES:
        return f'{header}{service}:\n  image:\n    digest: "{digest}"\n'
    components = COMPONENT_ALIASES.get(service, (service,))
    body = [header.rstrip(), "components:"]
    for component in components:
        body.extend((f"  {component}:", "    imageOverride:", f'      digest: "{digest}"'))
    return "\n".join(body) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--services-json", required=True)
    parser.add_argument("--digests-json", required=True)
    args = parser.parse_args()
    services = json.loads(args.services_json)
    digests = json.loads(args.digests_json)
    if not isinstance(services, list) or not all(isinstance(s, str) for s in services):
        raise SystemExit("services-json must be an array of service names")
    args.directory.mkdir(parents=True, exist_ok=True)
    changed: list[str] = []
    for service in services:
        digest = digests.get(service, "")
        if not DIGEST.fullmatch(digest):
            raise SystemExit(f"missing or invalid digest for {service}: {digest!r}")
        path = args.directory / f"values-{service}.yaml"
        content = render(service, digest)
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8", newline="\n")
            changed.append(path.name)
    print(json.dumps(changed))


if __name__ == "__main__":
    main()
