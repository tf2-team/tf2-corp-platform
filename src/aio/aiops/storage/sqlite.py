from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from aiops.incidents import incident_fingerprint
from aiops.notifications import NotificationBuilder
from aiops.schemas import CandidateEvent, Incident, NotificationMessage

logger = logging.getLogger(__name__)


class SQLiteIncidentStore:
    def __init__(self, path: Path, environment: str, runbooks_dir: Path | None = None):
        self.path = path
        self.environment = environment
        self.runbooks_dir = runbooks_dir or _default_runbooks_dir()
        self._last_enqueued_incident_ids: set[str] = set()
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
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS notification_outbox (
                incident_id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                notification_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempt_count INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT NOT NULL,
                last_error TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS notification_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id TEXT NOT NULL,
                status TEXT NOT NULL,
                attempt_number INTEGER NOT NULL,
                error TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self._ensure_event_columns()

    def upsert(self, candidate: CandidateEvent) -> Incident:
        self._validate_runbook(candidate.runbook_id)
        fingerprint = incident_fingerprint(self.environment, candidate)
        seen_at = _seen_at(candidate)
        row = self._connection.execute(
            "SELECT incident_json FROM incidents WHERE fingerprint = ?",
            (fingerprint,),
        ).fetchone()

        is_new = row is None
        if is_new:
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

        notification = NotificationBuilder().build([incident])[0] if is_new else None
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
            if notification is not None:
                self._connection.execute(
                    """
                    INSERT OR IGNORE INTO notification_outbox (
                        incident_id, fingerprint, notification_json, status, next_attempt_at
                    )
                    VALUES (?, ?, ?, 'pending', ?)
                    """,
                    (incident.incident_id, fingerprint, notification.model_dump_json(), _now()),
                )
                self._last_enqueued_incident_ids.add(incident.incident_id)
        (logger.info if is_new else logger.debug)(
            "AIOPS_INCIDENT_UPSERT action=%s incident=%s fingerprint=%s service=%s detector=%s occurrence=%s notification_enqueued=%s",
            "created" if is_new else "deduped",
            incident.incident_id,
            fingerprint,
            incident.service,
            candidate.detector_id,
            incident.occurrence_count,
            notification is not None,
        )
        return incident

    def list_incidents(self) -> list[Incident]:
        rows = self._connection.execute("SELECT incident_json FROM incidents ORDER BY fingerprint").fetchall()
        return [Incident.model_validate_json(row[0]) for row in rows]

    def pending_notifications_for(self, incidents: list[Incident]) -> list[NotificationMessage]:
        incident_ids = [incident.incident_id for incident in incidents if incident.incident_id in self._last_enqueued_incident_ids]
        if not incident_ids:
            return []
        placeholders = ",".join("?" for _ in incident_ids)
        rows = self._connection.execute(
            f"SELECT notification_json FROM notification_outbox WHERE status = 'pending' AND incident_id IN ({placeholders}) ORDER BY created_at",
            incident_ids,
        ).fetchall()
        return [NotificationMessage.model_validate_json(row[0]) for row in rows]

    def due_notifications(self, limit: int = 100) -> list[NotificationMessage]:
        rows = self._connection.execute(
            """
            SELECT notification_json
            FROM notification_outbox
            WHERE status IN ('pending', 'retry') AND next_attempt_at <= ?
            ORDER BY next_attempt_at
            LIMIT ?
            """,
            (_now(), limit),
        ).fetchall()
        return [NotificationMessage.model_validate_json(row[0]) for row in rows]

    def mark_notification_sent(self, incident_id: str) -> None:
        row = self._connection.execute(
            "SELECT attempt_count FROM notification_outbox WHERE incident_id = ?",
            (incident_id,),
        ).fetchone()
        if row is None:
            return
        attempt_count = int(row[0]) + 1
        with self._connection:
            self._connection.execute(
                "UPDATE notification_outbox SET status = 'sent', attempt_count = ?, updated_at = ? WHERE incident_id = ?",
                (attempt_count, _now(), incident_id),
            )
            self._record_notification_attempt(incident_id, "sent", attempt_count)

    def _record_notification_attempt(self, incident_id: str, status: str, attempt_number: int, error: str | None = None) -> None:
        self._connection.execute(
            """
            INSERT INTO notification_attempts (incident_id, status, attempt_number, error)
            VALUES (?, ?, ?, ?)
            """,
            (incident_id, status, attempt_number, error[:512] if error else None),
        )

    def mark_notification_failed(self, incident_id: str, error: str) -> None:
        row = self._connection.execute(
            "SELECT attempt_count FROM notification_outbox WHERE incident_id = ?",
            (incident_id,),
        ).fetchone()
        if row is None:
            return
        attempt_count = int(row[0]) + 1
        retry_at = datetime.now(UTC) + timedelta(seconds=min(60 * (2 ** (attempt_count - 1)), 3600))
        with self._connection:
            self._connection.execute(
                """
                UPDATE notification_outbox
                SET status = 'retry', attempt_count = ?, next_attempt_at = ?, last_error = ?, updated_at = ?
                WHERE incident_id = ?
                """,
                (attempt_count, retry_at.isoformat(), error[:512], _now(), incident_id),
            )
            self._record_notification_attempt(incident_id, "failed", attempt_count, error)

    def close(self) -> None:
        self._connection.close()

    def _validate_runbook(self, runbook_id: str) -> None:
        if not (self.runbooks_dir / f"{runbook_id}.md").is_file():
            raise ValueError(f"missing canonical runbook: {runbook_id}")

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
    return _now()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _default_runbooks_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "runbooks"
