from __future__ import annotations

import base64
import gzip
import json
from pathlib import Path

import pytest

import audit_alert_parser.allowlist as allowlist_module
from audit_alert_parser.allowlist import AllowlistConfig, AllowlistEntry
from audit_alert_parser.handler import lambda_handler

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def cloudwatch_payload(*audit_events: dict) -> dict:
    payload = {
        "messageType": "DATA_MESSAGE",
        "owner": "493499579600",
        "logGroup": "/aws/eks/techx-tf2/cluster",
        "logStream": "kube-apiserver-audit",
        "subscriptionFilters": ["mandate-11-audit-filter"],
        "logEvents": [
            {
                "id": f"event-{index}",
                "timestamp": 1784515200000 + index,
                "message": json.dumps(audit_event, separators=(",", ":")),
            }
            for index, audit_event in enumerate(audit_events, start=1)
        ],
    }
    encoded = base64.b64encode(gzip.compress(json.dumps(payload).encode("utf-8")))
    return {"awslogs": {"data": encoded.decode("ascii")}}


@pytest.mark.parametrize(
    ("fixture", "status", "rule_id", "severity", "evidence_status"),
    [
        (
            "cloudtrail-create-access-key.json",
            "matched",
            "aws.iam.create_access_key",
            "high",
            "alert_ready",
        ),
        (
            "cloudtrail-admin-policy-change.json",
            "matched",
            "aws.iam.admin_policy_change",
            "critical",
            "alert_ready",
        ),
        (
            "cloudtrail-attach-custom-policy.json",
            "matched",
            "aws.iam.policy_attach_requires_review",
            "high",
            "alert_ready",
        ),
        (
            "cloudtrail-create-policy-high-risk.json",
            "matched",
            "aws.iam.admin_policy_change",
            "critical",
            "alert_ready",
        ),
        (
            "cloudtrail-create-policy-low-risk.json",
            "matched",
            "aws.iam.policy_mutation_requires_review",
            "high",
            "alert_ready",
        ),
        (
            "cloudtrail-create-access-entry.json",
            "matched",
            "aws.eks.access_entry_created",
            "critical",
            "alert_ready",
        ),
        (
            "cloudtrail-associate-access-policy.json",
            "matched",
            "aws.eks.cluster_admin_access",
            "critical",
            "alert_ready",
        ),
        (
            "cloudtrail-update-cluster-config-disable-audit.json",
            "matched",
            "aws.eks.audit_logging_disabled",
            "critical",
            "alert_ready",
        ),
        (
            "cloudtrail-stop-logging.json",
            "matched",
            "aws.cloudtrail.logging_changed",
            "critical",
            "alert_ready",
        ),
        (
            "cloudtrail-describe-cluster.json",
            "ignored",
            "unmatched",
            "unknown",
            "ignored",
        ),
    ],
)
def test_cloudtrail_eventbridge_mentor_usecases(
    fixture: str,
    status: str,
    rule_id: str,
    severity: str,
    evidence_status: str,
) -> None:
    result = lambda_handler(load_fixture(fixture), None)

    assert result["source_type"] == "cloudtrail"
    assert result["status"] == status
    assert result["normalized_events"][0]["rule_id"] == rule_id
    assert result["normalized_events"][0]["severity"] == severity
    assert result["evidence_records"][0]["status"] == evidence_status
    if status == "matched":
        assert result["summary"]["alert_message_count"] == 1
        assert result["alert_messages"]
    else:
        assert result["alert_messages"] == []


@pytest.mark.parametrize(
    ("audit_event", "rule_id", "severity"),
    [
        (
            load_fixture("eks-secret-get.audit.json"),
            "k8s.secret_access_unapproved",
            "high",
        ),
        (
            load_fixture("eks-clusterrolebinding-admin.audit.json"),
            "k8s.rbac.cluster_admin_binding",
            "critical",
        ),
        (
            {
                "verb": "create",
                "user": {"username": "arn:aws:iam::493499579600:user/operator"},
                "objectRef": {
                    "resource": "pods",
                    "subresource": "exec",
                    "namespace": "techx-corp-prod",
                    "name": "checkout-abc",
                },
                "sourceIPs": ["203.0.113.21"],
                "auditID": "audit-pod-exec",
            },
            "k8s.pod_exec_production",
            "high",
        ),
        (
            {
                "verb": "create",
                "user": {"username": "arn:aws:iam::493499579600:user/operator"},
                "objectRef": {
                    "resource": "deployments",
                    "namespace": "techx-corp-prod",
                    "name": "debug-tools",
                },
                "requestObject": {
                    "spec": {
                        "template": {
                            "spec": {
                                "hostPID": True,
                                "volumes": [
                                    {"name": "host-root", "hostPath": {"path": "/"}}
                                ],
                                "containers": [
                                    {
                                        "name": "debug",
                                        "securityContext": {"privileged": True},
                                    }
                                ],
                            }
                        }
                    }
                },
                "auditID": "audit-privileged",
            },
            "k8s.privileged_workload_requested",
            "critical",
        ),
        (
            {
                "verb": "delete",
                "user": {"username": "arn:aws:iam::493499579600:user/operator"},
                "objectRef": {
                    "resource": "deployments",
                    "namespace": "techx-corp-prod",
                    "name": "checkout",
                },
                "auditID": "audit-delete-prod",
            },
            "k8s.production_resource_deleted",
            "high",
        ),
    ],
)
def test_kubernetes_cloudwatch_logs_mentor_usecases(
    audit_event: dict,
    rule_id: str,
    severity: str,
) -> None:
    result = lambda_handler(cloudwatch_payload(audit_event), None)

    assert result["source_type"] == "cloudwatch_logs"
    assert result["status"] == "matched"
    assert result["summary"]["event_count"] == 1
    assert result["summary"]["matched_count"] == 1
    assert result["summary"]["alert_message_count"] == 1
    assert result["normalized_events"][0]["rule_id"] == rule_id
    assert result["normalized_events"][0]["severity"] == severity
    assert result["evidence_records"][0]["status"] == "alert_ready"
    assert result["alert_messages"]


def test_kubernetes_cloudwatch_logs_batch_keeps_one_evidence_per_event() -> None:
    result = lambda_handler(
        cloudwatch_payload(
            load_fixture("eks-secret-get.audit.json"),
            {
                "verb": "create",
                "user": {"username": "arn:aws:iam::493499579600:user/operator"},
                "objectRef": {
                    "resource": "pods",
                    "subresource": "exec",
                    "namespace": "techx-corp-prod",
                    "name": "checkout-abc",
                },
                "auditID": "audit-pod-exec",
            },
            {
                "verb": "delete",
                "user": {"username": "arn:aws:iam::493499579600:user/operator"},
                "objectRef": {
                    "resource": "configmaps",
                    "namespace": "techx-corp-prod",
                    "name": "feature-flags",
                },
                "auditID": "audit-delete-config",
            },
        ),
        None,
    )

    assert result["status"] == "matched"
    assert result["summary"]["event_count"] == 3
    assert result["summary"]["matched_count"] == 3
    assert result["summary"]["alert_message_count"] == 3
    assert len(result["evidence_records"]) == 3
    assert {record["status"] for record in result["evidence_records"]} == {"alert_ready"}


def test_approved_policy_attach_is_suppressed_with_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AllowlistConfig(
        environment="production",
        entries=(
            AllowlistEntry(
                id="approved-human-policy-attach-test",
                enabled=True,
                owner="cdo06",
                reason="Mentor test entry for approved policy attach suppression.",
                ticket="TF4-M11-ALLOW-TEST",
                review_after="2026-08-20",
                rule_ids=("aws.iam.policy_attach_requires_review",),
                actor_patterns=("arn:aws:iam::493499579600:user/human-operator",),
                actions=("iam.amazonaws.com:AttachRolePolicy",),
                resource_patterns=("prod-support-role",),
                user_agent_patterns=("signin.amazonaws.com",),
            ),
        ),
    )
    monkeypatch.setattr(allowlist_module, "load_allowlist", lambda: config)

    result = lambda_handler(load_fixture("cloudtrail-attach-custom-policy.json"), None)

    assert result["status"] == "suppressed"
    assert result["reason"] == "allowlisted"
    assert result["summary"]["alert_message_count"] == 0
    assert result["alert_messages"] == []
    assert result["evidence_records"][0]["status"] == "suppressed"
    assert result["evidence_records"][0]["allowlist_id"] == "approved-human-policy-attach-test"


def test_eks_audit_logging_disabled_is_never_suppressed_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AllowlistConfig(
        environment="production",
        entries=(
            AllowlistEntry(
                id="bad-eks-logging-suppression-test",
                enabled=True,
                owner="platform",
                reason="This must not suppress audit logging disablement.",
                ticket="TF4-M11-ALLOW-TEST",
                review_after="2026-08-20",
                rule_ids=("aws.eks.audit_logging_disabled",),
                actor_patterns=("arn:aws:iam::493499579600:user/human-operator",),
                actions=("eks.amazonaws.com:UpdateClusterConfig",),
                resource_patterns=("techx-tf2",),
            ),
        ),
    )
    monkeypatch.setattr(allowlist_module, "load_allowlist", lambda: config)

    result = lambda_handler(
        load_fixture("cloudtrail-update-cluster-config-disable-audit.json"),
        None,
    )

    assert result["status"] == "matched"
    assert result["normalized_events"][0]["rule_id"] == "aws.eks.audit_logging_disabled"
    assert result["normalized_events"][0]["suppressed"] is False
    assert result["evidence_records"][0]["status"] == "alert_ready"


def test_evidence_records_are_emitted_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    result = lambda_handler(load_fixture("cloudtrail-create-access-key.json"), None)

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    assert result["evidence_records"][0]["status"] == "alert_ready"
    assert len(lines) == 1
    assert lines[0]["event"] == "audit_detection_evidence"
    assert lines[0]["status"] == "alert_ready"
    assert lines[0]["rule_id"] == "aws.iam.create_access_key"


def test_parse_error_evidence_is_emitted_to_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = lambda_handler({"awslogs": {"data": "not-base64"}}, None)

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    assert result["status"] == "parse_error"
    assert len(lines) == 1
    assert lines[0]["event"] == "audit_detection_evidence"
    assert lines[0]["status"] == "parse_error"
    assert lines[0]["error_message"] == "invalid_cloudwatch_logs_payload"
