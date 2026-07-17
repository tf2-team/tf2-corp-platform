#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Build the immutable Hugging Face cache artifact consumed by the EKS init container."""

import argparse
import hashlib
import json
import os
import tarfile
from pathlib import Path

MODEL_ID = "protectai/deberta-v3-base-prompt-injection-v2"
MODEL_REVISION = "89b085cd330414d3e7d9dd787870f315957e1e9f"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _portable_linkname(linkname: str) -> str:
    """Return a tar link target that can be resolved by Linux extractors."""
    return linkname.replace("\\", "/")


def create_archive(cache: Path, archive: Path) -> None:
    """Package a Hugging Face cache without leaking host path semantics."""
    with tarfile.open(archive, "w:gz") as bundle:
        for item in cache.rglob("*"):
            archive_name = item.relative_to(cache).as_posix()
            info = bundle.gettarinfo(str(item), arcname=archive_name)

            # Hugging Face snapshots link back to files in blobs/. When the
            # cache is built on Windows, those targets contain backslashes.
            # BusyBox/Linux preserves the backslashes literally and creates
            # broken links, so store all tar link targets in POSIX form.
            if info.issym() or info.islnk():
                info.linkname = _portable_linkname(info.linkname)

            if info.isfile():
                with item.open("rb") as stream:
                    bundle.addfile(info, stream)
            else:
                bundle.addfile(info)


def validate_runtime_model() -> None:
    """Load the exact scanner used by the service; propagate any loader failure."""
    from llm_guard.input_scanners import PromptInjection

    PromptInjection(threshold=0.5)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("dist/ai-model"))
    args = parser.parse_args()

    output = args.output.resolve()
    cache = output / "huggingface"
    output.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(cache)

    from huggingface_hub import snapshot_download

    snapshot_download(
        repo_id=MODEL_ID,
        revision=MODEL_REVISION,
        cache_dir=cache / "hub",
    )

    # LLM Guard loads by repo ID (without a revision argument). Pin its offline
    # `main` resolution to the reviewed commit rather than contacting the Hub.
    repo_cache = cache / "hub" / f"models--{MODEL_ID.replace('/', '--')}"
    refs = repo_cache / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    (refs / "main").write_text(MODEL_REVISION, encoding="ascii")

    # Validate the exact runtime loader before packaging the cache.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    validate_runtime_model()

    manifest = {
        "model_id": MODEL_ID,
        "revision": MODEL_REVISION,
        "cache_layout": "huggingface_hub",
    }
    (cache / ".model-ready").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")

    archive = output / "model.tar.gz"
    create_archive(cache, archive)

    checksum = sha256(archive)
    (output / "model.tar.gz.sha256").write_text(
        f"{checksum}  model.tar.gz\n", encoding="ascii", newline="\n"
    )
    (output / "manifest.json").write_text(
        json.dumps({**manifest, "sha256": checksum}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Built {archive} ({checksum})")


if __name__ == "__main__":
    main()
# Change trail: @hungxqt - 2026-07-16 - Add Apache-2.0 copyright headers for license-checker.
