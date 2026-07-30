# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


def utc_now_text() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class LiveExecutorStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS plans (
                plan_hash TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                action_id TEXT NOT NULL,
                target TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS executions (
                execution_id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                action_id TEXT NOT NULL,
                target TEXT NOT NULL,
                status TEXT NOT NULL,
                plan_hash TEXT,
                rollback_token TEXT,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._ensure_idempotency_schema()
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS target_cooldowns (
                target TEXT PRIMARY KEY,
                cooldown_until TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                event_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                request_id TEXT,
                incident_id TEXT,
                execution_id TEXT,
                action_id TEXT,
                event_type TEXT NOT NULL,
                actor_type TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                policy_id TEXT,
                allowed INTEGER NOT NULL,
                executed INTEGER NOT NULL,
                reasons_json TEXT NOT NULL,
                target_json TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def save_plan(self, response: dict[str, Any], binding: dict[str, Any]) -> None:
        now = utc_now_text()
        stored = {**response, "_binding": binding}
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO plans (plan_hash, incident_id, action_id, target, expires_at, response_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(plan_hash) DO UPDATE SET response_json = excluded.response_json
                """,
                (
                    response["plan_hash"],
                    response.get("incident_id", ""),
                    response["action_id"],
                    response["target"],
                    response.get("expires_at") or "",
                    json.dumps(stored, sort_keys=True),
                    now,
                ),
            )

    def get_plan_response(self, plan_hash: str) -> dict[str, Any] | None:
        row = self._connection.execute("SELECT response_json FROM plans WHERE plan_hash = ?", (plan_hash,)).fetchone()
        return json.loads(row["response_json"]) if row else None

    def save_execution(self, response: dict[str, Any], status: str) -> None:
        now = utc_now_text()
        execution_id = response.get("execution_id")
        if not execution_id:
            return
        stored = dict(response)
        stored["status"] = status
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO executions (
                    execution_id, incident_id, action_id, target, status, plan_hash, rollback_token, response_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(execution_id) DO UPDATE SET
                    status = excluded.status,
                    response_json = excluded.response_json,
                    updated_at = excluded.updated_at
                """,
                (
                    execution_id,
                    response.get("incident_id", ""),
                    response["action_id"],
                    response["target"],
                    status,
                    response.get("plan_hash"),
                    response.get("rollback_token"),
                    json.dumps(stored, sort_keys=True),
                    now,
                    now,
                ),
            )

    def get_execution_response(self, execution_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT response_json FROM executions WHERE execution_id = ?",
            (execution_id,),
        ).fetchone()
        return json.loads(row["response_json"]) if row else None

    def execution_for_target(self, target: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            """
            SELECT response_json FROM executions
            WHERE target = ? AND status = 'running'
            ORDER BY created_at DESC LIMIT 1
            """,
            (target,),
        ).fetchone()
        return json.loads(row["response_json"]) if row else None

    def execution_count_since(self, window_seconds: int) -> int:
        since = (datetime.now(UTC) - timedelta(seconds=max(0, window_seconds))).replace(
            microsecond=0
        ).isoformat().replace("+00:00", "Z")
        row = self._connection.execute(
            """
            SELECT COUNT(*) AS count FROM executions
            WHERE created_at >= ? AND status IN ('running', 'succeeded', 'failed', 'rolled_back')
            """,
            (since,),
        ).fetchone()
        return int(row["count"]) if row else 0

    def cooldown_active(self, target: str) -> bool:
        row = self._connection.execute(
            "SELECT cooldown_until FROM target_cooldowns WHERE target = ?",
            (target,),
        ).fetchone()
        if row is None:
            return False
        return datetime.fromisoformat(str(row["cooldown_until"]).replace("Z", "+00:00")) > datetime.now(UTC)

    def set_cooldown(self, target: str, seconds: int) -> None:
        now = datetime.now(UTC)
        cooldown_until = (now + timedelta(seconds=max(0, seconds))).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO target_cooldowns (target, cooldown_until, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(target) DO UPDATE SET
                    cooldown_until = excluded.cooldown_until,
                    updated_at = excluded.updated_at
                """,
                (target, cooldown_until, utc_now_text()),
            )

    def save_idempotency(self, key: str, operation: str, response: dict[str, Any]) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO idempotency_keys (idempotency_key, operation, response_json, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(idempotency_key, operation) DO NOTHING
                """,
                (key, operation, json.dumps(response, sort_keys=True), utc_now_text()),
            )

    def get_idempotency(self, key: str, operation: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT response_json FROM idempotency_keys WHERE idempotency_key = ? AND operation = ?",
            (key, operation),
        ).fetchone()
        return json.loads(row["response_json"]) if row else None

    def _ensure_idempotency_schema(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS idempotency_keys (
                idempotency_key TEXT NOT NULL,
                operation TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (idempotency_key, operation)
            )
            """
        )
        columns = self._connection.execute("PRAGMA table_info(idempotency_keys)").fetchall()
        primary_key_columns = [
            str(row["name"])
            for row in sorted(columns, key=lambda item: int(item["pk"]))
            if int(row["pk"]) > 0
        ]
        if primary_key_columns == ["idempotency_key", "operation"]:
            return

        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE idempotency_keys_v2 (
                    idempotency_key TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (idempotency_key, operation)
                )
                """
            )
            self._connection.execute(
                """
                INSERT OR IGNORE INTO idempotency_keys_v2 (
                    idempotency_key, operation, response_json, created_at
                )
                SELECT idempotency_key, operation, response_json, created_at
                FROM idempotency_keys
                """
            )
            self._connection.execute("DROP TABLE idempotency_keys")
            self._connection.execute("ALTER TABLE idempotency_keys_v2 RENAME TO idempotency_keys")

    def audit(self, event: dict[str, Any]) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO audit_events (
                    event_id, timestamp, request_id, incident_id, execution_id, action_id, event_type,
                    actor_type, actor_id, policy_id, allowed, executed, reasons_json, target_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["event_id"],
                    event["timestamp"],
                    event.get("request_id"),
                    event.get("incident_id"),
                    event.get("execution_id"),
                    event.get("action_id"),
                    event["event_type"],
                    event.get("actor_type", "service"),
                    event.get("actor_id", "aiops-runtime"),
                    event.get("policy_id"),
                    1 if event.get("allowed") else 0,
                    1 if event.get("executed") else 0,
                    json.dumps(event.get("reasons", []), sort_keys=True),
                    json.dumps(event.get("target", {}), sort_keys=True),
                ),
            )

    def audit_events_for(self, incident_id: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT event_id, timestamp, request_id, incident_id, execution_id,
                   action_id, event_type, actor_type, actor_id, policy_id,
                   allowed, executed, reasons_json, target_json
            FROM audit_events
            WHERE incident_id = ?
            ORDER BY timestamp, rowid
            """,
            (incident_id,),
        ).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "timestamp": row["timestamp"],
                "request_id": row["request_id"],
                "incident_id": row["incident_id"],
                "execution_id": row["execution_id"],
                "action_id": row["action_id"],
                "event_type": row["event_type"],
                "actor_type": row["actor_type"],
                "actor_id": row["actor_id"],
                "policy_id": row["policy_id"],
                "allowed": bool(row["allowed"]),
                "executed": bool(row["executed"]),
                "reasons": json.loads(row["reasons_json"]),
                "target": json.loads(row["target_json"]),
            }
            for row in rows
        ]

    def ready(self) -> bool:
        return self._connection.execute("SELECT 1").fetchone()[0] == 1

    def close(self) -> None:
        self._connection.close()
