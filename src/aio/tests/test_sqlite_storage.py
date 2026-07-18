import tempfile
import unittest
from pathlib import Path

from aiops.detectors import ThresholdDetector
from aiops.features import FeatureBuilder
from aiops.schemas import Observation, SignalQuality
from aiops.storage import SQLiteIncidentStore


def candidate(value: float):
    detector = ThresholdDetector(
        detector_id="ops01_checkout_slo",
        signal_id="checkout_bad_ratio_24h",
        threshold=0.01,
        flow="checkout",
        service="checkout",
        severity="SEV1",
        runbook_id="RB-CHECKOUT-SLO",
    )
    features = FeatureBuilder().build(
        [Observation(signal_id="checkout_bad_ratio_24h", value=value, unit="ratio", window="24h", quality=SignalQuality.VERIFIED)]
    )
    return detector.evaluate(features)[0]


class SQLiteIncidentStoreTest(unittest.TestCase):
    def test_persists_and_deduplicates_incidents(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "aiops.sqlite3"
            first_store = SQLiteIncidentStore(db_path, environment="tf2")
            incident = first_store.upsert(candidate(0.02))
            first_store.close()

            second_store = SQLiteIncidentStore(db_path, environment="tf2")
            same_incident = second_store.upsert(candidate(0.03))
            incidents = second_store.list_incidents()
            second_store.close()

        self.assertEqual(incident.incident_id, same_incident.incident_id)
        self.assertEqual(same_incident.occurrence_count, 2)
        self.assertEqual(len(same_incident.events), 2)
        self.assertEqual(len(incidents), 1)


if __name__ == "__main__":
    unittest.main()
