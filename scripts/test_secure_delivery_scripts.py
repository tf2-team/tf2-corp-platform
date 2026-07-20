#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import unittest

from update_chart_service_digests import render


class DigestOverlayTests(unittest.TestCase):
    digest = "sha256:" + "a" * 64

    def test_regular_component(self) -> None:
        self.assertIn("components:\n  ad:\n    imageOverride:", render("ad", self.digest))

    def test_mem0_top_level_image(self) -> None:
        self.assertIn("mem0:\n  image:\n    digest:", render("mem0", self.digest))

    def test_load_generator_updates_worker_alias(self) -> None:
        overlay = render("load-generator", self.digest)
        self.assertIn("  load-generator:", overlay)
        self.assertIn("  load-generator-worker:", overlay)

    def test_flagd_ui_uses_non_destructive_sidecar_map(self) -> None:
        overlay = render("flagd-ui", self.digest)
        self.assertIn("components:\n  flagd:\n    sidecarImageDigests:", overlay)
        self.assertNotIn("sidecarContainers:", overlay)


if __name__ == "__main__":
    unittest.main()
