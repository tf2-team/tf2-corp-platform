import csv
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evaluate"))

from incident_labels import label_for_case, load_label_sheet, validate_dataset_coverage


FIELDS = ["case_id", "expected_incident", "expected_root_service", "expected_root_metric", "expected_action"]


def write_labels(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


class IncidentLabelsTest(unittest.TestCase):
    def test_loads_optional_metric_and_action(self):
        with TemporaryDirectory(dir=ROOT / ".test-tmp") as tmp:
            path = Path(tmp) / "labels.csv"
            write_labels(path, [{"case_id": "RE2-SS/payment_delay/1", "expected_incident": "true",
                                 "expected_root_service": "payment", "expected_root_metric": "latency",
                                 "expected_action": "restart_payment"}])
            label = load_label_sheet(path)["RE2-SS/payment_delay/1"]
        self.assertTrue(label.expected_incident)
        self.assertEqual(label.expected_root_service, "payment")
        self.assertEqual(label.expected_root_metric, "latency")
        self.assertEqual(label.expected_action, "restart_payment")

    def test_rejects_duplicate_case_id(self):
        with TemporaryDirectory(dir=ROOT / ".test-tmp") as tmp:
            path = Path(tmp) / "labels.csv"
            row = {"case_id": "RE2-SS/payment_delay/1", "expected_incident": "true",
                   "expected_root_service": "payment", "expected_root_metric": "latency", "expected_action": ""}
            write_labels(path, [row, row])
            with self.assertRaisesRegex(ValueError, "duplicate case_id"):
                load_label_sheet(path)

    def test_rejects_incident_without_root_service(self):
        with TemporaryDirectory(dir=ROOT / ".test-tmp") as tmp:
            path = Path(tmp) / "labels.csv"
            write_labels(path, [{"case_id": "RE2-SS/unknown/1", "expected_incident": "true",
                                 "expected_root_service": "", "expected_root_metric": "", "expected_action": ""}])
            with self.assertRaisesRegex(ValueError, "requires expected_root_service"):
                load_label_sheet(path)

    def test_coverage_rejects_missing_dataset_case(self):
        with TemporaryDirectory(dir=ROOT / ".test-tmp") as tmp:
            dataset = Path(tmp) / "dataset"
            case = dataset / "RE2-SS" / "payment_delay" / "1"
            case.mkdir(parents=True)
            (case / "simple_metrics.csv").write_text("time,payment_latency\n0,1\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing labels"):
                validate_dataset_coverage(dataset, {})

    def test_label_lookup_normalizes_case_path(self):
        with TemporaryDirectory(dir=ROOT / ".test-tmp") as tmp:
            dataset = Path(tmp) / "dataset"
            case = dataset / "RE2-SS" / "payment_delay" / "1"
            case.mkdir(parents=True)
            path = Path(tmp) / "labels.csv"
            write_labels(path, [{"case_id": "RE2-SS/payment_delay/1", "expected_incident": "true",
                                 "expected_root_service": "payment", "expected_root_metric": "latency",
                                 "expected_action": ""}])
            label = label_for_case(case, dataset, load_label_sheet(path))
        self.assertEqual(label.case_id, "RE2-SS/payment_delay/1")


if __name__ == "__main__":
    unittest.main()
