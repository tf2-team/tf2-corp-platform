#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import logging
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from aiops.incidents import incident_fingerprint
from aiops.notifications import NotificationBuilder, is_slo_notification
from aiops.schemas import CandidateEvent, Incident, NotificationMessage
from aiops.shared.evidence import STRONG_LOG_MARKER, STRONG_TRACE_MARKER

logger = logging.getLogger(__name__)
SUPPLEMENTAL_NOTIFICATION_SUFFIX = ":supplement:"


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
        recovery_consecutive_buckets: int = 6,
        notification_retry_base_seconds: int = 60,
        notification_retry_max_seconds: int = 3600,
        notification_error_max_chars: int = 512,
        topology_graph=None,
    ):
        self.path = path
        self.environment = environment
        self.runbooks_dir = runbooks_dir or _default_runbooks_dir()
        self.notification_cooldown_seconds = notification_cooldown_seconds
        self.slo_dedup_seconds = slo_dedup_seconds
        self.rca_dedup_seconds = rca_dedup_seconds
        self.incident_count_reset_seconds = incident_count_reset_seconds
        self.recovery_consecutive_buckets = recovery_consecutive_buckets
        self.notification_retry_base_seconds = notification_retry_base_seconds
        self.notification_retry_max_seconds = notification_retry_max_seconds
        self.notification_error_max_chars = notification_error_max_chars
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
                cycle INTEGER NOT NULL DEFAULT 1,
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
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS self_heal_workflows (
                incident_id TEXT PRIMARY KEY,
                execution_id TEXT,
                status TEXT NOT NULL,
                workflow_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS self_heal_audit_events (
                event_id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                execution_id TEXT,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self._ensure_event_columns()
        self._ensure_outbox_columns()
        self._ensure_active_root_columns()

    def upsert(self, candidate: CandidateEvent) -> Incident:
        self._validate_runbook(candidate.runbook_id)
        if not candidate.timestamp:
            candidate = candidate.model_copy(update={"timestamp": int(datetime.now(UTC).timestamp())})
        fingerprint = incident_fingerprint(self.environment, candidate, self.topology_graph)
        seen_at = _seen_at(candidate)
        row = self._connection.execute(
            "SELECT incident_json FROM incidents WHERE fingerprint = ?",
            (fingerprint,),
        ).fetchone()

        is_new = row is None
        previous_severity = None
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
            previous_severity = incident.severity
            incident.state = "open" if incident.state == "recovered" else "ongoing"
            incident.recovered_at = None
            incident.recovery_count = 0
            incident.events = _events_in_window(
                incident.events,
                candidate,
                self.incident_count_reset_seconds,
            ) + [candidate]
            incident.occurrence_count = len(incident.events)
            incident.severity = min(event.severity for event in incident.events)
            incident.last_seen = seen_at

        now = datetime.now(UTC)
        slo_notification = is_slo_notification(candidate)
        rca_notification = candidate.detector_id == "rca_root_cause"
        severity_escalated = previous_severity is not None and _severity_rank(candidate.severity) < _severity_rank(previous_severity)
        notification_due = self._notification_due(incident, is_new, now) or severity_escalated
        outbox_status = self._notification_outbox_status(incident.incident_id)
        can_enqueue_incident = notification_due and (
            outbox_status is None
            or outbox_status in {"sent", "suppressed"}
            or severity_escalated and outbox_status in {"pending", "retry"}
        )
        cooldown_key = _notification_cooldown_key(incident.service, slo_notification, rca_notification)
        service_notification_due = False
        if can_enqueue_incident:
            service_notification_due = self._service_notification_due(
                cooldown_key,
                incident.severity,
                now,
                bypass_sev1=severity_escalated or not (slo_notification or rca_notification),
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
                        attempt_count = 0,
                        next_attempt_at = excluded.next_attempt_at,
                        last_error = NULL,
                        cycle = CASE
                            WHEN notification_outbox.status IN ('sent', 'suppressed') THEN notification_outbox.cycle + 1
                            ELSE notification_outbox.cycle
                        END,
                        created_at = CASE
                            WHEN notification_outbox.status IN ('sent', 'suppressed') THEN excluded.next_attempt_at
                            ELSE notification_outbox.created_at
                        END,
                        updated_at = excluded.next_attempt_at
                    WHERE notification_outbox.status IN ('sent', 'suppressed')
                       OR (? AND notification_outbox.status IN ('pending', 'retry'))
                    """,
                    (incident.incident_id, fingerprint, notification.model_dump_json(), _now(), severity_escalated),
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
            self._refresh_pending_rca_notification(incident, candidate)
            supplemental = self._supplemental_rca_notification(incident, candidate)
            if supplemental is not None:
                self._connection.execute(
                    """
                    INSERT INTO notification_outbox (
                        incident_id, fingerprint, notification_json, status, next_attempt_at
                    )
                    VALUES (?, ?, ?, 'pending', ?)
                    """,
                    (supplemental.incident_id, fingerprint, supplemental.model_dump_json(), _now()),
                )
                self._last_enqueued_incident_ids.add(supplemental.incident_id)
                notification_enqueued = True
                logger.info(
                    "AIOPS_NOTIFY_ENQUEUED_READY incident=%s service=%s severity=%s runbook=%s status=pending reason=strong_evidence_supplement",
                    supplemental.incident_id,
                    supplemental.service,
                    supplemental.severity,
                    supplemental.runbook_id,
                )
            elif service_suppressed:
                logger.info(
                    "AIOPS_NOTIFY_SUPPRESSED filter=service_notification_cooldown source=notification incident=%s service=%s reason=same_service_cooldown cooldown_key=%s",
                    incident.incident_id,
                    incident.service,
                    cooldown_key,
                )
            elif not notification_due:
                logger.info(
                    "AIOPS_NOTIFY_DEDUPED filter=incident_cooldown source=notification incident=%s service=%s reason=incident_cooldown_until cooldown_until=%s",
                    incident.incident_id,
                    incident.service,
                    incident.cooldown_until,
                )
            elif outbox_status not in {None, "sent", "suppressed"}:
                logger.info(
                    "AIOPS_NOTIFY_DEDUPED filter=notification_outbox source=notification incident=%s service=%s reason=notification_status status=%s",
                    incident.incident_id,
                    incident.service,
                    outbox_status,
                )
        (logger.info if is_new else logger.debug)(
            "AIOPS_INCIDENT_UPSERT action=%s filter=incident_fingerprint source=incident incident=%s fingerprint=%s service=%s detector=%s occurrence=%s notification_enqueued=%s",
            "created" if is_new else "deduped",
            incident.incident_id,
            fingerprint,
            incident.service,
            candidate.detector_id,
            incident.occurrence_count,
            notification_enqueued,
        )
        return incident

    def reconcile_lifecycle(self, seen_incident_ids: set[str]) -> list[Incident]:
        """Keep unseen incidents active until recovery is stable for N runs."""
        incidents = self.list_incidents()
        now = _now()
        with self._connection:
            for incident in incidents:
                if incident.state == "recovered":
                    continue
                if incident.incident_id in seen_incident_ids:
                    incident.recovery_count = 0
                    if incident.occurrence_count > 1:
                        incident.state = "ongoing"
                else:
                    incident.recovery_count += 1
                    if incident.recovery_count >= self.recovery_consecutive_buckets:
                        incident.state = "recovered"
                        incident.recovered_at = now
                        self._enqueue_recovery_notification(incident)
                self._connection.execute(
                    "UPDATE incidents SET incident_json = ? WHERE fingerprint = ?",
                    (incident.model_dump_json(), incident.fingerprint),
                )
        return incidents

    def _enqueue_recovery_notification(self, incident: Incident) -> None:
        message = NotificationBuilder().build([incident])[0]
        recovery_id = f"{incident.incident_id}:recovery"
        message = message.model_copy(update={"incident_id": recovery_id})
        self._connection.execute(
            """
            INSERT INTO notification_outbox (incident_id, fingerprint, notification_json, status, next_attempt_at)
            VALUES (?, ?, ?, 'pending', ?)
            ON CONFLICT(incident_id) DO UPDATE SET
                notification_json = excluded.notification_json,
                status = 'pending',
                next_attempt_at = excluded.next_attempt_at,
                updated_at = excluded.next_attempt_at
            """,
            (recovery_id, incident.fingerprint, message.model_dump_json(), _now()),
        )
        self._last_enqueued_incident_ids.add(recovery_id)

    def _notification_due(self, incident: Incident, is_new: bool, now: datetime) -> bool:
        if is_new or not incident.cooldown_until:
            return True
        return datetime.fromisoformat(incident.cooldown_until) <= now

    def _notification_outbox_status(self, incident_id: str) -> str | None:
        row = self._connection.execute(
            "SELECT status FROM notification_outbox WHERE incident_id = ?",
            (incident_id,),
        ).fetchone()
        return None if row is None else str(row[0])

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
            root_score = max(float(row[1]), root_score)
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
        logger.info(
            "AIOPS_RCA_SUPPRESS_REGISTER filter=active_root_registry source=rca root_service=%s affected_services=%s suppress_until=%s root_score=%.3f reason=active_root_cause",
            root_service,
            sorted(affected_services),
            expires_at,
            root_score,
        )

    def breakout_services(self, service_scores: dict[str, float], multiplier: float, max_hops: int = 1) -> set[str]:
        if self.topology_graph is None:
            return set()
        rows = self._connection.execute(
            "SELECT root_service, root_score FROM active_root_causes WHERE expires_at > ? AND root_score > 0",
            (_now(),),
        ).fetchall()
        required: dict[str, float] = {}
        for root_service, root_score in rows:
            threshold = float(root_score) * multiplier
            for service in self.topology_graph.blast_radius(root_service, max_hops=max_hops):
                if service != root_service:
                    required[service] = max(required.get(service, 0.0), threshold)
        return {service for service, score in service_scores.items() if score >= required.get(service, float("inf"))}

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
        suppressed_ids = set()
        with self._connection:
            for incident in suppressed:
                if not self._suppress_notification(incident):
                    continue
                suppressed_ids.add(incident.incident_id)
                logger.info(
                    "AIOPS_NOTIFY_SUPPRESSED filter=same_blast_radius source=rca incident=%s service=%s parent_root_cause=%s reason=same_blast_radius",
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
        suppressed_ids = set()
        with self._connection:
            for incident, parent in rows:
                if not self._suppress_notification(incident):
                    continue
                suppressed_ids.add(incident.incident_id)
                logger.info(
                    "AIOPS_NOTIFY_SUPPRESSED filter=active_root_cause source=rca incident=%s service=%s parent_root_cause=%s reason=active_root_cause",
                    incident.incident_id,
                    incident.service,
                    parent,
                )
        return suppressed_ids

    def _suppress_notification(self, incident: Incident) -> bool:
        now = _now()
        base = self._connection.execute(
            "UPDATE notification_outbox SET status = 'suppressed', updated_at = ? WHERE incident_id = ? AND status IN ('pending', 'retry')",
            (now, incident.incident_id),
        )
        supplements = self._connection.execute(
            "UPDATE notification_outbox SET status = 'suppressed', updated_at = ? WHERE incident_id LIKE ? AND status IN ('pending', 'retry')",
            (now, f"{incident.incident_id}{SUPPLEMENTAL_NOTIFICATION_SUFFIX}%"),
        )
        self._last_enqueued_incident_ids = {
            incident_id
            for incident_id in self._last_enqueued_incident_ids
            if incident_id != incident.incident_id and not incident_id.startswith(f"{incident.incident_id}{SUPPLEMENTAL_NOTIFICATION_SUFFIX}")
        }
        if base.rowcount:
            event = incident.events[-1]
            key = _notification_cooldown_key(incident.service, is_slo_notification(event), event.detector_id == "rca_root_cause")
            if incident.cooldown_until:
                self._connection.execute(
                    "DELETE FROM notification_service_cooldowns WHERE service = ? AND cooldown_until = ?",
                    (key, incident.cooldown_until),
                )
            incident.cooldown_until = None
            self._connection.execute(
                "UPDATE incidents SET incident_json = ? WHERE fingerprint = ?",
                (incident.model_dump_json(), incident.fingerprint),
            )
        return bool(base.rowcount or supplements.rowcount)

    def list_incidents(self) -> list[Incident]:
        rows = self._connection.execute("SELECT fingerprint, incident_json FROM incidents ORDER BY fingerprint").fetchall()
        incidents = []
        with self._connection:
            for fingerprint, incident_json in rows:
                incident, changed = _incident_from_json(incident_json)
                incidents.append(incident)
                if changed:
                    self._connection.execute(
                        "UPDATE incidents SET incident_json = ? WHERE fingerprint = ?",
                        (incident.model_dump_json(), fingerprint),
                    )
        return incidents

    def save_self_heal_workflow(self, workflow: dict) -> None:
        now = _now()
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO self_heal_workflows (
                    incident_id, execution_id, status, workflow_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(incident_id) DO UPDATE SET
                    execution_id = excluded.execution_id,
                    status = excluded.status,
                    workflow_json = excluded.workflow_json,
                    updated_at = excluded.updated_at
                """,
                (
                    workflow["incident_id"],
                    workflow.get("execution_id"),
                    workflow["status"],
                    json.dumps(workflow, sort_keys=True),
                    now,
                    now,
                ),
            )

    def active_self_heal_workflows(self) -> list[dict]:
        rows = self._connection.execute(
            """
            SELECT workflow_json
            FROM self_heal_workflows
            WHERE status IN ('verifying', 'rollback_pending')
            ORDER BY created_at
            """
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def queued_self_heal_workflows(self) -> list[dict]:
        rows = self._connection.execute(
            "SELECT workflow_json FROM self_heal_workflows WHERE status = 'queued' ORDER BY created_at"
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def self_heal_workflow(self, incident_id: str) -> dict | None:
        row = self._connection.execute(
            "SELECT workflow_json FROM self_heal_workflows WHERE incident_id = ?",
            (incident_id,),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def append_self_heal_audit(
        self,
        event_type: str,
        incident_id: str,
        execution_id: str | None,
        payload: dict,
    ) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO self_heal_audit_events (
                    event_id, incident_id, execution_id, event_type, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    f"evt-{uuid4()}",
                    incident_id,
                    execution_id,
                    event_type,
                    json.dumps(payload, sort_keys=True),
                    _now(),
                ),
            )

    def self_heal_audit_events(self, incident_id: str) -> list[dict]:
        rows = self._connection.execute(
            """
            SELECT event_id, incident_id, execution_id, event_type, payload_json, created_at
            FROM self_heal_audit_events
            WHERE incident_id = ?
            ORDER BY created_at, rowid
            """,
            (incident_id,),
        ).fetchall()
        return [
            {
                "event_id": row[0],
                "incident_id": row[1],
                "execution_id": row[2],
                "event_type": row[3],
                "payload": json.loads(row[4]),
                "created_at": row[5],
            }
            for row in rows
        ]

    def mark_incident_recovered(self, incident_id: str, recovered_at: str | None = None) -> Incident | None:
        recovered_at = recovered_at or _now()
        rows = self._connection.execute(
            "SELECT fingerprint, incident_json FROM incidents"
        ).fetchall()
        for fingerprint, incident_json in rows:
            incident = Incident.model_validate_json(incident_json)
            if incident.incident_id != incident_id:
                continue
            incident.state = "recovered"
            incident.recovered_at = recovered_at
            with self._connection:
                self._connection.execute(
                    "UPDATE incidents SET incident_json = ? WHERE fingerprint = ?",
                    (incident.model_dump_json(), fingerprint),
                )
                self._connection.execute(
                    """
                    UPDATE incident_events
                    SET state = 'recovered', recovered_at = ?
                    WHERE fingerprint = ? AND state != 'recovered'
                    """,
                    (recovered_at, fingerprint),
                )
                self._enqueue_recovery_notification(incident)
            return incident
        return None

    def pending_notifications_for(self, incidents: list[Incident]) -> list[NotificationMessage]:
        prefixes = tuple(f"{incident.incident_id}{SUPPLEMENTAL_NOTIFICATION_SUFFIX}" for incident in incidents)
        base_ids = {incident.incident_id for incident in incidents}
        recovery_ids = {f"{incident.incident_id}:recovery" for incident in incidents}
        incident_ids = [
            incident_id
            for incident_id in self._last_enqueued_incident_ids
            if incident_id in base_ids or incident_id in recovery_ids or incident_id.startswith(prefixes)
        ]
        if not incident_ids:
            return []
        placeholders = ",".join("?" for _ in incident_ids)
        rows = self._connection.execute(
            f"SELECT notification_json FROM notification_outbox WHERE status = 'pending' AND incident_id IN ({placeholders}) ORDER BY created_at, rowid",
            incident_ids,
        ).fetchall()
        self._last_enqueued_incident_ids.difference_update(incident_ids)
        return _ordered_notifications(rows)

    def enqueue_notification(self, message: NotificationMessage) -> None:
        now = _now()
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO notification_outbox (
                    incident_id, fingerprint, notification_json, status, next_attempt_at
                )
                VALUES (?, ?, ?, 'pending', ?)
                ON CONFLICT(incident_id) DO UPDATE SET
                    notification_json = excluded.notification_json,
                    status = CASE
                        WHEN notification_outbox.status = 'sent' THEN notification_outbox.status
                        ELSE 'pending'
                    END,
                    next_attempt_at = CASE
                        WHEN notification_outbox.status = 'sent' THEN notification_outbox.next_attempt_at
                        ELSE excluded.next_attempt_at
                    END,
                    updated_at = excluded.next_attempt_at
                """,
                (
                    message.incident_id,
                    message.incident_id,
                    message.model_dump_json(),
                    now,
                ),
            )

    def suppressed_incident_ids(self, incidents: list[Incident]) -> set[str]:
        return {
            incident.incident_id
            for incident in incidents
            if self._suppression_parent(incident.service) is not None
        }

    def _suppression_parent(self, service: str) -> str | None:
        rows = self._connection.execute(
            "SELECT root_service, affected_services_json FROM active_root_causes WHERE expires_at > ? ORDER BY root_score DESC, root_service",
            (_now(),),
        ).fetchall()
        if service in {root_service for root_service, _ in rows}:
            return None
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
            ORDER BY next_attempt_at, rowid
            LIMIT ?
            """,
            (_now(), limit),
        ).fetchall()
        return _ordered_notifications(rows)

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
        retry_seconds = min(self.notification_retry_base_seconds * (2 ** (attempt_count - 1)), self.notification_retry_max_seconds)
        retry_at = datetime.now(UTC) + timedelta(seconds=retry_seconds)
        with self._connection:
            self._connection.execute(
                """
                UPDATE notification_outbox
                SET status = 'retry', attempt_count = ?, next_attempt_at = ?, last_error = ?, updated_at = ?
                WHERE incident_id = ?
                """,
                (attempt_count, retry_at.isoformat(), error[: self.notification_error_max_chars], _now(), incident_id),
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

    def _ensure_outbox_columns(self) -> None:
        columns = {row[1] for row in self._connection.execute("PRAGMA table_info(notification_outbox)").fetchall()}
        if "cycle" not in columns:
            self._connection.execute("ALTER TABLE notification_outbox ADD COLUMN cycle INTEGER NOT NULL DEFAULT 1")

    def _ensure_active_root_columns(self) -> None:
        columns = {row[1] for row in self._connection.execute("PRAGMA table_info(active_root_causes)").fetchall()}
        if "root_score" not in columns:
            self._connection.execute("ALTER TABLE active_root_causes ADD COLUMN root_score REAL NOT NULL DEFAULT 0")

    def _refresh_pending_rca_notification(self, incident: Incident, candidate: CandidateEvent) -> None:
        if candidate.detector_id != "rca_root_cause" or not _has_strong_trace_log_evidence(candidate):
            return
        message = NotificationBuilder().build([incident])[0]
        self._connection.execute(
            "UPDATE notification_outbox SET notification_json = ?, updated_at = ? WHERE incident_id = ? AND status IN ('pending', 'retry')",
            (message.model_dump_json(), _now(), incident.incident_id),
        )

    def _supplemental_rca_notification(self, incident: Incident, candidate: CandidateEvent) -> NotificationMessage | None:
        if candidate.detector_id != "rca_root_cause" or not _has_strong_trace_log_evidence(candidate):
            return None
        row = self._connection.execute(
            """
            SELECT notification_json, cycle
            FROM notification_outbox
            WHERE incident_id = ?
              AND status = 'sent'
              AND datetime(created_at, '+' || ? || ' seconds') >= CURRENT_TIMESTAMP
            """,
            (incident.incident_id, self.rca_dedup_seconds),
        ).fetchone()
        if row is None:
            return None
        original = NotificationMessage.model_validate_json(row[0])
        supplement_id = f"{incident.incident_id}{SUPPLEMENTAL_NOTIFICATION_SUFFIX}{int(row[1])}"
        if self._connection.execute("SELECT 1 FROM notification_outbox WHERE incident_id = ?", (supplement_id,)).fetchone():
            return None
        if _notification_has_strong_trace_log_evidence(original):
            return None
        message = NotificationBuilder().build([incident])[0]
        return message.model_copy(
            update={
                "incident_id": supplement_id,
                "title": f"Supplement: {message.title}",
                "summary": f"Supplement for {incident.incident_id}\n{message.summary}",
            }
        )


def _seen_at(candidate: CandidateEvent) -> str:
    return _candidate_seen_at(candidate).isoformat()


def _incident_from_json(payload: str) -> tuple[Incident, bool]:
    data = json.loads(payload)
    changed = False
    for event in data.get("events", []):
        if "unit" not in event:
            event["unit"] = "count"
            changed = True
        if "window" not in event:
            event["window"] = "unknown"
            changed = True
    return Incident.model_validate(data), changed


def _candidate_seen_at(candidate: CandidateEvent) -> datetime:
    if candidate.timestamp:
        return datetime.fromtimestamp(candidate.timestamp, UTC)
    return datetime.now(UTC)


def _events_in_window(events: list[CandidateEvent], candidate: CandidateEvent, window_seconds: int) -> list[CandidateEvent]:
    if window_seconds <= 0:
        return []
    current = _candidate_seen_at(candidate)
    window = timedelta(seconds=window_seconds)
    return [event for event in events if timedelta(0) <= current - _candidate_seen_at(event) < window]


def _ordered_notifications(rows: list[tuple[str]]) -> list[NotificationMessage]:
    messages = [NotificationMessage.model_validate_json(row[0]) for row in rows]
    return sorted(messages, key=lambda message: message.likely_dependency != "unknown")


def _severity_rank(severity: str) -> int:
    try:
        return int(severity.removeprefix("SEV"))
    except ValueError:
        return 999


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


def _has_strong_trace_log_evidence(candidate: CandidateEvent) -> bool:
    return any(STRONG_TRACE_MARKER in item.summary or STRONG_LOG_MARKER in item.summary for item in candidate.evidence)


def _notification_has_strong_trace_log_evidence(message: NotificationMessage) -> bool:
    return STRONG_TRACE_MARKER in message.summary or STRONG_LOG_MARKER in message.summary


def _default_runbooks_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "runbooks"


# Change trail: @hungxqt - 2026-07-28 - Ensure deterministic notification outbox tie-breaking by adding rowid ordering.
