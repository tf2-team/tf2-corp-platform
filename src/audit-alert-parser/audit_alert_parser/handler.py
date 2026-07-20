#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""AWS Lambda entry point for the Mandate 11 audit alert parser."""

from __future__ import annotations

import json
from typing import Any, Mapping

from .allowlist import apply_allowlist
from .cloudtrail import cloudtrail_summary, is_cloudtrail_event, normalize_cloudtrail_event
from .eks_audit import is_cloudwatch_logs_event, normalize_cloudwatch_logs_event
from .evidence import build_evidence_record
from .formatter import format_alert_messages
from .rules import apply_rule_match
from .ttd import utc_now_iso

CLOUDTRAIL_SOURCE = "cloudtrail"
CLOUDWATCH_LOGS_SOURCE = "cloudwatch_logs"
UNKNOWN_SOURCE = "unknown"


def classify_event(event: Mapping[str, Any]) -> str:
    """Return the supported source type for an incoming Lambda event."""

    if is_cloudtrail_event(event):
        return CLOUDTRAIL_SOURCE

    if is_cloudwatch_logs_event(event):
        return CLOUDWATCH_LOGS_SOURCE

    return UNKNOWN_SOURCE


def lambda_handler(event: Mapping[str, Any], context: Any = None) -> dict[str, Any]:
    """Lambda handler used by Phase 6 evidence and TTD validation."""

    parser_received_time = utc_now_iso()
    source_type = classify_event(event)
    response: dict[str, Any] = {
        "phase": "phase_6_evidence_ttd",
        "source_type": source_type,
        "status": "accepted" if source_type != UNKNOWN_SOURCE else "ignored",
        "parser_received_time": parser_received_time,
        "alert_messages": [],
        "evidence_records": [],
        "normalized_events": [],
    }

    try:
        if source_type == CLOUDTRAIL_SOURCE:
            normalized_event = apply_allowlist(
                apply_rule_match(normalize_cloudtrail_event(event))
            )
            normalized_events = [normalized_event]
            response["summary"] = cloudtrail_summary(event)
            response["summary"].update(_allowlist_summary(normalized_events))
            normalized_event_dicts = [item.to_dict() for item in normalized_events]
            response["normalized_events"] = normalized_event_dicts
            response["alert_messages"] = format_alert_messages(normalized_event_dicts)
            response["summary"]["alert_message_count"] = len(response["alert_messages"])
            _set_status_from_events(response, normalized_events, empty_reason=None)
            response["evidence_records"] = _event_evidence_records(
                normalized_events,
                parser_received_time=parser_received_time,
                alert_ready_time=_alert_ready_time(response),
                ignored_reason=response.get("reason"),
            )
            return _finalize_response(response)

        if source_type == CLOUDWATCH_LOGS_SOURCE:
            normalized_events = [
                apply_allowlist(apply_rule_match(item))
                for item in normalize_cloudwatch_logs_event(event)
            ]
            response["summary"] = {
                "event_count": len(normalized_events),
                **_allowlist_summary(normalized_events),
            }
            normalized_event_dicts = [item.to_dict() for item in normalized_events]
            response["normalized_events"] = normalized_event_dicts
            response["alert_messages"] = format_alert_messages(normalized_event_dicts)
            response["summary"]["alert_message_count"] = len(response["alert_messages"])
            _set_status_from_events(
                response,
                normalized_events,
                empty_reason="control_message_or_empty_payload",
            )
            response["evidence_records"] = _event_evidence_records(
                normalized_events,
                parser_received_time=parser_received_time,
                alert_ready_time=_alert_ready_time(response),
                ignored_reason=response.get("reason"),
            )
            if not normalized_events:
                response["evidence_records"] = [
                    build_evidence_record(
                        "ignored",
                        parser_received_time=parser_received_time,
                        source_type=source_type,
                        reason=response["reason"],
                    )
                ]
            return _finalize_response(response)
    except ValueError as error:
        return _parse_error_response(response, source_type, parser_received_time, error)

    response["reason"] = "unsupported_event_shape"
    response["evidence_records"] = [
        build_evidence_record(
            "ignored",
            parser_received_time=parser_received_time,
            source_type=source_type,
            reason=response["reason"],
        )
    ]
    return _finalize_response(response)


def _finalize_response(response: dict[str, Any]) -> dict[str, Any]:
    _emit_evidence_records(response.get("evidence_records", []))
    return response


def _emit_evidence_records(evidence_records: Any) -> None:
    if not isinstance(evidence_records, list):
        return

    for record in evidence_records:
        if isinstance(record, Mapping):
            print(
                json.dumps(
                    record,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )


def _allowlist_summary(normalized_events: list[Any]) -> dict[str, int]:
    matched_count = sum(1 for item in normalized_events if item.matched)
    suppressed_count = sum(1 for item in normalized_events if item.suppressed)
    allowlist_error_count = sum(1 for item in normalized_events if item.allowlist_error)

    return {
        "matched_count": matched_count,
        "suppressed_count": suppressed_count,
        "alert_candidate_count": matched_count - suppressed_count,
        "ignored_count": len(normalized_events) - matched_count,
        "allowlist_error_count": allowlist_error_count,
    }


def _set_status_from_events(
    response: dict[str, Any],
    normalized_events: list[Any],
    *,
    empty_reason: str | None,
) -> None:
    if not normalized_events:
        response["status"] = "ignored"
        response["reason"] = empty_reason or "empty_payload"
    elif response["summary"]["alert_candidate_count"]:
        response["status"] = "matched"
        response["alert_ready_time"] = utc_now_iso()
    elif response["summary"]["suppressed_count"]:
        response["status"] = "suppressed"
        response["reason"] = "allowlisted"
    else:
        response["status"] = "ignored"
        response["reason"] = "not_dangerous_event"


def _alert_ready_time(response: Mapping[str, Any]) -> str | None:
    value = response.get("alert_ready_time")
    return value if isinstance(value, str) else None


def _event_evidence_records(
    normalized_events: list[Any],
    *,
    parser_received_time: str,
    alert_ready_time: str | None,
    ignored_reason: Any,
) -> list[dict[str, Any]]:
    evidence_records: list[dict[str, Any]] = []
    alert_message_index = 0

    for item in normalized_events:
        event_dict = item.to_dict()
        if item.matched and item.suppressed:
            evidence_records.append(
                build_evidence_record(
                    "suppressed",
                    event_dict,
                    parser_received_time=parser_received_time,
                    allowlist_id=item.allowlist_id,
                    allowlist_reason=item.allowlist_reason,
                    allowlist_owner=item.allowlist_owner,
                    allowlist_ticket=item.allowlist_ticket,
                    allowlist_review_after=item.allowlist_review_after,
                )
            )
        elif item.matched:
            evidence_records.append(
                build_evidence_record(
                    "alert_ready",
                    event_dict,
                    parser_received_time=parser_received_time,
                    alert_ready_time=alert_ready_time,
                    alert_message_index=alert_message_index,
                    delivery_status="pending_router_11_4",
                    allowlist_error=item.allowlist_error,
                )
            )
            alert_message_index += 1
        else:
            evidence_records.append(
                build_evidence_record(
                    "ignored",
                    event_dict,
                    parser_received_time=parser_received_time,
                    reason=ignored_reason or "not_dangerous_event",
                )
            )

    return evidence_records


def _parse_error_response(
    response: dict[str, Any],
    source_type: str,
    parser_received_time: str,
    error: ValueError,
) -> dict[str, Any]:
    response["status"] = "parse_error"
    response["reason"] = str(error)
    response["summary"] = {
        "event_count": 0,
        "matched_count": 0,
        "suppressed_count": 0,
        "alert_candidate_count": 0,
        "ignored_count": 0,
        "allowlist_error_count": 0,
        "alert_message_count": 0,
    }
    response["evidence_records"] = [
        build_evidence_record(
            "parse_error",
            parser_received_time=parser_received_time,
            source_type=source_type,
            error_type=error.__class__.__name__,
            error_message=str(error),
        )
    ]
    return _finalize_response(response)
