#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Validate a Mem0 FastEmbed artifact without model-network access."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import socket
import sys
import tarfile
import tempfile
from contextlib import contextmanager
from pathlib import Path

try:
    from .build_embedding_model_artifact import (
        EMBEDDING_DIMENSION,
        FASTEMBED_VERSION,
        MANIFEST_NAME,
        MODEL_NAME,
        READY_MARKER,
        SCHEMA_VERSION,
        SOURCE_REPOSITORY,
        SOURCE_REVISION,
        sha256_file,
    )
except ImportError:  # Support direct script execution.
    from build_embedding_model_artifact import (
        EMBEDDING_DIMENSION,
        FASTEMBED_VERSION,
        MANIFEST_NAME,
        MODEL_NAME,
        READY_MARKER,
        SCHEMA_VERSION,
        SOURCE_REPOSITORY,
        SOURCE_REVISION,
        sha256_file,
    )


def verify_checksum(archive: Path, checksum: Path) -> None:
    fields = checksum.read_text(encoding="utf-8").strip().split()
    if len(fields) != 2:
        raise ValueError(f"Invalid checksum file format: {checksum}")
    expected_digest, expected_name = fields
    if expected_name.lstrip("*") != archive.name:
        raise ValueError(f"Checksum targets {expected_name!r}, not {archive.name!r}")
    actual_digest = sha256_file(archive)
    if actual_digest != expected_digest.lower():
        raise ValueError(f"Archive checksum mismatch: expected {expected_digest}, got {actual_digest}")


def _safe_extract(archive: Path, destination: Path) -> None:
    destination = destination.resolve()
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            target = (destination / member.name).resolve()
            if target != destination and destination not in target.parents:
                raise ValueError(f"Unsafe archive member path: {member.name}")
            if member.issym() or member.islnk():
                link_target = (target.parent / member.linkname).resolve()
                if link_target != destination and destination not in link_target.parents:
                    raise ValueError(f"Unsafe archive link target: {member.name} -> {member.linkname}")
        if sys.version_info >= (3, 12):
            bundle.extractall(destination, filter="fully_trusted")
        else:  # pragma: no cover - build and runtime images use Python 3.12
            bundle.extractall(destination)


def validate_manifest(root: Path) -> dict[str, object]:
    manifest_path = root / MANIFEST_NAME
    ready_path = root / READY_MARKER
    if not manifest_path.is_file() or not ready_path.is_file():
        raise ValueError("Artifact must contain manifest.json and .model-ready at its root")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {
        "schema_version": SCHEMA_VERSION,
        "model_name": MODEL_NAME,
        "dimension": EMBEDDING_DIMENSION,
        "fastembed_version": FASTEMBED_VERSION,
        "source_repository": SOURCE_REPOSITORY,
        "source_revision": SOURCE_REVISION,
    }
    actual = {
        "schema_version": manifest.get("schema_version"),
        "model_name": manifest.get("model", {}).get("name"),
        "dimension": manifest.get("model", {}).get("embedding_dimension"),
        "fastembed_version": manifest.get("model", {}).get("fastembed_version"),
        "source_repository": manifest.get("source", {}).get("repository"),
        "source_revision": manifest.get("source", {}).get("revision"),
    }
    if actual != expected:
        raise ValueError(f"Manifest contract mismatch: expected {expected}, got {actual}")

    ready = json.loads(ready_path.read_text(encoding="utf-8"))
    if ready.get("manifest_sha256") != sha256_file(manifest_path):
        raise ValueError("Ready marker does not match manifest checksum")

    for item in manifest.get("files", []):
        relative_path = Path(str(item["path"]))
        path = (root / relative_path).resolve()
        if root.resolve() not in path.parents or not path.is_file():
            raise ValueError(f"Manifest file is missing or unsafe: {relative_path}")
        if path.stat().st_size != item["size"] or sha256_file(path) != item["sha256"]:
            raise ValueError(f"Manifest file verification failed: {relative_path}")
    return manifest


@contextmanager
def blocked_network():
    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection

    def deny_network(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("Network access is disabled during offline model validation")

    socket.socket.connect = deny_network
    socket.create_connection = deny_network
    try:
        yield
    finally:
        socket.socket.connect = original_connect
        socket.create_connection = original_create_connection


def validate_runtime(root: Path) -> None:
    installed_version = importlib.metadata.version("fastembed")
    if installed_version != FASTEMBED_VERSION:
        raise RuntimeError(f"Expected fastembed=={FASTEMBED_VERSION}, found {installed_version}")

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    with blocked_network():
        from fastembed import TextEmbedding

        model = TextEmbedding(model_name=MODEL_NAME, cache_dir=str(root), local_files_only=True)
        embedding = next(iter(model.embed("Mem0 offline artifact validation")))

    if model.embedding_size != EMBEDDING_DIMENSION or len(embedding) != EMBEDDING_DIMENSION:
        raise RuntimeError(
            f"Expected {EMBEDDING_DIMENSION}-dimensional embedding, got metadata={model.embedding_size}, vector={len(embedding)}"
        )


def validate_artifact(archive: Path, checksum: Path, *, run_runtime: bool = True) -> dict[str, object]:
    archive = archive.resolve()
    checksum = checksum.resolve()
    verify_checksum(archive, checksum)
    with tempfile.TemporaryDirectory(prefix="mem0-fastembed-validate-") as temporary:
        root = Path(temporary)
        _safe_extract(archive, root)
        manifest = validate_manifest(root)
        if run_runtime:
            validate_runtime(root)
        return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--checksum", type=Path, help="Defaults to <archive>.sha256")
    parser.add_argument("--skip-runtime", action="store_true", help="Only validate archive integrity and manifest")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    checksum = args.checksum or Path(f"{args.archive}.sha256")
    manifest = validate_artifact(args.archive, checksum, run_runtime=not args.skip_runtime)
    print(
        json.dumps(
            {
                "model": manifest["model"]["name"],
                "revision": manifest["source"]["revision"],
                "dimension": manifest["model"]["embedding_dimension"],
                "offline": not args.skip_runtime,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
