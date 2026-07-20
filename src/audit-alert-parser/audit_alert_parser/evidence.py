"""Structured evidence record helpers."""

from __future__ import annotations

from typing import Any, Mapping

from .ttd import safe_seconds_between, utc_now_iso


def build_evidence_record(
    status: str,
    normalized_event: Mapping[str, Any] | None = None,
    *,
    parser_received_time: str | None = None,
    alert_ready_time: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    recorded_at = extra.pop("recorded_at", None) or utc_now_iso()
    record: dict[str, Any] = {
        "schema_version": "audit-detection-evidence/v1",
        "event": "audit_detection_evidence",
        "status": status,
        "recorded_at": recorded_at,
    }

    if parser_received_time:
        record["parser_received_time"] = parser_received_time

    if alert_ready_time:
        record["alert_ready_time"] = alert_ready_time

    if normalized_event:
        for key in (
            "rule_id",
            "severity",
            "actor",
            "action",
            "resource",
            "namespace",
            "source_ip",
            "event_time_utc",
            "request_id",
            "audit_id",
            "account_id",
            "region",
            "cluster_name",
        ):
            if key in normalized_event:
                record[key] = normalized_event[key]

    # These latency fields are parser-side measurements only. The final
    # Discord/on-call TTD must be completed by the router in Task 11.4/11.5.
    event_time = record.get("event_time_utc")
    parser_latency_seconds = safe_seconds_between(event_time, parser_received_time)
    if parser_latency_seconds is not None:
        record["parser_latency_seconds"] = parser_latency_seconds

    alert_ready_latency_seconds = safe_seconds_between(parser_received_time, alert_ready_time)
    if alert_ready_latency_seconds is not None:
        record["alert_ready_latency_seconds"] = alert_ready_latency_seconds

    time_to_alert_ready_seconds = safe_seconds_between(event_time, alert_ready_time)
    if time_to_alert_ready_seconds is not None:
        record["time_to_alert_ready_seconds"] = time_to_alert_ready_seconds

    record.update(extra)
    return record
