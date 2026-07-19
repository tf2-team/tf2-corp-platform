#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Populate a local Docker volume with a validated Mem0 FastEmbed cache."""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path
from typing import Callable

try:
    from . import build_embedding_model_artifact as builder
    from . import validate_embedding_model_artifact as validator
except ImportError:  # Support direct execution from the Docker bind mount.
    import build_embedding_model_artifact as builder
    import validate_embedding_model_artifact as validator


CacheValidator = Callable[[Path], None]
ArtifactBuilder = Callable[[Path], tuple[Path, Path, Path]]


def validate_cache(cache_dir: Path) -> None:
    """Verify the cache layout and load the model without network access."""
    validator.validate_manifest(cache_dir)
    validator.validate_runtime(cache_dir)


def _clear_cache(cache_dir: Path) -> None:
    cache_dir = cache_dir.resolve()
    if cache_dir == Path(cache_dir.anchor):
        raise ValueError("Refusing to clear a filesystem root")
    cache_dir.mkdir(parents=True, exist_ok=True)
    for item in cache_dir.iterdir():
        if item.is_dir() and not item.is_symlink():
            shutil.rmtree(item)
        else:
            item.unlink()


def seed_cache(
    cache_dir: Path,
    *,
    artifact_builder: ArtifactBuilder = builder.build_artifact,
    cache_validator: CacheValidator = validate_cache,
) -> bool:
    """Return true when a new artifact was built, false when a valid cache exists."""
    cache_dir = cache_dir.resolve()
    try:
        cache_validator(cache_dir)
    except (FileNotFoundError, ValueError, RuntimeError):
        pass
    else:
        print(f"Mem0 FastEmbed cache is already valid: {cache_dir}")
        return False

    with tempfile.TemporaryDirectory(prefix="mem0-fastembed-local-") as temporary:
        archive, checksum, _ = artifact_builder(Path(temporary))
        validator.validate_artifact(archive, checksum, run_runtime=False)
        _clear_cache(cache_dir)
        validator._safe_extract(archive, cache_dir)

    cache_validator(cache_dir)
    print(f"Mem0 FastEmbed cache seeded: {cache_dir}")
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=Path("/models/fastembed"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    seed_cache(args.cache_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
