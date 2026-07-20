#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Human-readable Vietnamese alert formatter for Mandate 11.3."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from .redaction import redact

ICT = ZoneInfo("Asia/Ho_Chi_Minh")
UNKNOWN = "unknown"
SAFETY_FOOTER = (
    "Khong paste secret, token, password, webhook URL, payment data, PII "
    "hoac raw log vao kenh chat."
)


def format_audit_message(normalized_event: Mapping[str, Any]) -> str:
    """Format one alert candidate into safe Vietnamese text.

    The formatter intentionally does not print raw JSON or raw attributes. If a
    detail is missing, it prints `unknown` instead of failing the alert path.
    """

    event = _redacted_mapping(normalized_event)
    severity = _field(event, "severity").upper()
    service = _field(event, "service")
    action = _field(event, "action")
    title = _field(event, "title_vi", "Phat hien hanh dong audit nguy hiem")
    event_time = _format_ict_time(_field(event, "event_time_utc"))
    request_or_audit_id = _field(event, "request_id", "") or _field(event, "audit_id", "")

    lines = [
        f"[{severity}] {title}",
        "",
        f"Moi truong: {_field(event, 'environment')}",
        f"Rule: {_field(event, 'rule_id')}",
        f"Muc do: {_field(event, 'severity')}",
        "",
        f"Ai: {_field(event, 'actor')}",
        f"Lam gi: {_format_action(action, service)}",
        f"Luc nao: {event_time}",
        f"Tu dau: {_field(event, 'source_ip')}",
        "",
        f"Tai nguyen: {_field(event, 'resource')}",
        f"Namespace: {_field(event, 'namespace')}",
        f"Cluster: {_field(event, 'cluster_name')}",
        f"Account/Region: {_field(event, 'account_id')} / {_field(event, 'region')}",
        f"User agent: {_field(event, 'user_agent')}",
        f"Request/Audit ID: {request_or_audit_id or UNKNOWN}",
        "",
        f"Tac dong: {_field(event, 'impact_vi')}",
        f"Buoc dau tien: {_field(event, 'first_action_vi')}",
    ]

    allowlist_error = _field(event, "allowlist_error", "")
    if allowlist_error:
        lines.extend(["", f"Luu y allowlist: {allowlist_error}"])

    lines.extend(["", SAFETY_FOOTER])
    return "\n".join(lines)


def format_alert_messages(normalized_events: Sequence[Mapping[str, Any]]) -> list[str]:
    """Format only dangerous events that were not suppressed by allowlist."""

    messages: list[str] = []
    for event in normalized_events:
        if event.get("matched") is True and event.get("suppressed") is not True:
            messages.append(format_audit_message(event))
    return messages


def _redacted_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    redacted = redact(value)
    return redacted if isinstance(redacted, Mapping) else {}


def _field(event: Mapping[str, Any], key: str, default: str = UNKNOWN) -> str:
    value = event.get(key)
    if value is None:
        return default

    text = str(value).strip()
    return text if text else default


def _format_action(action: str, service: str) -> str:
    if service == UNKNOWN:
        return action
    return f"{action} tren {service}"


def _format_ict_time(value: str) -> str:
    if value == UNKNOWN:
        return UNKNOWN

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)

    return parsed.astimezone(ICT).strftime("%d/%m/%Y %H:%M:%S ICT")
