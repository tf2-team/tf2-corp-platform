#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Build an immutable FastEmbed cache artifact for the Mem0 workload."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import tarfile
import tempfile
from pathlib import Path
from typing import Callable


MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
SOURCE_REPOSITORY = "Qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q"
SOURCE_REVISION = "faf4aa4225822f3bc6376869cb1164e8e3feedd0"
FASTEMBED_VERSION = "0.8.0"
EMBEDDING_DIMENSION = 384
MANIFEST_NAME = "manifest.json"
READY_MARKER = ".model-ready"
SCHEMA_VERSION = 1


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inventory(root: Path) -> list[dict[str, object]]:
    files: list[dict[str, object]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or path.name in {MANIFEST_NAME, READY_MARKER}:
            continue
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return files


def _normalize_tar_info(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    return info


def create_deterministic_archive(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as raw_stream:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_stream, mtime=0) as gzip_stream:
            with tarfile.open(fileobj=gzip_stream, mode="w", format=tarfile.PAX_FORMAT, dereference=False) as archive:
                for path in sorted(source.rglob("*"), key=lambda item: item.relative_to(source).as_posix()):
                    arcname = path.relative_to(source).as_posix()
                    info = _normalize_tar_info(archive.gettarinfo(str(path), arcname=arcname))
                    if info.isfile():
                        with path.open("rb") as file_stream:
                            archive.addfile(info, fileobj=file_stream)
                    else:
                        archive.addfile(info)


def _default_snapshot_downloader(**kwargs: object) -> str:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:  # pragma: no cover - exercised by the CLI environment
        raise RuntimeError("huggingface-hub is required to build the FastEmbed artifact") from exc
    return snapshot_download(**kwargs)


def build_artifact(
    output_dir: Path,
    *,
    snapshot_downloader: Callable[..., str] = _default_snapshot_downloader,
) -> tuple[Path, Path, Path]:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_name = f"fastembed-paraphrase-multilingual-MiniLM-L12-v2-{SOURCE_REVISION[:12]}.tar.gz"
    archive_path = output_dir / archive_name
    checksum_path = output_dir / f"{archive_name}.sha256"
    manifest_output_path = output_dir / MANIFEST_NAME

    with tempfile.TemporaryDirectory(prefix="mem0-fastembed-") as temporary:
        artifact_root = Path(temporary) / "artifact"
        artifact_root.mkdir()
        snapshot_path = Path(
            snapshot_downloader(
                repo_id=SOURCE_REPOSITORY,
                revision=SOURCE_REVISION,
                cache_dir=str(artifact_root),
                local_files_only=False,
            )
        ).resolve()
        if snapshot_path.name != SOURCE_REVISION:
            raise RuntimeError(
                f"Resolved source revision {snapshot_path.name!r} does not match pinned revision {SOURCE_REVISION!r}"
            )

        cache_repository = artifact_root / f"models--{SOURCE_REPOSITORY.replace('/', '--')}"
        if not snapshot_path.is_relative_to(cache_repository.resolve()):
            raise RuntimeError(f"Downloaded snapshot is outside the expected FastEmbed cache: {snapshot_path}")

        refs_dir = cache_repository / "refs"
        refs_dir.mkdir(parents=True, exist_ok=True)
        # huggingface_hub treats the entire refs/main content as the revision;
        # a trailing newline makes an otherwise complete cache undiscoverable.
        (refs_dir / "main").write_text(SOURCE_REVISION, encoding="utf-8")

        files = _inventory(artifact_root)
        required_names = {"config.json", "model_optimized.onnx", "tokenizer.json"}
        present_names = {Path(str(item["path"])).name for item in files}
        missing = sorted(required_names - present_names)
        if missing:
            raise RuntimeError(f"Downloaded snapshot is missing required runtime files: {', '.join(missing)}")

        manifest = {
            "schema_version": SCHEMA_VERSION,
            "model": {
                "name": MODEL_NAME,
                "embedding_dimension": EMBEDDING_DIMENSION,
                "fastembed_version": FASTEMBED_VERSION,
            },
            "source": {
                "repository": SOURCE_REPOSITORY,
                "revision": SOURCE_REVISION,
            },
            "cache_layout": "huggingface-hub",
            "files": files,
        }
        manifest_path = artifact_root / MANIFEST_NAME
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        manifest_output_path.write_text(manifest_path.read_text(encoding="utf-8"), encoding="utf-8")
        manifest_digest = sha256_file(manifest_path)
        (artifact_root / READY_MARKER).write_text(
            json.dumps({"manifest_sha256": manifest_digest}, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        temporary_archive = output_dir / f".{archive_name}.tmp"
        try:
            create_deterministic_archive(artifact_root, temporary_archive)
            os.replace(temporary_archive, archive_path)
        finally:
            temporary_archive.unlink(missing_ok=True)

    checksum_path.write_text(f"{sha256_file(archive_path)}  {archive_path.name}\n", encoding="utf-8")
    return archive_path, checksum_path, manifest_output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for the archive and checksum")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    archive, checksum, manifest = build_artifact(args.output_dir)
    print(json.dumps({"archive": str(archive), "checksum": str(checksum), "manifest": str(manifest)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
