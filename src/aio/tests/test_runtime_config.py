import json
import re
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from aiops.config import build_detectors, load_runtime_config
from aiops.config import Settings
from aiops.schemas import RuntimeConfig


class RuntimeConfigTest(unittest.TestCase):
    def test_loads_runtime_json_and_builds_detectors(self):
        config = load_runtime_config(Path("config/runtime.json"))
        detectors = build_detectors(config, Settings())

        self.assertEqual(config.topology.services[0].name, "checkout")
        self.assertEqual([detector.__class__.__name__ for detector in detectors], ["ThresholdDetector", "NoDataDetector", "DependencyDetector"])

    def test_rejects_detector_with_unknown_signal(self):
        config = json.loads(Path("config/runtime.json").read_text(encoding="utf-8"))
        config["detectors"][0]["signal_id"] = "missing_signal"

        with self.assertRaises(ValidationError):
            RuntimeConfig.model_validate(config)

    def test_api_markdown_json_schemas_are_parseable(self):
        text = Path("docs/các API cần kết nối.md").read_text(encoding="utf-8")
        blocks = re.findall(r"```json[^\n]*\n(.*?)\n```", text, re.S)

        self.assertEqual(len(blocks), 18)
        for block in blocks:
            schema = json.loads(block)
            self.assertIn("$schema", schema)
            self.assertIn("$id", schema)
            self.assertEqual(schema.get("type"), "object")
            self.assertIsInstance(schema.get("required", []), list)


if __name__ == "__main__":
    unittest.main()
