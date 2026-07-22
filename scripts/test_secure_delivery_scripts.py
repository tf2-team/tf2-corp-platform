#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import json
import tempfile
import unittest
from pathlib import Path

from update_chart_service_digests import render, resolve_output_dir, main as update_main
import update_chart_service_digests as digest_mod


class DigestOverlayTests(unittest.TestCase):
    digest = "sha256:" + "a" * 64

    def test_regular_component(self) -> None:
        self.assertIn("components:\n  ad:\n    imageOverride:", render("ad", self.digest))
        self.assertIn(f'digest: "{self.digest}"', render("ad", self.digest))

    def test_mem0_top_level_image(self) -> None:
        self.assertIn("mem0:\n  image:\n    digest:", render("mem0", self.digest))

    def test_aiops_top_level_image_keeps_runtime_contract(self) -> None:
        overlay = render("aiops", self.digest)
        self.assertIn("aiops:\n  enabled: true", overlay)
        self.assertIn("existingSecret: techx-corp-aiops-grafana-webhook", overlay)
        self.assertIn("  image:\n    digest:", overlay)

    def test_load_generator_updates_worker_alias(self) -> None:
        overlay = render("load-generator", self.digest)
        self.assertIn("  load-generator:", overlay)
        self.assertIn("  load-generator-worker:", overlay)

    def test_flagd_ui_uses_non_destructive_sidecar_map(self) -> None:
        overlay = render("flagd-ui", self.digest)
        self.assertIn("components:\n  flagd:\n    sidecarImageDigests:", overlay)
        self.assertNotIn("sidecarContainers:", overlay)

    def test_resolve_output_dir_appends_service_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = resolve_output_dir(root, "service-digest")
            self.assertEqual(out, root / "service-digest")

    def test_resolve_output_dir_when_already_service_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sd = Path(tmp) / "service-digest"
            sd.mkdir()
            out = resolve_output_dir(sd, "service-digest")
            self.assertEqual(out, sd.resolve())

    def test_writes_under_service_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            services = json.dumps(["ad"])
            digests = json.dumps({"ad": self.digest})
            # Simulate CLI argv
            import sys

            argv = sys.argv
            try:
                sys.argv = [
                    "update_chart_service_digests.py",
                    "--directory",
                    str(root),
                    "--services-json",
                    services,
                    "--digests-json",
                    digests,
                ]
                digest_mod.main()
            finally:
                sys.argv = argv
            path = root / "service-digest" / "values-ad.yaml"
            self.assertTrue(path.is_file())
            self.assertIn(self.digest, path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
# Change trail: @hungxqt - 2026-07-20 - Cover service-digest output path for chart promote script.
