from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

import audit_alert_parser.allowlist as allowlist_module
from audit_alert_parser.allowlist import (
    AllowlistConfig,
    AllowlistEntry,
    apply_allowlist,
    evaluate_allowlist,
    load_allowlist,
)
from audit_alert_parser.cloudtrail import normalize_cloudtrail_event
from audit_alert_parser.eks_audit import normalize_kubernetes_audit_event
from audit_alert_parser.handler import lambda_handler
from audit_alert_parser.rules import apply_rule_match

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def approved_terraform_eks_entry() -> AllowlistEntry:
    return AllowlistEntry(
        id="ci-terraform-approved-eks-access",
        enabled=True,
        owner="cdo06",
        reason="Terraform GitHub Actions duoc phe duyet quan ly EKS access entries.",
        ticket="TF4-M11-ALLOW-001",
        review_after="2026-08-19",
        rule_ids=("aws.eks.cluster_admin_access",),
        actor_patterns=("arn:aws:iam::493499579600:user/example",),
        actions=("eks.amazonaws.com:AssociateAccessPolicy",),
        resource_patterns=("techx-tf2",),
        user_agent_patterns=("Terraform/*",),
    )


def test_default_allowlist_loads_empty_entries_and_never_suppress_rules() -> None:
    config = load_allowlist()

    assert config.environment == "production"
    assert config.entries == ()
    assert "aws.cloudtrail.logging_changed" in config.never_suppress_rule_ids


def test_specific_terraform_eks_access_is_suppressed() -> None:
    normalized = apply_rule_match(
        normalize_cloudtrail_event(load_fixture("cloudtrail-associate-access-policy.json"))
    )
    config = AllowlistConfig(
        environment="production",
        entries=(approved_terraform_eks_entry(),),
    )

    result = apply_allowlist(normalized, config=config)

    assert result.suppressed is True
    assert result.allowlist_id == "ci-terraform-approved-eks-access"
    assert result.allowlist_owner == "cdo06"
    assert result.allowlist_ticket == "TF4-M11-ALLOW-001"


def test_unknown_actor_is_not_suppressed() -> None:
    normalized = apply_rule_match(
        normalize_cloudtrail_event(load_fixture("cloudtrail-associate-access-policy.json"))
    )
    normalized = replace(normalized, actor="arn:aws:iam::493499579600:user/unknown")
    config = AllowlistConfig(
        environment="production",
        entries=(approved_terraform_eks_entry(),),
    )

    result = apply_allowlist(normalized, config=config)

    assert result.suppressed is False
    assert result.allowlist_id is None


def test_kubernetes_secret_read_by_specific_service_account_is_suppressed() -> None:
    normalized = apply_rule_match(
        normalize_kubernetes_audit_event(
            load_fixture("eks-secret-get.audit.json"),
            account_id="493499579600",
            cluster_name="techx-tf2",
        )
    )
    normalized = replace(
        normalized,
        actor="system:serviceaccount:external-secrets:external-secrets",
    )
    config = AllowlistConfig(
        environment="production",
        entries=(
            AllowlistEntry(
                id="external-secrets-approved-secret-read",
                enabled=True,
                owner="cdo06",
                reason="External Secrets Operator duoc phe duyet doc Secret.",
                ticket="TF4-M11-ALLOW-002",
                review_after="2026-08-19",
                rule_ids=("k8s.secret_access_unapproved",),
                k8s_user_patterns=("system:serviceaccount:external-secrets:external-secrets",),
                verbs=("get", "list", "watch"),
                resources=("secrets",),
                namespaces=("techx-corp-prod",),
            ),
        ),
    )

    result = apply_allowlist(normalized, config=config)

    assert result.suppressed is True
    assert result.allowlist_id == "external-secrets-approved-secret-read"


def test_cloudtrail_logging_change_is_never_suppressed() -> None:
    normalized = apply_rule_match(
        normalize_cloudtrail_event(load_fixture("cloudtrail-stop-logging.json"))
    )
    config = AllowlistConfig(
        environment="production",
        never_suppress_rule_ids=("aws.cloudtrail.logging_changed",),
        entries=(
            AllowlistEntry(
                id="break-glass-cloudtrail-change",
                enabled=True,
                owner="platform",
                reason="This entry should not suppress CloudTrail logging changes.",
                ticket="TF4-M11-ALLOW-999",
                review_after="2026-08-19",
                rule_ids=("aws.cloudtrail.logging_changed",),
                actor_patterns=("arn:aws:iam::493499579600:user/example",),
                actions=("cloudtrail.amazonaws.com:StopLogging",),
            ),
        ),
    )

    result = apply_allowlist(normalized, config=config)

    assert result.suppressed is False
    assert result.allowlist_id is None


def test_broad_actor_wildcard_entry_is_rejected() -> None:
    normalized = apply_rule_match(
        normalize_cloudtrail_event(load_fixture("cloudtrail-associate-access-policy.json"))
    )

    with pytest.raises(ValueError, match="allowlist_entry_broad_wildcard"):
        evaluate_allowlist(
            normalized,
            config=AllowlistConfig(environment="production", entries=()),
            entries=[
                {
                    "id": "bad-broad-entry",
                    "enabled": True,
                    "owner": "cdo06",
                    "reason": "Invalid broad wildcard.",
                    "ticket": "TF4-M11-ALLOW-BAD",
                    "review_after": "2026-08-19",
                    "actor_patterns": ["*"],
                    "actions": ["eks.amazonaws.com:AssociateAccessPolicy"],
                }
            ],
        )


def test_allowlist_error_fails_safe_without_suppressing(monkeypatch: pytest.MonkeyPatch) -> None:
    normalized = apply_rule_match(
        normalize_cloudtrail_event(load_fixture("cloudtrail-associate-access-policy.json"))
    )

    def broken_loader() -> AllowlistConfig:
        raise ValueError("broken_allowlist")

    monkeypatch.setattr(allowlist_module, "load_allowlist", broken_loader)

    result = allowlist_module.apply_allowlist(normalized)

    assert result.suppressed is False
    assert result.allowlist_error == "broken_allowlist"


def test_handler_returns_suppressed_status_and_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    config = AllowlistConfig(
        environment="production",
        entries=(approved_terraform_eks_entry(),),
    )
    monkeypatch.setattr(allowlist_module, "load_allowlist", lambda: config)

    result = lambda_handler(load_fixture("cloudtrail-associate-access-policy.json"), None)

    assert result["status"] == "suppressed"
    assert result["reason"] == "allowlisted"
    assert result["summary"]["matched_count"] == 1
    assert result["summary"]["suppressed_count"] == 1
    assert result["summary"]["alert_candidate_count"] == 0
    assert result["summary"]["alert_message_count"] == 0
    assert result["alert_messages"] == []
    assert result["normalized_events"][0]["allowlist_id"] == "ci-terraform-approved-eks-access"
    assert result["evidence_records"][0]["status"] == "suppressed"
    assert result["evidence_records"][0]["allowlist_id"] == "ci-terraform-approved-eks-access"


def test_handler_keeps_unknown_actor_as_alert_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    event = load_fixture("cloudtrail-associate-access-policy.json")
    event["detail"]["userIdentity"]["arn"] = "arn:aws:iam::493499579600:user/unknown"
    config = AllowlistConfig(
        environment="production",
        entries=(approved_terraform_eks_entry(),),
    )
    monkeypatch.setattr(allowlist_module, "load_allowlist", lambda: config)

    result = lambda_handler(event, None)

    assert result["status"] == "matched"
    assert result["summary"]["matched_count"] == 1
    assert result["summary"]["suppressed_count"] == 0
    assert result["summary"]["alert_candidate_count"] == 1
    assert result["summary"]["alert_message_count"] == 1
    assert result["normalized_events"][0]["actor"] == "arn:aws:iam::493499579600:user/unknown"
    assert result["normalized_events"][0]["allowlist_id"] is None
    assert result["evidence_records"][0]["status"] == "alert_ready"
