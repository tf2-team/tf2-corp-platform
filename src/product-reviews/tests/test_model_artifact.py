#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import os
import sys
import tarfile
from pathlib import Path

import pytest


sys.path.append(os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from scripts.build_model_artifact import create_archive, _portable_linkname


def test_portable_linkname_normalizes_windows_separators():
    assert _portable_linkname(r"..\..\blobs\digest") == "../../blobs/digest"


def test_archive_round_trip_preserves_hugging_face_snapshot_links(tmp_path: Path):
    cache = tmp_path / "huggingface"
    repo = cache / "hub" / "models--protectai--example"
    blob = repo / "blobs" / "digest"
    config = repo / "snapshots" / "revision" / "config.json"
    blob.parent.mkdir(parents=True)
    config.parent.mkdir(parents=True)
    blob.write_text('{"model_type": "deberta-v2"}', encoding="utf-8")

    try:
        config.symlink_to(r"..\..\blobs\digest")
    except OSError as error:
        pytest.skip(f"Creating symlinks is not supported in this environment: {error}")

    archive = tmp_path / "model.tar.gz"
    create_archive(cache, archive)

    with tarfile.open(archive, "r:gz") as bundle:
        member = bundle.getmember(
            "hub/models--protectai--example/snapshots/revision/config.json"
        )
        assert member.issym()
        assert member.linkname == "../../blobs/digest"
        bundle.extractall(tmp_path / "extracted", filter="data")

    extracted_config = (
        tmp_path
        / "extracted"
        / "hub"
        / "models--protectai--example"
        / "snapshots"
        / "revision"
        / "config.json"
    )
    assert extracted_config.read_text(encoding="utf-8") == '{"model_type": "deberta-v2"}'
