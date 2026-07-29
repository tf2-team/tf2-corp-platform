#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
"""Update Helm digest values for images rebuilt in this run.

Writes under ``service-digest/values-<service>.yaml`` relative to the chart
repository root (or an explicit ``--directory`` that already points at
``service-digest``). Production promotion may synchronize the signed ``aiops``
digest to ``values-aiops-live-executor.yaml`` as part of the same reviewed
chart PR.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
COMPONENT_ALIASES = {"load-generator": ("load-generator", "load-generator-worker")}
TOP_LEVEL_IMAGES = {"aiops", "mem0"}
DEFAULT_SUBDIR = "service-digest"


def render(service: str, digest: str) -> str:
    header = (
        "# Managed by tf2-corp-platform secure delivery pipeline.\n"
        "# Change trail: @hungxqt - 2026-07-20 - Selective service digest promote into service-digest/.\n"
    )
    if service == "aiops":
        return (
            f"{header}aiops:\n"
            "  enabled: true\n"
            "  existingSecret: techx-corp-aiops-grafana-webhook\n"
            "  image:\n"
            f'    digest: "{digest}"\n'
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


def resolve_chart_root(directory: Path) -> Path:
    """Return the chart root when given either the root or service-digest."""
    directory = directory.resolve()
    if directory.name == DEFAULT_SUBDIR:
        return directory.parent
    return directory


def update_aiops_live_executor(chart_root: Path, digest: str) -> bool:
    """Replace only aiopsLiveExecutor.image.digest in the chart overlay."""
    if not DIGEST.fullmatch(digest):
        raise SystemExit(f"invalid aiops live executor digest: {digest!r}")

    path = chart_root / "values-aiops-live-executor.yaml"
    if not path.is_file():
        raise SystemExit(f"missing aiops live executor values file: {path}")

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    section_start = next(
        (
            index
            for index, line in enumerate(lines)
            if line.strip() == "aiopsLiveExecutor:"
            and not line.startswith((" ", "\t"))
        ),
        None,
    )
    if section_start is None:
        raise SystemExit(f"missing top-level aiopsLiveExecutor section in {path}")

    section_end = len(lines)
    for index in range(section_start + 1, len(lines)):
        stripped = lines[index].strip()
        if stripped and not stripped.startswith("#") and not lines[index].startswith((" ", "\t")):
            section_end = index
            break

    image_start = next(
        (
            index
            for index in range(section_start + 1, section_end)
            if lines[index].startswith("  image:") and lines[index].strip() == "image:"
        ),
        None,
    )
    if image_start is None:
        raise SystemExit(f"missing aiopsLiveExecutor.image section in {path}")

    image_end = section_end
    for index in range(image_start + 1, section_end):
        stripped = lines[index].strip()
        if stripped and not stripped.startswith("#") and len(lines[index]) - len(lines[index].lstrip(" ")) <= 2:
            image_end = index
            break

    digest_indexes = [
        index
        for index in range(image_start + 1, image_end)
        if lines[index].startswith("    digest:") and lines[index].strip().startswith("digest:")
    ]
    if len(digest_indexes) != 1:
        raise SystemExit(
            f"expected exactly one aiopsLiveExecutor.image.digest in {path}, found {len(digest_indexes)}"
        )

    digest_index = digest_indexes[0]
    newline = "\r\n" if lines[digest_index].endswith("\r\n") else "\n"
    replacement = f"    digest: {digest}{newline}"
    if lines[digest_index] == replacement:
        return False

    lines[digest_index] = replacement
    path.write_text("".join(lines), encoding="utf-8", newline="")
    return True


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
    parser.add_argument(
        "--promote-aiops-live-executor",
        action="store_true",
        help="Also update values-aiops-live-executor.yaml with the rebuilt aiops digest.",
    )
    args = parser.parse_args()
    services = json.loads(args.services_json)
    digests = json.loads(args.digests_json)
    if not isinstance(services, list) or not all(isinstance(s, str) for s in services):
        raise SystemExit("services-json must be an array of service names")
    if args.promote_aiops_live_executor and "aiops" not in services:
        raise SystemExit("--promote-aiops-live-executor requires aiops in services-json")
    for service in services:
        digest = digests.get(service, "")
        if not DIGEST.fullmatch(digest):
            raise SystemExit(f"missing or invalid digest for {service}: {digest!r}")

    out_dir = resolve_output_dir(args.directory, args.subdir)
    out_dir.mkdir(parents=True, exist_ok=True)
    changed: list[str] = []
    for service in services:
        digest = digests[service]
        path = out_dir / f"values-{service}.yaml"
        content = render(service, digest)
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8", newline="\n")
            if out_dir.name == DEFAULT_SUBDIR:
                changed.append(f"{DEFAULT_SUBDIR}/values-{service}.yaml")
            else:
                changed.append(path.name)
    if args.promote_aiops_live_executor:
        aiops_digest = digests["aiops"]
        if update_aiops_live_executor(resolve_chart_root(args.directory), aiops_digest):
            changed.append("values-aiops-live-executor.yaml")
    print(json.dumps(changed))


if __name__ == "__main__":
    main()
# Change trail: @hungxqt - 2026-07-20 - Write selective digests under chart service-digest/.
