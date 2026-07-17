#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
MEM0_SRC = REPO_ROOT / "src" / "mem0"
MEM0_SERVER = REPO_ROOT / "third-party" / "mem0" / "server"

DOCKERFILE = (MEM0_SRC / "Dockerfile").read_text(encoding="utf-8")
SERVER_MAIN = (MEM0_SERVER / "main.py").read_text(encoding="utf-8")
CLEANUP_SCRIPT = (MEM0_SERVER / "scripts" / "cleanup_expired_memories.py").read_text(encoding="utf-8")


class RuntimeContractTest(unittest.TestCase):
    def test_api_startup_does_not_run_migrations(self):
        command = next(line for line in DOCKERFILE.splitlines() if line.startswith("CMD "))
        self.assertIn('"uvicorn"', command)
        self.assertNotIn("alembic", command)
        self.assertTrue((MEM0_SERVER / "alembic.ini").exists())
        self.assertTrue((MEM0_SERVER / "alembic" / "versions").exists())

    def test_liveness_and_readiness_endpoints_are_distinct(self):
        self.assertIn('@app.get("/health/live"', SERVER_MAIN)
        self.assertIn('@app.get("/health/ready"', SERVER_MAIN)
        self.assertIn("def liveness", SERVER_MAIN)
        self.assertIn("def readiness", SERVER_MAIN)
        self.assertIn("_check_app_database()", SERVER_MAIN)
        self.assertIn("_check_memory_store()", SERVER_MAIN)
        self.assertRegex(SERVER_MAIN, r"HTTPException\(status_code=503")

    def test_health_endpoints_are_not_request_logged(self):
        skipped_paths = re.search(r"SKIPPED_REQUEST_LOG_PATHS = \{([^}]+)\}", SERVER_MAIN, re.DOTALL)
        self.assertIsNotNone(skipped_paths)
        self.assertIn('"/health/live"', skipped_paths.group(1))
        self.assertIn('"/health/ready"', skipped_paths.group(1))

    def test_expired_memory_cleanup_is_idempotent_delete(self):
        self.assertIn("def cleanup_expired_memories", CLEANUP_SCRIPT)
        self.assertIn("DELETE FROM {}", CLEANUP_SCRIPT)
        self.assertIn("payload ? 'expiration_date'", CLEANUP_SCRIPT)
        self.assertIn("payload->>'expiration_date' < %s", CLEANUP_SCRIPT)
        self.assertNotIn("TRUNCATE", CLEANUP_SCRIPT.upper())
        self.assertNotIn("DROP TABLE", CLEANUP_SCRIPT.upper())


if __name__ == "__main__":
    unittest.main()
