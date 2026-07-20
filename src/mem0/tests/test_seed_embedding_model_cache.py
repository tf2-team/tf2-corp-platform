#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import sys
import tempfile
import unittest
from pathlib import Path


MEM0_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MEM0_DIR))

from scripts import build_embedding_model_artifact as builder  # noqa: E402
from scripts import seed_embedding_model_cache as seed  # noqa: E402
from scripts import validate_embedding_model_artifact as validator  # noqa: E402


class SeedEmbeddingModelCacheTest(unittest.TestCase):
    @staticmethod
    def fake_snapshot_downloader(**kwargs):
        cache_dir = Path(kwargs["cache_dir"])
        repository = cache_dir / f"models--{builder.SOURCE_REPOSITORY.replace('/', '--')}"
        snapshot = repository / "snapshots" / builder.SOURCE_REVISION
        snapshot.mkdir(parents=True)
        (snapshot / "config.json").write_text("{}\n", encoding="utf-8")
        (snapshot / "tokenizer.json").write_text('{"version":"1.0"}\n', encoding="utf-8")
        (snapshot / "model_optimized.onnx").write_bytes(b"fake-onnx-model")
        return str(snapshot)

    def test_seed_populates_an_empty_cache_with_a_validated_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache_dir = root / "cache"

            def artifact_builder(output_dir: Path):
                return builder.build_artifact(output_dir, snapshot_downloader=self.fake_snapshot_downloader)

            seeded = seed.seed_cache(
                cache_dir,
                artifact_builder=artifact_builder,
                cache_validator=validator.validate_manifest,
            )

            self.assertTrue(seeded)
            self.assertTrue((cache_dir / builder.READY_MARKER).is_file())
            self.assertEqual(
                validator.validate_manifest(cache_dir)["model"]["embedding_dimension"],
                builder.EMBEDDING_DIMENSION,
            )

    def test_seed_reuses_an_already_valid_cache_without_building_again(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache_dir = root / "cache"

            def artifact_builder(output_dir: Path):
                return builder.build_artifact(output_dir, snapshot_downloader=self.fake_snapshot_downloader)

            seed.seed_cache(cache_dir, artifact_builder=artifact_builder, cache_validator=validator.validate_manifest)

            def should_not_build(_output_dir: Path):
                raise AssertionError("A valid cache must not be rebuilt")

            self.assertFalse(
                seed.seed_cache(cache_dir, artifact_builder=should_not_build, cache_validator=validator.validate_manifest)
            )


if __name__ == "__main__":
    unittest.main()
