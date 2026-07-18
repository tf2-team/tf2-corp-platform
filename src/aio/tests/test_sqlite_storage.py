import tempfile
import unittest
from pathlib import Path

from aiops.config import load_runtime_config
from aiops.detectors import ThresholdDetector
from aiops.features import FeatureBuilder
from aiops.schemas import CandidateEvent, Observation, SignalQuality, VerificationResult
from aiops.storage import SQLiteIncidentStore


def candidate(value: float, timestamp: int = 0):
    detector = ThresholdDetector(
        detector_id="ops01_checkout_slo",
        signal_id="checkout_bad_ratio_24h",
        threshold=0.01,
        flow="checkout",
        service="checkout",
        severity="SEV1",
        runbook_id="RB-CHECKOUT-SLO",
    )
    features = FeatureBuilder(load_runtime_config(Path("config/runtime.json"))).build(
        [Observation(signal_id="checkout_bad_ratio_24h", value=value, unit="ratio", window="24h", quality=SignalQuality.VERIFIED)]
    )
    return detector.evaluate(features)[0].model_copy(update={"timestamp": timestamp})


def service_candidate(service: str, detector_id: str) -> CandidateEvent:
    return CandidateEvent(
        detector_id=detector_id,
        timestamp=100,
        flow="checkout",
        service=service,
        severity="SEV2",
        signal_id=f"{service.replace('-', '_')}_error_rate_5m",
        value=0.2,
        unit="ratio",
        window="5m",
        threshold=0.05,
        quality=SignalQuality.VERIFIED,
        reason="threshold_breached",
        runbook_id="RB-CHECKOUT-SLO",
    )


class SQLiteIncidentStoreTest(unittest.TestCase):
    def test_persists_and_deduplicates_incidents(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "aiops.sqlite3"
            with self.assertLogs("aiops.storage.sqlite", level="DEBUG") as logs:
                first_store = SQLiteIncidentStore(db_path, environment="tf2")
                incident = first_store.upsert(candidate(0.02, timestamp=100))
                notifications = first_store.pending_notifications_for([incident])
                first_store.close()

                second_store = SQLiteIncidentStore(db_path, environment="tf2")
                same_incident = second_store.upsert(candidate(0.03, timestamp=200))
                duplicate_notifications = second_store.pending_notifications_for([same_incident])
                event_row = second_store._connection.execute(
                    "SELECT state, last_seen, recovered_at, cooldown_until FROM incident_events ORDER BY id DESC LIMIT 1"
                ).fetchone()
                outbox_count = second_store._connection.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0]
                incidents = second_store.list_incidents()
                second_store.close()

        self.assertEqual(incident.incident_id, same_incident.incident_id)
        text = "\n".join(logs.output)
        self.assertIn("AIOPS_INCIDENT_UPSERT action=created", text)
        self.assertIn("AIOPS_INCIDENT_UPSERT action=deduped", text)
        self.assertIn("notification_enqueued=False", text)
        self.assertEqual(notifications[0].incident_id, incident.incident_id)
        self.assertEqual(notifications[0].runbook_id, "RB-CHECKOUT-SLO")
        self.assertEqual(duplicate_notifications, [])
        self.assertEqual(outbox_count, 1)
        self.assertEqual(same_incident.occurrence_count, 2)
        self.assertEqual(len(same_incident.events), 2)
        self.assertEqual(len(incidents), 1)
        self.assertEqual(same_incident.state, "open")
        self.assertEqual(same_incident.last_seen, "1970-01-01T00:03:20+00:00")
        self.assertIsNone(same_incident.recovered_at)
        self.assertIsNone(same_incident.cooldown_until)
        self.assertEqual(event_row, ("open", "1970-01-01T00:03:20+00:00", None, None))

    def test_notification_outbox_retry_and_sent_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment="tf2")
            incident = store.upsert(candidate(0.02, timestamp=100))

            self.assertEqual([message.incident_id for message in store.due_notifications()], [incident.incident_id])
            store.mark_notification_failed(incident.incident_id, "receiver down")
            retry_row = store._connection.execute(
                "SELECT status, attempt_count, last_error FROM notification_outbox WHERE incident_id = ?",
                (incident.incident_id,),
            ).fetchone()
            store.mark_notification_sent(incident.incident_id)
            sent_row = store._connection.execute(
                "SELECT status FROM notification_outbox WHERE incident_id = ?",
                (incident.incident_id,),
            ).fetchone()
            store.close()

        self.assertEqual(retry_row, ("retry", 1, "receiver down"))
        self.assertEqual(sent_row, ("sent",))

    def test_recovered_incident_reopens_and_enqueues_a_new_notification(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment="tf2")
            first = store.upsert(candidate(0.02, timestamp=100))
            store.pending_notifications_for([first])
            store.apply_verification(
                [VerificationResult(incident_id=first.incident_id, status="recovered", reason="detector_no_longer_firing")]
            )

            recovered = store.list_incidents()[0]
            reopened = store.upsert(candidate(0.03, timestamp=300))
            notifications = store.pending_notifications_for([reopened])
            store.close()

        self.assertEqual(recovered.state, "recovered")
        self.assertIsNotNone(recovered.recovered_at)
        self.assertEqual(reopened.state, "open")
        self.assertIsNone(reopened.recovered_at)
        self.assertEqual(reopened.occurrence_count, 2)
        self.assertEqual([message.incident_id for message in notifications], [reopened.incident_id])

    def test_missing_canonical_runbook_is_rejected_before_incident_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment="tf2", runbooks_dir=Path(tmp) / "runbooks")

            with self.assertRaisesRegex(ValueError, "missing canonical runbook"):
                store.upsert(candidate(0.02, timestamp=100))

            count = store._connection.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
            store.close()

        self.assertEqual(count, 0)

    def test_active_root_cause_suppresses_child_notification(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment="tf2")
            store.register_active_root_cause("checkout", {"checkout", "cart"}, suppress_seconds=900)
            incident = store.upsert(service_candidate("cart", "auto_cart_error_rate"))
            notifications = store.pending_notifications_for([incident])
            status = store._connection.execute("SELECT status FROM notification_outbox WHERE incident_id = ?", (incident.incident_id,)).fetchone()
            store.close()

        self.assertEqual(notifications, [])
        self.assertIsNone(status)


if __name__ == "__main__":
    unittest.main()
