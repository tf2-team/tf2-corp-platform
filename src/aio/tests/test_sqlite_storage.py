#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from aiops.config import load_runtime_config
from aiops.detectors import ThresholdDetector
from aiops.features import FeatureBuilder
from aiops.schemas import CandidateEvent, Observation, SignalQuality
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
        self.assertIn("AIOPS_NOTIFY_ENQUEUED_READY", text)
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
        self.assertIsNotNone(same_incident.cooldown_until)
        self.assertEqual(event_row[:3], ("open", "1970-01-01T00:03:20+00:00", None))
        self.assertIsNotNone(event_row[3])

    def test_deduped_incident_requeues_notification_after_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment="tf2", slo_dedup_seconds=0)
            incident = store.upsert(candidate(0.02, timestamp=100))
            store.mark_notification_sent(incident.incident_id)

            repeated = store.upsert(candidate(0.03, timestamp=200))
            notifications = store.pending_notifications_for([repeated])
            outbox_row = store._connection.execute(
                "SELECT status FROM notification_outbox WHERE incident_id = ?",
                (incident.incident_id,),
            ).fetchone()
            store.close()

        self.assertEqual(incident.incident_id, repeated.incident_id)
        self.assertEqual([message.incident_id for message in notifications], [incident.incident_id])
        self.assertEqual(outbox_row, ("pending",))

    def test_slo_incident_requeues_after_dedup_ttl(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment="tf2", slo_dedup_seconds=0)
            incident = store.upsert(service_candidate("product-reviews", "auto_product_reviews_error_rate").model_copy(update={"signal_id": "product_reviews_error_ratio_5m"}))
            store.mark_notification_sent(incident.incident_id)

            repeated = store.upsert(service_candidate("product-reviews", "auto_product_reviews_error_rate").model_copy(update={"signal_id": "product_reviews_error_ratio_5m"}))
            notifications = store.pending_notifications_for([repeated])
            service_cooldowns = store._connection.execute("SELECT COUNT(*) FROM notification_service_cooldowns").fetchone()[0]
            store.close()

        self.assertEqual(incident.incident_id, repeated.incident_id)
        self.assertEqual([message.incident_id for message in notifications], [incident.incident_id])
        self.assertEqual(service_cooldowns, 1)

    def test_repeated_incident_does_not_reset_notification_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment="tf2", notification_cooldown_seconds=900)
            incident = store.upsert(candidate(0.02, timestamp=100))
            first_cooldown = incident.cooldown_until

            repeated = store.upsert(candidate(0.03, timestamp=200))
            store.close()

        self.assertEqual(repeated.cooldown_until, first_cooldown)

    def test_deduped_incident_count_resets_after_count_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment="tf2", incident_count_reset_seconds=50)
            incident = store.upsert(candidate(0.02, timestamp=100))
            repeated = store.upsert(candidate(0.03, timestamp=120))
            reset = store.upsert(candidate(0.04, timestamp=200))
            store.close()

        self.assertEqual(incident.incident_id, repeated.incident_id)
        self.assertEqual(repeated.occurrence_count, 2)
        self.assertEqual(reset.incident_id, incident.incident_id)
        self.assertEqual(reset.occurrence_count, 1)
        self.assertEqual(len(reset.events), 1)

    def test_slo_notification_bypasses_service_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment="tf2", notification_cooldown_seconds=900)
            first = store.upsert(
                service_candidate("product-reviews", "auto_product_reviews_requests").model_copy(update={"signal_id": "product_reviews_request_count_5m"})
            )
            second = store.upsert(service_candidate("product-reviews", "auto_product_reviews_error_rate").model_copy(update={"signal_id": "product_reviews_error_ratio_5m"}))
            notifications = store.pending_notifications_for([first, second])
            outbox_rows = store._connection.execute("SELECT incident_id FROM notification_outbox ORDER BY incident_id").fetchall()
            store.close()

        self.assertNotEqual(first.incident_id, second.incident_id)
        self.assertEqual({message.incident_id for message in notifications}, {first.incident_id, second.incident_id})
        self.assertEqual(set(outbox_rows), {(first.incident_id,), (second.incident_id,)})

    def test_slo_notification_bypass_is_deduped_by_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment="tf2", slo_dedup_seconds=900)
            first = store.upsert(
                service_candidate("product-reviews", "auto_product_reviews_latency").model_copy(update={"signal_id": "product_reviews_latency_5m"})
            )
            second = store.upsert(service_candidate("product-reviews", "auto_product_reviews_error_rate").model_copy(update={"signal_id": "product_reviews_error_ratio_5m"}))
            notifications = store.pending_notifications_for([first, second])
            outbox_rows = store._connection.execute("SELECT incident_id FROM notification_outbox ORDER BY incident_id").fetchall()
            cooldown_rows = store._connection.execute("SELECT service FROM notification_service_cooldowns").fetchall()
            store.close()

        self.assertNotEqual(first.incident_id, second.incident_id)
        self.assertEqual([message.incident_id for message in notifications], [first.incident_id])
        self.assertEqual(outbox_rows, [(first.incident_id,)])
        self.assertEqual(cooldown_rows, [("slo:product-reviews",)])

    def test_rca_notification_uses_separate_service_dedup(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment="tf2", slo_dedup_seconds=900, rca_dedup_seconds=900)
            slo = store.upsert(
                service_candidate("product-reviews", "auto_product_reviews_latency").model_copy(update={"signal_id": "product_reviews_latency_5m"})
            )
            rca = store.upsert(
                service_candidate("product-reviews", "rca_root_cause").model_copy(update={"signal_id": "cpu_millicores", "reason": "rca_root_cause"})
            )
            repeat_rca = store.upsert(
                service_candidate("product-reviews", "rca_root_cause").model_copy(update={"signal_id": "memory_usage", "reason": "rca_root_cause"})
            )
            notifications = store.pending_notifications_for([slo, rca, repeat_rca])
            cooldown_rows = store._connection.execute("SELECT service FROM notification_service_cooldowns ORDER BY service").fetchall()
            store.close()

        self.assertEqual({message.incident_id for message in notifications}, {slo.incident_id, rca.incident_id})
        self.assertEqual(cooldown_rows, [("rca:product-reviews",), ("slo:product-reviews",)])

    def test_sev1_bypasses_same_service_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment="tf2", notification_cooldown_seconds=900)
            first = store.upsert(
                service_candidate("product-reviews", "auto_product_reviews_requests").model_copy(update={"signal_id": "product_reviews_request_count_5m"})
            )
            sev1 = service_candidate("product-reviews", "auto_product_reviews_requests").model_copy(
                update={"severity": "SEV1", "signal_id": "product_reviews_request_count_5m"}
            )
            second = store.upsert(sev1)
            notifications = store.pending_notifications_for([first, second])
            store.close()

        self.assertEqual({message.incident_id for message in notifications}, {first.incident_id, second.incident_id})

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
            incident = store.upsert(service_candidate("cart", "auto_cart_error_rate").model_copy(update={"severity": "SEV1"}))
            suppressed = store.suppress_active_root_notifications([incident])
            notifications = store.pending_notifications_for([incident])
            status = store._connection.execute("SELECT status FROM notification_outbox WHERE incident_id = ?", (incident.incident_id,)).fetchone()
            store.close()

        self.assertEqual(suppressed, {incident.incident_id})
        self.assertEqual(notifications, [])
        self.assertEqual(status, ("suppressed",))

    def test_repeated_active_root_cause_does_not_extend_suppression_ttl(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", environment="tf2")
            store.register_active_root_cause("checkout", {"checkout", "cart"}, suppress_seconds=900)
            fixed_expiry = (datetime.now(UTC) + timedelta(seconds=300)).isoformat()
            store._connection.execute(
                "UPDATE active_root_causes SET expires_at = ? WHERE root_service = ?",
                (fixed_expiry, "checkout"),
            )

            store.register_active_root_cause("checkout", {"checkout", "cart", "payment"}, suppress_seconds=900)
            row = store._connection.execute(
                "SELECT affected_services_json, expires_at FROM active_root_causes WHERE root_service = ?",
                ("checkout",),
            ).fetchone()
            store.close()

        self.assertEqual(set(json.loads(row[0])), {"checkout", "cart", "payment"})
        self.assertEqual(row[1], fixed_expiry)


if __name__ == "__main__":
    unittest.main()
