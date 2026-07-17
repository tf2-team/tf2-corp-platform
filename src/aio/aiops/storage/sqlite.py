from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
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
                state TEXT NOT NULL DEFAULT 'open',
                last_seen TEXT,
                recovered_at TEXT,
                cooldown_until TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self._ensure_event_columns()

    def upsert(self, candidate: CandidateEvent) -> Incident:
        fingerprint = incident_fingerprint(self.environment, candidate)
        seen_at = _seen_at(candidate)
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
                last_seen=seen_at,
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
            incident.last_seen = seen_at
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
                """
                INSERT INTO incident_events (fingerprint, event_json, state, last_seen, recovered_at, cooldown_until)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (fingerprint, candidate.model_dump_json(), incident.state, incident.last_seen, incident.recovered_at, incident.cooldown_until),
            )
        return incident

    def list_incidents(self) -> list[Incident]:
        rows = self._connection.execute("SELECT incident_json FROM incidents ORDER BY fingerprint").fetchall()
        return [Incident.model_validate_json(row[0]) for row in rows]

    def close(self) -> None:
        self._connection.close()

    def _ensure_event_columns(self) -> None:
        columns = {row[1] for row in self._connection.execute("PRAGMA table_info(incident_events)").fetchall()}
        for name, ddl in {
            "state": "ALTER TABLE incident_events ADD COLUMN state TEXT NOT NULL DEFAULT 'open'",
            "last_seen": "ALTER TABLE incident_events ADD COLUMN last_seen TEXT",
            "recovered_at": "ALTER TABLE incident_events ADD COLUMN recovered_at TEXT",
            "cooldown_until": "ALTER TABLE incident_events ADD COLUMN cooldown_until TEXT",
        }.items():
            if name not in columns:
                self._connection.execute(ddl)


def _seen_at(candidate: CandidateEvent) -> str:
    if candidate.timestamp:
        return datetime.fromtimestamp(candidate.timestamp, UTC).isoformat()
    return datetime.now(UTC).isoformat()
