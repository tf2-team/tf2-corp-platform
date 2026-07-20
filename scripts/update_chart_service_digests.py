#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
"""Update only per-service Helm values files for images rebuilt in this run.

Writes under ``service-digest/values-<service>.yaml`` relative to the chart
repository root (or an explicit ``--directory`` that already points at
``service-digest``).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
COMPONENT_ALIASES = {"load-generator": ("load-generator", "load-generator-worker")}
TOP_LEVEL_IMAGES = {"mem0"}
DEFAULT_SUBDIR = "service-digest"


def render(service: str, digest: str) -> str:
    header = (
        "# Managed by tf2-corp-platform secure delivery pipeline.\n"
        "# Change trail: @hungxqt - 2026-07-20 - Selective service digest promote into service-digest/.\n"
    )
    if service in TOP_LEVEL_IMAGES:
        return f'{header}{service}:\n  image:\n    digest: "{digest}"\n'
    if service == "flagd-ui":
        return (
            f"{header}components:\n"
            "  flagd:\n"
            "    sidecarImageDigests:\n"
            f'      flagd-ui: "{digest}"\n'
        )
    components = COMPONENT_ALIASES.get(service, (service,))
    body = [header.rstrip(), "components:"]
    for component in components:
        body.extend((f"  {component}:", "    imageOverride:", f'      digest: "{digest}"'))
    return "\n".join(body) + "\n"


def resolve_output_dir(directory: Path, subdir: str) -> Path:
    """Accept chart root or service-digest path."""
    directory = directory.resolve()
    if directory.name == DEFAULT_SUBDIR or subdir in ("", "."):
        return directory
    return directory / subdir


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--directory",
        type=Path,
        required=True,
        help="Chart repo root, or the service-digest directory itself.",
    )
    parser.add_argument(
        "--subdir",
        default=DEFAULT_SUBDIR,
        help=f"Subdirectory under chart root (default: {DEFAULT_SUBDIR}). "
        "Ignored when --directory already ends with this name.",
    )
    parser.add_argument("--services-json", required=True)
    parser.add_argument("--digests-json", required=True)
    args = parser.parse_args()
    services = json.loads(args.services_json)
    digests = json.loads(args.digests_json)
    if not isinstance(services, list) or not all(isinstance(s, str) for s in services):
        raise SystemExit("services-json must be an array of service names")
    out_dir = resolve_output_dir(args.directory, args.subdir)
    out_dir.mkdir(parents=True, exist_ok=True)
    changed: list[str] = []
    for service in services:
        digest = digests.get(service, "")
        if not DIGEST.fullmatch(digest):
            raise SystemExit(f"missing or invalid digest for {service}: {digest!r}")
        path = out_dir / f"values-{service}.yaml"
        content = render(service, digest)
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8", newline="\n")
            if out_dir.name == DEFAULT_SUBDIR:
                changed.append(f"{DEFAULT_SUBDIR}/values-{service}.yaml")
            else:
                changed.append(path.name)
    print(json.dumps(changed))


if __name__ == "__main__":
    main()
# Change trail: @hungxqt - 2026-07-20 - Write selective digests under chart service-digest/.
