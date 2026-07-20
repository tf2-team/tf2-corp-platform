#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import json
import sys
import tarfile
import tempfile
import unittest
from io import BytesIO
from pathlib import Path


MEM0_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MEM0_DIR))

from scripts import build_embedding_model_artifact as builder  # noqa: E402
from scripts import validate_embedding_model_artifact as validator  # noqa: E402


class EmbeddingArtifactTest(unittest.TestCase):
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

    def test_build_is_reproducible_and_validates_without_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_archive, first_checksum, first_manifest = builder.build_artifact(
                root / "first", snapshot_downloader=self.fake_snapshot_downloader
            )
            second_archive, _, _ = builder.build_artifact(
                root / "second", snapshot_downloader=self.fake_snapshot_downloader
            )

            self.assertEqual(builder.sha256_file(first_archive), builder.sha256_file(second_archive))
            manifest = validator.validate_artifact(first_archive, first_checksum, run_runtime=False)
            self.assertTrue(first_manifest.is_file())
            self.assertEqual(json.loads(first_manifest.read_text(encoding="utf-8")), manifest)
            self.assertEqual(manifest["model"]["embedding_dimension"], 384)
            self.assertEqual(manifest["source"]["revision"], builder.SOURCE_REVISION)
            extract = root / "inspect"
            extract.mkdir()
            validator._safe_extract(first_archive, extract)
            repository = extract / f"models--{builder.SOURCE_REPOSITORY.replace('/', '--')}"
            self.assertEqual((repository / "refs" / "main").read_text(encoding="utf-8"), builder.SOURCE_REVISION)

    def test_checksum_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive, checksum, _ = builder.build_artifact(
                Path(temporary), snapshot_downloader=self.fake_snapshot_downloader
            )
            checksum.write_text(f"{'0' * 64}  {archive.name}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                validator.verify_checksum(archive, checksum)

    def test_archive_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "unsafe.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                content = b"unsafe"
                info = tarfile.TarInfo("../outside")
                info.size = len(content)
                bundle.addfile(info, BytesIO(content))
            with self.assertRaisesRegex(ValueError, "Unsafe archive member"):
                validator._safe_extract(archive, Path(temporary) / "extract")

    def test_ready_marker_binds_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive, checksum, _ = builder.build_artifact(
                Path(temporary), snapshot_downloader=self.fake_snapshot_downloader
            )
            validator.verify_checksum(archive, checksum)
            extract = Path(temporary) / "extract"
            extract.mkdir()
            validator._safe_extract(archive, extract)
            marker = json.loads((extract / builder.READY_MARKER).read_text(encoding="utf-8"))
            self.assertEqual(marker["manifest_sha256"], builder.sha256_file(extract / builder.MANIFEST_NAME))

    def test_source_repository_matches_fastembed_model_catalog(self):
        try:
            from fastembed import TextEmbedding
        except ImportError:
            self.skipTest("fastembed is installed in the production image, not this local unit-test environment")

        model = next(item for item in TextEmbedding.list_supported_models() if item["model"] == builder.MODEL_NAME)
        self.assertEqual(model["sources"]["hf"], builder.SOURCE_REPOSITORY)


if __name__ == "__main__":
    unittest.main()
