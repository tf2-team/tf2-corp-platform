from __future__ import annotations

import sqlite3
from pathlib import Path

from aiops.incidents import incident_fingerprint
from aiops.schemas import CandidateEvent, Incident


class SQLiteIncidentStore:
    def __init__(self, path: Path, environment: str):
        self.path = path
        self.environment = environment
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS incidents (
                fingerprint TEXT PRIMARY KEY,
                incident_json TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS incident_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL,
                event_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    def upsert(self, candidate: CandidateEvent) -> Incident:
        fingerprint = incident_fingerprint(self.environment, candidate)
        row = self._connection.execute(
            "SELECT incident_json FROM incidents WHERE fingerprint = ?",
            (fingerprint,),
        ).fetchone()

        if row is None:
            digest = fingerprint.removeprefix("sha256:")
            incident = Incident(
                incident_id=f"inc-{digest[:12]}",
                fingerprint=fingerprint,
                state="open",
                severity=candidate.severity,
                flow=candidate.flow,
                service=candidate.service,
                likely_dependency=candidate.likely_dependency,
                events=[candidate],
            )
        else:
            incident = Incident.model_validate_json(row[0])
            incident.occurrence_count += 1
            incident.events.append(candidate)
            incident.severity = min(incident.severity, candidate.severity)

        with self._connection:
            self._connection.execute(
                """
                INSERT INTO incidents (fingerprint, incident_json)
                VALUES (?, ?)
                ON CONFLICT(fingerprint) DO UPDATE SET incident_json = excluded.incident_json
                """,
                (fingerprint, incident.model_dump_json()),
            )
            self._connection.execute(
                "INSERT INTO incident_events (fingerprint, event_json) VALUES (?, ?)",
                (fingerprint, candidate.model_dump_json()),
            )
        return incident

    def list_incidents(self) -> list[Incident]:
        rows = self._connection.execute("SELECT incident_json FROM incidents ORDER BY fingerprint").fetchall()
        return [Incident.model_validate_json(row[0]) for row in rows]

    def close(self) -> None:
        self._connection.close()
