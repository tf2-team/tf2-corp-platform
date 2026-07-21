"""Integration tests for the eval JSONL loader.

These tests use real temporary JSONL files and the real JSON Schema.
"""

import json
import tempfile
import unittest
from pathlib import Path

from harness.loader import load_dataset


def _summary_case() -> dict:
    return {
        "case_id": "summary_grounded_001",
        "surface": "summary",
        "input": {
            "product_id": "HEADPHONE_01",
            "question": "How long does the battery last?",
            "mock_reviews": ["Battery lasts 30 hours."],
        },
        "labels": {
            "case_type": "grounded",
            "expected_behavior": "answer",
            "expected_status": "GROUNDED",
        },
    }


def _copilot_case() -> dict:
    return {
        "case_id": "copilot_search_001",
        "surface": "copilot",
        "input": {"user_message": "Show me headphones"},
        "labels": {
            "case_type": "search",
            "expected_behavior": "search_results",
            "expected_status": "GROUNDED",
        },
    }


class LoaderIntegrationTests(unittest.TestCase):
    def _write_jsonl(self, *cases: dict) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        dataset = Path(directory.name) / "cases.jsonl"
        dataset.write_text(
            "\n".join(json.dumps(case) for case in cases), encoding="utf-8"
        )
        return dataset

    def test_loads_valid_cases_and_filters_by_surface(self) -> None:
        dataset = self._write_jsonl(_summary_case(), _copilot_case())

        self.assertEqual(len(load_dataset(dataset)), 2)
        self.assertEqual(load_dataset(dataset, "summary")[0]["surface"], "summary")

    def test_reports_line_and_reason_for_schema_error(self) -> None:
        invalid_case = _summary_case()
        del invalid_case["input"]["question"]

        with self.assertRaisesRegex(ValueError, r"Line 1.*question"):
            load_dataset(self._write_jsonl(invalid_case))

    def test_reports_line_for_invalid_json(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        dataset = Path(directory.name) / "cases.jsonl"
        dataset.write_text('{"case_id": ', encoding="utf-8")

        with self.assertRaisesRegex(ValueError, r"Line 1: Invalid JSON"):
            load_dataset(dataset)


if __name__ == "__main__":
    unittest.main()
