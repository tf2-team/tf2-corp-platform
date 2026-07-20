from __future__ import annotations

import json
from pathlib import Path

import pytest

from audit_alert_parser.cloudtrail import normalize_cloudtrail_event
from audit_alert_parser.eks_audit import (
    decode_cloudwatch_logs_event,
    iter_kubernetes_audit_events,
    normalize_cloudwatch_logs_event,
    normalize_kubernetes_audit_event,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_normalize_cloudtrail_access_key_event() -> None:
    normalized = normalize_cloudtrail_event(
        load_fixture("cloudtrail-create-access-key.json")
    )

    assert normalized.source_type == "cloudtrail"
    assert normalized.actor == "arn:aws:iam::493499579600:user/example"
    assert normalized.action == "CreateAccessKey"
    assert normalized.service == "iam.amazonaws.com"
    assert normalized.resource == "example"
    assert normalized.event_time_utc == "2026-07-18T08:10:12Z"
    assert normalized.source_ip == "203.0.113.10"
    assert normalized.account_id == "493499579600"
    assert normalized.region == "us-east-1"
    assert normalized.request_id == "request-id"
    assert normalized.event_id == "event-id"


def test_normalize_cloudtrail_eks_cluster_access_event() -> None:
    normalized = normalize_cloudtrail_event(
        load_fixture("cloudtrail-associate-access-policy.json")
    )

    assert normalized.service == "eks.amazonaws.com"
    assert normalized.action == "AssociateAccessPolicy"
    assert normalized.resource == "techx-tf2"
    assert normalized.cluster_name == "techx-tf2"
    assert normalized.user_agent == "Terraform/1.13"


def test_decode_cloudwatch_logs_data_message() -> None:
    payload = decode_cloudwatch_logs_event(load_fixture("cloudwatch-eks-secret-get.json"))

    assert payload["messageType"] == "DATA_MESSAGE"
    assert payload["logGroup"] == "/aws/eks/techx-tf2/cluster"
    assert len(payload["logEvents"]) == 1


def test_iter_kubernetes_audit_events_from_cloudwatch_logs() -> None:
    audit_events = iter_kubernetes_audit_events(
        load_fixture("cloudwatch-eks-secret-get.json")
    )

    assert len(audit_events) == 1
    assert audit_events[0]["verb"] == "get"
    assert audit_events[0]["objectRef"]["resource"] == "secrets"


def test_normalize_kubernetes_audit_event() -> None:
    normalized = normalize_kubernetes_audit_event(
        load_fixture("eks-secret-get.audit.json"),
        account_id="493499579600",
        cluster_name="techx-tf2",
    )

    assert normalized.source_type == "kubernetes_audit"
    assert normalized.actor == "arn:aws:iam::493499579600:user/example"
    assert normalized.action == "get secrets"
    assert normalized.resource == "grafana-secret"
    assert normalized.namespace == "techx-corp-prod"
    assert normalized.source_ip == "203.0.113.10"
    assert normalized.user_agent == "kubectl/v1.33"
    assert normalized.audit_id == "audit-id"
    assert normalized.account_id == "493499579600"
    assert normalized.cluster_name == "techx-tf2"


def test_normalize_cloudwatch_logs_payload_adds_cluster_metadata() -> None:
    normalized_events = normalize_cloudwatch_logs_event(
        load_fixture("cloudwatch-eks-secret-get.json")
    )

    assert len(normalized_events) == 1
    assert normalized_events[0].cluster_name == "techx-tf2"
    assert normalized_events[0].account_id == "493499579600"


def test_cloudwatch_control_message_has_no_audit_events() -> None:
    assert iter_kubernetes_audit_events(load_fixture("cloudwatch-control-message.json")) == []
    assert normalize_cloudwatch_logs_event(load_fixture("cloudwatch-control-message.json")) == []


def test_invalid_cloudwatch_payload_is_rejected() -> None:
    with pytest.raises(ValueError, match="invalid_cloudwatch_logs_payload"):
        decode_cloudwatch_logs_event({"awslogs": {"data": "not-base64"}})
