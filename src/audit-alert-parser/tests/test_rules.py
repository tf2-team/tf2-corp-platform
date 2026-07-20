#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from audit_alert_parser.cloudtrail import normalize_cloudtrail_event
from audit_alert_parser.eks_audit import normalize_kubernetes_audit_event
from audit_alert_parser.rules import apply_rule_match, load_rules, match_rule

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_rules_config_loads_expected_mandate_11_rules() -> None:
    rule_ids = {rule.id for rule in load_rules()}

    assert "aws.iam.create_access_key" in rule_ids
    assert "aws.iam.admin_policy_change" in rule_ids
    assert "aws.iam.policy_attach_requires_review" in rule_ids
    assert "aws.iam.policy_mutation_requires_review" in rule_ids
    assert "aws.iam.interactive_identity_access_changed" in rule_ids
    assert "aws.eks.access_entry_created" in rule_ids
    assert "aws.eks.cluster_admin_access" in rule_ids
    assert "aws.eks.audit_logging_disabled" in rule_ids
    assert "aws.cloudtrail.logging_changed" in rule_ids
    assert "k8s.rbac.cluster_admin_binding" in rule_ids
    assert "k8s.secret_access_unapproved" in rule_ids
    assert "k8s.pod_exec_production" in rule_ids
    assert "k8s.privileged_workload_requested" in rule_ids
    assert "k8s.production_resource_deleted" in rule_ids


def test_create_access_key_matches_high_severity_rule() -> None:
    normalized = normalize_cloudtrail_event(
        load_fixture("cloudtrail-create-access-key.json")
    )

    matched = apply_rule_match(normalized)

    assert matched.matched is True
    assert matched.rule_id == "aws.iam.create_access_key"
    assert matched.severity == "high"
    assert matched.title_vi == "Tao IAM access key moi"


def test_admin_policy_change_requires_admin_policy() -> None:
    normalized = normalize_cloudtrail_event(
        load_fixture("cloudtrail-admin-policy-change.json")
    )

    matched = apply_rule_match(normalized)

    assert matched.matched is True
    assert matched.rule_id == "aws.iam.admin_policy_change"
    assert matched.severity == "critical"
    assert matched.attributes["admin_policy_requested"] is True


def test_attach_custom_policy_matches_zero_trust_review_rule() -> None:
    normalized = normalize_cloudtrail_event(
        load_fixture("cloudtrail-attach-custom-policy.json")
    )

    matched = apply_rule_match(normalized)

    assert matched.matched is True
    assert matched.rule_id == "aws.iam.policy_attach_requires_review"
    assert matched.severity == "high"
    assert matched.attributes["admin_policy_requested"] is False


def test_create_policy_with_high_risk_document_matches_critical_rule() -> None:
    normalized = normalize_cloudtrail_event(
        load_fixture("cloudtrail-create-policy-high-risk.json")
    )

    matched = apply_rule_match(normalized)

    assert matched.matched is True
    assert matched.rule_id == "aws.iam.admin_policy_change"
    assert matched.severity == "critical"
    assert matched.resource == "a"
    assert matched.attributes["policy_document_high_risk"] is True
    assert "high_risk_action_prefix:iam:*" in matched.attributes["policy_document_risks"]


def test_create_low_risk_policy_still_requires_review() -> None:
    normalized = normalize_cloudtrail_event(
        load_fixture("cloudtrail-create-policy-low-risk.json")
    )

    matched = apply_rule_match(normalized)

    assert matched.matched is True
    assert matched.rule_id == "aws.iam.policy_mutation_requires_review"
    assert matched.severity == "high"
    assert matched.attributes["policy_document_high_risk"] is False


def test_create_access_entry_matches_critical_rule() -> None:
    normalized = normalize_cloudtrail_event(
        load_fixture("cloudtrail-create-access-entry.json")
    )

    matched = apply_rule_match(normalized)

    assert matched.matched is True
    assert matched.rule_id == "aws.eks.access_entry_created"
    assert matched.severity == "critical"


def test_eks_audit_logging_disabled_matches_critical_rule() -> None:
    normalized = normalize_cloudtrail_event(
        load_fixture("cloudtrail-update-cluster-config-disable-audit.json")
    )

    matched = apply_rule_match(normalized)

    assert matched.matched is True
    assert matched.rule_id == "aws.eks.audit_logging_disabled"
    assert matched.severity == "critical"
    assert matched.attributes["eks_audit_logging_disabled"] is True
    assert matched.attributes["disabled_cluster_log_types"] == ["api", "audit"]


def test_eks_cluster_admin_access_matches_policy_arn_condition() -> None:
    normalized = normalize_cloudtrail_event(
        load_fixture("cloudtrail-associate-access-policy.json")
    )

    matched = apply_rule_match(normalized)

    assert matched.matched is True
    assert matched.rule_id == "aws.eks.cluster_admin_access"
    assert matched.severity == "critical"
    assert matched.resource == "techx-tf2"


def test_cloudtrail_logging_change_matches_critical_rule() -> None:
    normalized = normalize_cloudtrail_event(
        load_fixture("cloudtrail-stop-logging.json")
    )

    matched = apply_rule_match(normalized)

    assert matched.matched is True
    assert matched.rule_id == "aws.cloudtrail.logging_changed"
    assert matched.severity == "critical"


def test_kubernetes_secret_access_matches_high_rule() -> None:
    normalized = normalize_kubernetes_audit_event(
        load_fixture("eks-secret-get.audit.json"),
        account_id="493499579600",
        cluster_name="techx-tf2",
    )

    matched = apply_rule_match(normalized)

    assert matched.matched is True
    assert matched.rule_id == "k8s.secret_access_unapproved"
    assert matched.severity == "high"


def test_kubernetes_secret_access_with_missing_optional_fields_still_matches() -> None:
    normalized = normalize_kubernetes_audit_event(
        {
            "verb": "get",
            "objectRef": {
                "resource": "secrets",
                "namespace": "techx-corp-prod",
            },
        },
        account_id="493499579600",
        cluster_name="techx-tf2",
    )

    matched = apply_rule_match(normalized)

    assert matched.matched is True
    assert matched.rule_id == "k8s.secret_access_unapproved"
    assert matched.actor == "unknown"
    assert matched.source_ip == "unknown"
    assert matched.resource == "secrets"


def test_kubernetes_cluster_admin_binding_matches_critical_rule() -> None:
    normalized = normalize_kubernetes_audit_event(
        load_fixture("eks-clusterrolebinding-admin.audit.json"),
        account_id="493499579600",
        cluster_name="techx-tf2",
    )

    matched = apply_rule_match(normalized)

    assert matched.matched is True
    assert matched.rule_id == "k8s.rbac.cluster_admin_binding"
    assert matched.severity == "critical"


def test_kubernetes_pod_exec_in_production_matches_high_rule() -> None:
    normalized = normalize_kubernetes_audit_event(
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
        account_id="493499579600",
        cluster_name="techx-tf2",
    )

    matched = apply_rule_match(normalized)

    assert matched.matched is True
    assert matched.rule_id == "k8s.pod_exec_production"
    assert matched.severity == "high"


def test_kubernetes_privileged_workload_matches_critical_rule() -> None:
    normalized = normalize_kubernetes_audit_event(
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
        account_id="493499579600",
        cluster_name="techx-tf2",
    )

    matched = apply_rule_match(normalized)

    assert matched.matched is True
    assert matched.rule_id == "k8s.privileged_workload_requested"
    assert matched.severity == "critical"
    assert matched.attributes["privileged_workload_requested"] is True
    assert "hostPID=true" in matched.attributes["privileged_workload_reasons"]


def test_kubernetes_delete_production_resource_matches_high_rule() -> None:
    normalized = normalize_kubernetes_audit_event(
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
        account_id="493499579600",
        cluster_name="techx-tf2",
    )

    matched = apply_rule_match(normalized)

    assert matched.matched is True
    assert matched.rule_id == "k8s.production_resource_deleted"
    assert matched.severity == "high"


def test_non_dangerous_cloudtrail_event_does_not_match() -> None:
    normalized = normalize_cloudtrail_event(
        load_fixture("cloudtrail-describe-cluster.json")
    )

    assert match_rule(normalized) is None
    assert apply_rule_match(normalized).matched is False
