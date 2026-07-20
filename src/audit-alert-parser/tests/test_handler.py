#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

import audit_alert_parser.handler as handler_module
from audit_alert_parser.handler import (
    CLOUDTRAIL_SOURCE,
    CLOUDWATCH_LOGS_SOURCE,
    UNKNOWN_SOURCE,
    classify_event,
    lambda_handler,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_cloudtrail_event_is_detected() -> None:
    event = load_fixture("cloudtrail-create-access-key.json")

    result = lambda_handler(event, None)

    assert classify_event(event) == CLOUDTRAIL_SOURCE
    assert result["status"] == "matched"
    assert result["source_type"] == CLOUDTRAIL_SOURCE
    assert result["summary"]["event_name"] == "CreateAccessKey"
    assert result["summary"]["matched_count"] == 1
    assert result["normalized_events"][0]["actor"] == "arn:aws:iam::493499579600:user/example"
    assert result["normalized_events"][0]["action"] == "CreateAccessKey"
    assert result["normalized_events"][0]["resource"] == "example"
    assert result["normalized_events"][0]["rule_id"] == "aws.iam.create_access_key"
    assert result["normalized_events"][0]["severity"] == "high"
    assert result["summary"]["alert_message_count"] == 1
    assert len(result["alert_messages"]) == 1
    assert "Tao IAM access key moi" in result["alert_messages"][0]
    assert result["evidence_records"][0]["status"] == "alert_ready"
    assert result["evidence_records"][0]["delivery_status"] == "pending_router_11_4"


def test_cloudwatch_logs_event_is_detected() -> None:
    event = load_fixture("cloudwatch-eks-secret-get.json")

    result = lambda_handler(event, None)

    assert classify_event(event) == CLOUDWATCH_LOGS_SOURCE
    assert result["status"] == "matched"
    assert result["source_type"] == CLOUDWATCH_LOGS_SOURCE
    assert result["summary"]["event_count"] == 1
    assert result["summary"]["matched_count"] == 1
    assert result["normalized_events"][0]["source_type"] == "kubernetes_audit"
    assert result["normalized_events"][0]["action"] == "get secrets"
    assert result["normalized_events"][0]["namespace"] == "techx-corp-prod"
    assert result["normalized_events"][0]["rule_id"] == "k8s.secret_access_unapproved"
    assert result["summary"]["alert_message_count"] == 1
    assert len(result["alert_messages"]) == 1
    assert "Doc Kubernetes Secret" in result["alert_messages"][0]
    assert result["evidence_records"][0]["status"] == "alert_ready"


def test_cloudwatch_control_message_is_ignored() -> None:
    event = load_fixture("cloudwatch-control-message.json")

    result = lambda_handler(event, None)

    assert classify_event(event) == CLOUDWATCH_LOGS_SOURCE
    assert result["status"] == "ignored"
    assert result["reason"] == "control_message_or_empty_payload"
    assert result["normalized_events"] == []
    assert result["alert_messages"] == []
    assert result["evidence_records"][0]["status"] == "ignored"
    assert result["evidence_records"][0]["reason"] == "control_message_or_empty_payload"


def test_unknown_event_shape_is_ignored() -> None:
    event = {"source": "manual-test"}

    result = lambda_handler(event, None)

    assert classify_event(event) == UNKNOWN_SOURCE
    assert result["status"] == "ignored"
    assert result["reason"] == "unsupported_event_shape"
    assert result["evidence_records"][0]["status"] == "ignored"
    assert result["evidence_records"][0]["reason"] == "unsupported_event_shape"


def test_non_dangerous_cloudtrail_event_is_ignored() -> None:
    event = load_fixture("cloudtrail-describe-cluster.json")

    result = lambda_handler(event, None)

    assert classify_event(event) == CLOUDTRAIL_SOURCE
    assert result["status"] == "ignored"
    assert result["reason"] == "not_dangerous_event"
    assert result["normalized_events"][0]["matched"] is False
    assert result["normalized_events"][0]["rule_id"] == "unmatched"
    assert result["alert_messages"] == []
    assert result["evidence_records"][0]["status"] == "ignored"
    assert result["evidence_records"][0]["reason"] == "not_dangerous_event"


def test_handler_alert_ready_evidence_has_deterministic_parser_ttd(
    monkeypatch,
) -> None:
    event = load_fixture("cloudtrail-create-access-key.json")
    timestamps = iter(["2026-07-18T08:10:25Z", "2026-07-18T08:10:35Z"])
    monkeypatch.setattr(handler_module, "utc_now_iso", lambda: next(timestamps))

    result = handler_module.lambda_handler(event, None)
    evidence = result["evidence_records"][0]

    assert result["phase"] == "phase_6_evidence_ttd"
    assert result["parser_received_time"] == "2026-07-18T08:10:25Z"
    assert result["alert_ready_time"] == "2026-07-18T08:10:35Z"
    assert evidence["status"] == "alert_ready"
    assert evidence["parser_received_time"] == "2026-07-18T08:10:25Z"
    assert evidence["alert_ready_time"] == "2026-07-18T08:10:35Z"
    assert evidence["parser_latency_seconds"] == 13
    assert evidence["alert_ready_latency_seconds"] == 10
    assert evidence["time_to_alert_ready_seconds"] == 23


def test_invalid_cloudwatch_payload_returns_parse_error() -> None:
    result = lambda_handler({"awslogs": {"data": "not-base64"}}, None)

    assert result["status"] == "parse_error"
    assert result["reason"] == "invalid_cloudwatch_logs_payload"
    assert result["summary"]["alert_message_count"] == 0
    assert result["alert_messages"] == []
    assert result["normalized_events"] == []
    assert result["evidence_records"][0]["status"] == "parse_error"
    assert result["evidence_records"][0]["error_message"] == "invalid_cloudwatch_logs_payload"


def test_cloudtrail_dangerous_event_with_missing_fields_does_not_crash() -> None:
    event = {
        "detail-type": "AWS API Call via CloudTrail",
        "source": "aws.iam",
        "account": "493499579600",
        "region": "us-east-1",
        "time": "2026-07-18T08:10:12Z",
        "detail": {
            "eventSource": "iam.amazonaws.com",
            "eventName": "CreateAccessKey",
            "requestParameters": {},
        },
    }

    result = lambda_handler(event, None)

    assert result["status"] == "matched"
    assert result["summary"]["matched_count"] == 1
    assert result["normalized_events"][0]["actor"] == "unknown"
    assert result["normalized_events"][0]["source_ip"] == "unknown"
    assert result["normalized_events"][0]["resource"] == "unknown"
    assert result["summary"]["alert_message_count"] == 1
    assert "Ai: unknown" in result["alert_messages"][0]
    assert "Tu dau: unknown" in result["alert_messages"][0]
    assert result["evidence_records"][0]["status"] == "alert_ready"
