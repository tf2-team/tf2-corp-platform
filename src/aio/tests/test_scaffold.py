import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from aiops.main import run
from scripts.check_runtime_imports import main as check_runtime_imports
from scripts.validate_config import validate


SERVICE_ROOT = Path(__file__).resolve().parents[1]


class ScaffoldTest(unittest.TestCase):
    def test_configuration_scaffold_is_complete_and_safe(self):
        self.assertEqual(validate(), [])

    def test_runtime_does_not_import_tests_or_planning_docs(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(check_runtime_imports(), 0)

    def test_entry_point_is_importable(self):
        self.assertTrue(callable(run))

    def test_container_is_digest_pinned_and_excludes_non_runtime_assets(self):
        dockerfile = (SERVICE_ROOT / "Dockerfile").read_text(encoding="utf-8")
        dockerignore = (SERVICE_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

        self.assertIn("python:3.12.10-slim-bookworm@sha256:", dockerfile)
        self.assertIn("USER 10001:10001", dockerfile)
        self.assertIn("tests", dockerignore)
        self.assertIn("docs", dockerignore)
        self.assertIn(".env", dockerignore)

    def test_canonical_p0_runbooks_exist(self):
        expected = {
            "RB-CHECKOUT-SLO.md",
            "RB-CHECKOUT-DEPENDENCY.md",
            "RB-DB-SATURATION.md",
            "RB-MONITORING-LOSS.md",
        }
        runbook_root = SERVICE_ROOT / "runbooks"

        self.assertEqual({path.name for path in runbook_root.glob("*.md")}, expected)
        for name in expected:
            text = (runbook_root / name).read_text(encoding="utf-8")
            self.assertIn("## Preconditions and signal quality", text)
            self.assertIn("## Evidence to collect", text)
            self.assertIn("## Prohibited actions", text)
            self.assertIn("## Verification", text)
            self.assertIn("## Rollback and escalation", text)


if __name__ == "__main__":
    unittest.main()
