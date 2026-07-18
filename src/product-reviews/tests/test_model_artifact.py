#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest


sys.path.append(os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from scripts.build_model_artifact import create_archive, sha256, validate_runtime_model


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


def test_archive_checksum_changes_with_artifact_content(tmp_path: Path):
    artifact = tmp_path / "model.tar.gz"
    artifact.write_bytes(b"first model artifact")
    first_checksum = sha256(artifact)

    artifact.write_bytes(b"second model artifact")

    assert sha256(artifact) != first_checksum


def test_runtime_validation_uses_the_production_scanner(monkeypatch):
    import llm_guard.input_scanners

    thresholds = []

    def fake_scanner(*, threshold):
        thresholds.append(threshold)

    monkeypatch.setattr(llm_guard.input_scanners, "PromptInjection", fake_scanner)

    validate_runtime_model()

    assert thresholds == [0.5]


def test_runtime_validation_propagates_model_loader_failure(monkeypatch):
    import llm_guard.input_scanners

    def broken_scanner(*, threshold):
        raise OSError(f"model files are corrupt at threshold {threshold}")

    monkeypatch.setattr(llm_guard.input_scanners, "PromptInjection", broken_scanner)

    with pytest.raises(OSError, match="model files are corrupt"):
        validate_runtime_model()


def test_strict_offline_startup_rejects_an_empty_model_cache(tmp_path: Path):
    empty_cache = tmp_path / "empty-huggingface-cache"
    empty_cache.mkdir()
    service_dir = Path(__file__).resolve().parent.parent
    environment = {
        **os.environ,
        "HF_HOME": str(empty_cache),
        "HUGGINGFACE_HUB_CACHE": str(empty_cache / "hub"),
        "TRANSFORMERS_CACHE": str(empty_cache / "transformers"),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "AI_GUARDRAIL_REQUIRE_MODEL": "true",
        "PYTHONPATH": str(service_dir),
    }

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import guardrails; guardrails.initialize_guardrails()",
        ],
        cwd=service_dir,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode != 0
    assert "Required prompt-injection model failed to load" in result.stderr
