#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import re
import unittest
from pathlib import Path


MEM0_DIR = Path(__file__).resolve().parents[1]
DOCKERFILE = (MEM0_DIR / "Dockerfile").read_text(encoding="utf-8")
REQUIREMENTS = (MEM0_DIR / "requirements-production.txt").read_text(encoding="utf-8")


class ProductionImageContractTest(unittest.TestCase):
    def test_installs_mem0_from_pinned_submodule_source(self):
        self.assertIn("COPY third-party/mem0 /build/mem0", DOCKERFILE)
        self.assertIn("--no-deps /build/mem0", DOCKERFILE)
        self.assertNotRegex(REQUIREMENTS, r"(?m)^mem0ai(?:[<>=]|$)")

    def test_uvicorn_is_production_mode(self):
        command = next(line for line in DOCKERFILE.splitlines() if line.startswith("CMD "))
        self.assertIn('"uvicorn"', command)
        self.assertNotIn("--reload", command)

    def test_runtime_is_non_root(self):
        self.assertRegex(DOCKERFILE, r"(?m)^USER \$\{APP_UID\}:\$\{APP_GID\}$")
        self.assertNotRegex(DOCKERFILE, r"(?m)^USER (?:0|root)(?::(?:0|root))?$")

    def test_writable_paths_have_explicit_runtime_contracts(self):
        self.assertIn("HOME=/tmp", DOCKERFILE)
        self.assertIn("TMPDIR=/tmp", DOCKERFILE)
        self.assertIn("MEM0_DIR=/tmp/.mem0", DOCKERFILE)
        self.assertIn("HISTORY_DB_PATH=/app/history/history.db", DOCKERFILE)
        self.assertIn("FASTEMBED_CACHE_PATH=/models/fastembed", DOCKERFILE)

    def test_model_is_not_copied_into_application_image(self):
        copy_lines = [line.strip() for line in DOCKERFILE.splitlines() if line.strip().startswith("COPY ")]
        self.assertFalse(any(re.search(r"(?:^|[ /])models?(?:[ /]|$)", line) for line in copy_lines))

    def test_psycopg_includes_binary_backend_for_slim_runtime(self):
        # pure psycopg needs system libpq; slim-bookworm does not ship it.
        self.assertRegex(REQUIREMENTS, r"(?m)^psycopg\[binary\]==")
        self.assertIn("slim-bookworm", DOCKERFILE)


if __name__ == "__main__":
    unittest.main()
# Change trail: @hungxqt - 2026-07-18 - Assert mem0 production image pins psycopg[binary].

