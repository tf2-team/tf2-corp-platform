import json
import tempfile
import unittest
from pathlib import Path

from evaluate.e2e_pipeline import load_labels, score_report, validation_summary


class LabeledEvaluationTest(unittest.TestCase):
    def test_labels_are_explicit_and_not_inferred(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "labels.json"
            path.write_text(json.dumps({"cases": {"incident/one": {"expected_incident": True}}}), encoding="utf-8")

            self.assertIn("incident/one", load_labels(path))

        with self.assertRaises(FileNotFoundError):
            load_labels(Path("missing-labels.json"))

    def test_validation_requires_incident_normal_and_timing(self):
        cases = [
            {"expected_incident": True, "predicted_incident": True, "lead_time_seconds": 30},
            {"expected_incident": False, "predicted_incident": False, "lead_time_seconds": None},
        ]

        self.assertTrue(validation_summary(cases)["valid"])

        cases[0]["lead_time_seconds"] = None
        result = validation_summary(cases)
        self.assertFalse(result["valid"])
        self.assertIn("detected_incidents_missing_timing_labels", result["reasons"])

    def test_score_report_counts_normal_false_positives_and_lead_time(self):
        cases = [
            {
                "expected_incident": True,
                "predicted_incident": True,
                "lead_time_seconds": 20,
                "expected_root_causes": ["payment"],
                "predicted_root_services": ["payment"],
                "rca_top_k_hit": True,
            },
            {
                "expected_incident": False,
                "predicted_incident": True,
                "lead_time_seconds": None,
                "expected_root_causes": [],
                "predicted_root_services": [],
                "rca_top_k_hit": False,
            },
        ]

        report = score_report(cases)

        self.assertEqual(report["incident"]["tp"], 1)
        self.assertEqual(report["incident"]["fp"], 1)
        self.assertEqual(report["incident"]["precision"], 0.5)
        self.assertEqual(report["lead_time"]["mean_seconds"], 20)


if __name__ == "__main__":
    unittest.main()
