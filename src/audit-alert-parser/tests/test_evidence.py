#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from audit_alert_parser.cloudtrail import normalize_cloudtrail_event
from audit_alert_parser.evidence import build_evidence_record
from audit_alert_parser.rules import apply_rule_match
from audit_alert_parser.ttd import safe_seconds_between, seconds_between

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_build_alert_ready_evidence_has_parser_side_ttd_fields() -> None:
    normalized = apply_rule_match(
        normalize_cloudtrail_event(load_fixture("cloudtrail-create-access-key.json"))
    )

    record = build_evidence_record(
        "alert_ready",
        normalized.to_dict(),
        parser_received_time="2026-07-18T08:10:25Z",
        alert_ready_time="2026-07-18T08:10:35Z",
        recorded_at="2026-07-18T08:10:35Z",
        delivery_status="pending_router_11_4",
    )

    assert record["schema_version"] == "audit-detection-evidence/v1"
    assert record["event"] == "audit_detection_evidence"
    assert record["status"] == "alert_ready"
    assert record["rule_id"] == "aws.iam.create_access_key"
    assert record["parser_latency_seconds"] == 13
    assert record["alert_ready_latency_seconds"] == 10
    assert record["time_to_alert_ready_seconds"] == 23
    assert record["delivery_status"] == "pending_router_11_4"


def test_build_suppressed_evidence_has_allowlist_context() -> None:
    normalized = apply_rule_match(
        normalize_cloudtrail_event(load_fixture("cloudtrail-associate-access-policy.json"))
    )

    record = build_evidence_record(
        "suppressed",
        normalized.to_dict(),
        parser_received_time="2026-07-18T08:12:20Z",
        allowlist_id="ci-terraform-approved-eks-access",
        allowlist_owner="cdo06",
        allowlist_ticket="TF4-M11-ALLOW-001",
    )

    assert record["status"] == "suppressed"
    assert record["resource"] == "techx-tf2"
    assert record["allowlist_id"] == "ci-terraform-approved-eks-access"
    assert record["allowlist_owner"] == "cdo06"
    assert record["allowlist_ticket"] == "TF4-M11-ALLOW-001"


def test_safe_seconds_between_returns_none_for_unknown_timestamps() -> None:
    assert seconds_between("2026-07-18T08:10:12Z", "2026-07-18T08:10:35Z") == 23
    assert safe_seconds_between("unknown", "2026-07-18T08:10:35Z") is None
    assert safe_seconds_between(None, "2026-07-18T08:10:35Z") is None
