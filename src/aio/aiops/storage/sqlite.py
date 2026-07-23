#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import logging
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from aiops.incidents import incident_fingerprint
from aiops.notifications import NotificationBuilder, is_slo_notification
from aiops.schemas import CandidateEvent, Incident, NotificationMessage

logger = logging.getLogger(__name__)


class SQLiteIncidentStore:
    def __init__(
        self,
        path: Path,
        environment: str,
        runbooks_dir: Path | None = None,
        notification_cooldown_seconds: int = 900,
        slo_dedup_seconds: int = 300,
        rca_dedup_seconds: int = 300,
        incident_count_reset_seconds: int = 900,
        topology_graph=None,
    ):
        self.path = path
        self.environment = environment
        self.runbooks_dir = runbooks_dir or _default_runbooks_dir()
        self.notification_cooldown_seconds = notification_cooldown_seconds
        self.slo_dedup_seconds = slo_dedup_seconds
        self.rca_dedup_seconds = rca_dedup_seconds
        self.incident_count_reset_seconds = incident_count_reset_seconds
        self.topology_graph = topology_graph
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
            CREATE TABLE IF NOT EXISTS notification_service_cooldowns (
                service TEXT PRIMARY KEY,
                cooldown_until TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS active_root_causes (
                root_service TEXT PRIMARY KEY,
                affected_services_json TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                root_score REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self._ensure_event_columns()
        self._ensure_active_root_columns()

    def upsert(self, candidate: CandidateEvent) -> Incident:
        self._validate_runbook(candidate.runbook_id)
        fingerprint = incident_fingerprint(self.environment, candidate, self.topology_graph)
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
            if self._count_window_expired(incident, candidate):
                incident.occurrence_count = 1
                incident.events = [candidate]
                incident.severity = candidate.severity
            else:
                incident.occurrence_count += 1
                incident.events.append(candidate)
                incident.severity = min(incident.severity, candidate.severity)
            incident.last_seen = seen_at

        now = datetime.now(UTC)
        slo_notification = is_slo_notification(candidate)
        rca_notification = candidate.detector_id == "rca_root_cause"
        notification_due = self._notification_due(incident, is_new, now)
        can_enqueue_incident = notification_due and self._can_enqueue_notification(incident.incident_id)
        cooldown_key = _notification_cooldown_key(incident.service, slo_notification, rca_notification)
        service_notification_due = False
        if can_enqueue_incident:
            service_notification_due = self._service_notification_due(
                cooldown_key,
                incident.severity,
                now,
                bypass_sev1=not (slo_notification or rca_notification),
            )
        notification = (
            NotificationBuilder().build([incident])[0]
            if can_enqueue_incident and service_notification_due
            else None
        )
        if notification is not None:
            cooldown_seconds = self.slo_dedup_seconds if slo_notification else self.rca_dedup_seconds if rca_notification else self.notification_cooldown_seconds
            incident.cooldown_until = (now + timedelta(seconds=cooldown_seconds)).isoformat()
        service_suppressed = can_enqueue_incident and not service_notification_due
        notification_enqueued = False
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
                cursor = self._connection.execute(
                    """
                    INSERT INTO notification_outbox (
                        incident_id, fingerprint, notification_json, status, next_attempt_at
                    )
                    VALUES (?, ?, ?, 'pending', ?)
                    ON CONFLICT(incident_id) DO UPDATE SET
                        notification_json = excluded.notification_json,
                        status = 'pending',
                        next_attempt_at = excluded.next_attempt_at,
                        updated_at = excluded.next_attempt_at
                    WHERE notification_outbox.status IN ('sent', 'suppressed')
                    """,
                    (incident.incident_id, fingerprint, notification.model_dump_json(), _now()),
                )
                notification_enqueued = cursor.rowcount > 0
                if notification_enqueued:
                    self._set_service_notification_cooldown(cooldown_key, incident.cooldown_until or _now())
                    self._last_enqueued_incident_ids.add(incident.incident_id)
                    logger.info(
                        "AIOPS_NOTIFY_ENQUEUED_READY incident=%s service=%s severity=%s runbook=%s status=pending",
                        incident.incident_id,
                        incident.service,
                        incident.severity,
                        notification.runbook_id,
                    )
            elif service_suppressed:
                logger.info(
                    "AIOPS_NOTIFY_SUPPRESSED incident=%s service=%s reason=same_service_cooldown",
                    incident.incident_id,
                    incident.service,
                )
        (logger.info if is_new else logger.debug)(
            "AIOPS_INCIDENT_UPSERT action=%s incident=%s fingerprint=%s service=%s detector=%s occurrence=%s notification_enqueued=%s",
            "created" if is_new else "deduped",
            incident.incident_id,
            fingerprint,
            incident.service,
            candidate.detector_id,
            incident.occurrence_count,
            notification_enqueued,
        )
        return incident

    def _notification_due(self, incident: Incident, is_new: bool, now: datetime) -> bool:
        if is_new or not incident.cooldown_until:
            return True
        return datetime.fromisoformat(incident.cooldown_until) <= now

    def _count_window_expired(self, incident: Incident, candidate: CandidateEvent) -> bool:
        if self.incident_count_reset_seconds <= 0 or not incident.events:
            return True
        first_seen = _candidate_seen_at(incident.events[0])
        current_seen = _candidate_seen_at(candidate)
        return current_seen - first_seen >= timedelta(seconds=self.incident_count_reset_seconds)

    def _can_enqueue_notification(self, incident_id: str) -> bool:
        row = self._connection.execute(
            "SELECT status FROM notification_outbox WHERE incident_id = ?",
            (incident_id,),
        ).fetchone()
        return row is None or row[0] in {"sent", "suppressed"}

    def _service_notification_due(self, service: str, severity: str, now: datetime, bypass_sev1: bool = True) -> bool:
        if bypass_sev1 and severity == "SEV1":
            return True
        row = self._connection.execute(
            "SELECT cooldown_until FROM notification_service_cooldowns WHERE service = ?",
            (service,),
        ).fetchone()
        return row is None or datetime.fromisoformat(row[0]) <= now

    def _set_service_notification_cooldown(self, service: str, cooldown_until: str) -> None:
        self._connection.execute(
            """
            INSERT INTO notification_service_cooldowns (service, cooldown_until, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(service) DO UPDATE SET
                cooldown_until = excluded.cooldown_until,
                updated_at = excluded.updated_at
            """,
            (service, cooldown_until, _now()),
        )

    def register_active_root_cause(
        self,
        root_service: str,
        affected_services: set[str],
        suppress_seconds: int = 900,
        root_score: float = 0.0,
    ) -> None:
        now = datetime.now(UTC)
        row = self._connection.execute(
            "SELECT expires_at, root_score FROM active_root_causes WHERE root_service = ?",
            (root_service,),
        ).fetchone()
        expires_at = (now + timedelta(seconds=suppress_seconds)).isoformat()
        if row is not None and datetime.fromisoformat(row[0]) > now:
            expires_at = row[0]
            root_score = float(row[1])
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO active_root_causes (root_service, affected_services_json, expires_at, root_score)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(root_service) DO UPDATE SET
                    affected_services_json = excluded.affected_services_json,
                    expires_at = excluded.expires_at,
                    root_score = excluded.root_score
                """,
                (root_service, json.dumps(sorted(affected_services)), expires_at, root_score),
            )

    def breakout_services(self, service_scores: dict[str, float], multiplier: float) -> set[str]:
        if self.topology_graph is None or not service_scores:
            return set()
        rows = self._connection.execute(
            "SELECT root_service, root_score, affected_services_json FROM active_root_causes WHERE expires_at > ? AND root_score > 0",
            (_now(),),
        ).fetchall()
        if not rows:
            return set()

        breakouts = set()
        for service, score in service_scores.items():
            relevant_root_scores = []
            for root_service, root_score, affected_json in rows:
                if service == root_service:
                    continue
                affected_set = set(json.loads(affected_json)) if affected_json else set()
                is_neighbor = service in self.topology_graph.neighborhood(root_service, max_hops=1)
                if service in affected_set or is_neighbor:
                    relevant_root_scores.append(float(root_score))
            if relevant_root_scores and score >= max(relevant_root_scores) * multiplier:
                breakouts.add(service)
        return breakouts

    def suppress_related_notifications(
        self,
        incidents: list[Incident],
        root_service: str,
        affected_services: set[str],
        exempt_services: set[str] | None = None,
    ) -> set[str]:
        exempt_services = exempt_services or set()
        suppressed = [
            incident
            for incident in incidents
            if incident.service in affected_services and incident.service != root_service and incident.service not in exempt_services
        ]
        if not suppressed:
            return set()
        suppressed_ids = {incident.incident_id for incident in suppressed}
        with self._connection:
            for incident in suppressed:
                self._connection.execute(
                    "UPDATE notification_outbox SET status = 'suppressed', updated_at = ? WHERE incident_id = ? AND status = 'pending'",
                    (_now(), incident.incident_id),
                )
                self._last_enqueued_incident_ids.discard(incident.incident_id)
                logger.info(
                    "AIOPS_NOTIFY_SUPPRESSED incident=%s service=%s parent_root_cause=%s reason=same_blast_radius",
                    incident.incident_id,
                    incident.service,
                    root_service,
                )
        return suppressed_ids

    def suppress_active_root_notifications(
        self,
        incidents: list[Incident],
        exempt_services: set[str] | None = None,
    ) -> set[str]:
        exempt_services = exempt_services or set()
        rows = [
            (incident, parent)
            for incident in incidents
            if incident.service not in exempt_services
            for parent in [self._suppression_parent(incident.service)]
            if parent is not None
        ]
        if not rows:
            return set()
        with self._connection:
            for incident, parent in rows:
                self._connection.execute(
                    "UPDATE notification_outbox SET status = 'suppressed', updated_at = ? WHERE incident_id = ? AND status = 'pending'",
                    (_now(), incident.incident_id),
                )
                self._last_enqueued_incident_ids.discard(incident.incident_id)
                logger.info(
                    "AIOPS_NOTIFY_SUPPRESSED incident=%s service=%s parent_root_cause=%s reason=active_root_cause",
                    incident.incident_id,
                    incident.service,
                    parent,
                )
        return {incident.incident_id for incident, _ in rows}

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

    def suppressed_incident_ids(self, incidents: list[Incident]) -> set[str]:
        return {
            incident.incident_id
            for incident in incidents
            if self._suppression_parent(incident.service) is not None
        }

    def _suppression_parent(self, service: str) -> str | None:
        rows = self._connection.execute(
            "SELECT root_service, affected_services_json FROM active_root_causes WHERE expires_at > ? ORDER BY root_score DESC, root_service ASC",
            (_now(),),
        ).fetchall()
        for root_service, affected_json in rows:
            if service != root_service and service in set(json.loads(affected_json)):
                return root_service
        return None

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

    def _ensure_active_root_columns(self) -> None:
        columns = {row[1] for row in self._connection.execute("PRAGMA table_info(active_root_causes)").fetchall()}
        if "root_score" not in columns:
            self._connection.execute("ALTER TABLE active_root_causes ADD COLUMN root_score REAL NOT NULL DEFAULT 0")


def _seen_at(candidate: CandidateEvent) -> str:
    return _candidate_seen_at(candidate).isoformat()


def _candidate_seen_at(candidate: CandidateEvent) -> datetime:
    if candidate.timestamp:
        return datetime.fromtimestamp(candidate.timestamp, UTC)
    return datetime.now(UTC)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _slo_cooldown_key(service: str) -> str:
    return f"slo:{service}"


def _notification_cooldown_key(service: str, slo_notification: bool, rca_notification: bool) -> str:
    if slo_notification:
        return _slo_cooldown_key(service)
    if rca_notification:
        return f"rca:{service}"
    return service


def _default_runbooks_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "runbooks"
