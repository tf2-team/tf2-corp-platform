#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from aiops.cli import format_incidents, load_incidents_for_cli
from aiops.schemas import CandidateEvent, Incident, SignalQuality
from aiops.storage import SQLiteIncidentStore


class CliTest(unittest.TestCase):
    def test_formats_incidents_for_terminal(self):
        text = format_incidents(
            [
                Incident(
                    incident_id="inc-1",
                    fingerprint="sha256:abc",
                    state="open",
                    last_seen="2026-07-17T00:00:00+00:00",
                    severity="SEV1",
                    flow="checkout",
                    service="checkout",
                    likely_dependency="payment",
                    events=[
                        CandidateEvent(
                            detector_id="ops03_checkout_payment_dependency",
                            flow="checkout",
                            service="checkout",
                            severity="SEV1",
                            signal_id="checkout_payment_error_rate_5m",
                            value=0.2,
                            unit="ratio",
                            window="5m",
                            threshold=0.05,
                            quality=SignalQuality.VERIFIED,
                            reason="dependency_signal_breached",
                            runbook_id="RB-CHECKOUT-DEPENDENCY",
                            likely_dependency="payment",
                        )
                    ],
                )
            ]
        )

        self.assertIn("incident_id", text)
        self.assertIn("inc-1", text)
        self.assertIn("dependency_signal_breached", text)

    def test_formats_empty_incidents(self):
        self.assertEqual(format_incidents([]), "No incidents.")

    def test_formats_only_deduped_incidents(self):
        first = Incident(
            incident_id="inc-1",
            fingerprint="sha256:same",
            state="open",
            severity="SEV1",
            flow="checkout",
            service="checkout",
            likely_dependency="payment",
            occurrence_count=1,
        )
        second = first.model_copy(update={"occurrence_count": 2})

        text = format_incidents([first, second])

        self.assertEqual(text.count("inc-1"), 1)
        self.assertIn("2", text)

    def test_cli_skips_legacy_invalid_rows(self):
        with TemporaryDirectory() as tmp:
            store = SQLiteIncidentStore(Path(tmp) / "aiops.sqlite3", "test")
            with store._connection:
                store._connection.execute(
                    "INSERT INTO incidents (fingerprint, incident_json) VALUES (?, ?)",
                    ("sha256:bad", '{"events":[{}]}'),
                )
            incidents = load_incidents_for_cli(store)
            store.close()

        self.assertEqual(incidents, [])


if __name__ == "__main__":
    unittest.main()
