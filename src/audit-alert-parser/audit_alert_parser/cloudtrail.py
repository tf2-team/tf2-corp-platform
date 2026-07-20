#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""CloudTrail event helpers for Mandate 11 audit detection."""

from __future__ import annotations

import json
from typing import Any, Mapping
from urllib.parse import unquote

from .normalizer import NormalizedAuditEvent, as_mapping, as_string


def is_cloudtrail_event(event: Mapping[str, Any]) -> bool:
    """Return True when the event looks like EventBridge CloudTrail input."""

    detail = event.get("detail")
    if not isinstance(detail, Mapping):
        return False

    return (
        event.get("detail-type") == "AWS API Call via CloudTrail"
        and isinstance(detail.get("eventSource"), str)
        and isinstance(detail.get("eventName"), str)
    )


def cloudtrail_summary(event: Mapping[str, Any]) -> dict[str, str]:
    """Extract a safe Phase 1 summary without exposing request payloads."""

    detail = event.get("detail")
    if not isinstance(detail, Mapping):
        detail = {}

    user_identity = detail.get("userIdentity")
    if not isinstance(user_identity, Mapping):
        user_identity = {}

    return {
        "event_source": str(detail.get("eventSource", "unknown")),
        "event_name": str(detail.get("eventName", "unknown")),
        "actor": str(
            user_identity.get("arn")
            or user_identity.get("principalId")
            or user_identity.get("userName")
            or "unknown"
        ),
        "event_time": str(detail.get("eventTime") or event.get("time") or "unknown"),
        "source_ip": str(detail.get("sourceIPAddress", "unknown")),
    }


def normalize_cloudtrail_event(event: Mapping[str, Any]) -> NormalizedAuditEvent:
    """Normalize an EventBridge CloudTrail event into the shared schema."""

    if not is_cloudtrail_event(event):
        raise ValueError("unsupported_cloudtrail_event_shape")

    detail = as_mapping(event.get("detail"))
    user_identity = as_mapping(detail.get("userIdentity"))
    request_parameters = as_mapping(detail.get("requestParameters"))
    event_source = as_string(detail.get("eventSource"))
    event_name = as_string(detail.get("eventName"))
    policy_arn = _optional_string(request_parameters.get("policyArn"))
    access_scope = as_mapping(request_parameters.get("accessScope"))
    policy_document_risks = _policy_document_risks(request_parameters.get("policyDocument"))
    disabled_cluster_log_types = _disabled_cluster_log_types(request_parameters)

    return NormalizedAuditEvent(
        source_type="cloudtrail",
        actor=_actor_from_user_identity(user_identity),
        action=event_name,
        event_time_utc=as_string(detail.get("eventTime") or event.get("time")),
        source_ip=as_string(detail.get("sourceIPAddress")),
        service=event_source,
        resource=_resource_from_request_parameters(request_parameters),
        user_agent=as_string(detail.get("userAgent")),
        request_id=_optional_string(detail.get("requestID")),
        account_id=_optional_string(event.get("account") or detail.get("recipientAccountId")),
        region=_optional_string(event.get("region") or detail.get("awsRegion")),
        cluster_name=_optional_string(request_parameters.get("clusterName")),
        event_id=_optional_string(detail.get("eventID")),
        attributes={
            "event_source": event_source,
            "event_name": event_name,
            "user_identity_type": _optional_string(user_identity.get("type")),
            "policyArn": policy_arn,
            "policy_arn": policy_arn,
            "policyName": _optional_string(request_parameters.get("policyName")),
            "policy_name": _optional_string(request_parameters.get("policyName")),
            "policy_document_high_risk": bool(policy_document_risks),
            "policy_document_risks": policy_document_risks,
            "clusterName": _optional_string(request_parameters.get("clusterName")),
            "cluster_name": _optional_string(request_parameters.get("clusterName")),
            "principalArn": _optional_string(request_parameters.get("principalArn")),
            "principal_arn": _optional_string(request_parameters.get("principalArn")),
            "access_scope_type": _optional_string(access_scope.get("type")),
            "disabled_cluster_log_types": disabled_cluster_log_types,
            "eks_audit_logging_disabled": bool(disabled_cluster_log_types),
            "admin_policy_requested": _is_admin_policy_request(
                request_parameters,
                policy_document_risks,
            ),
        },
    )


def _actor_from_user_identity(user_identity: Mapping[str, Any]) -> str:
    return as_string(
        user_identity.get("arn")
        or user_identity.get("principalId")
        or user_identity.get("userName")
    )


def _resource_from_request_parameters(request_parameters: Mapping[str, Any]) -> str:
    for key in (
        "userName",
        "roleName",
        "groupName",
        "policyName",
        "clusterName",
        "policyArn",
        "principalArn",
        "name",
    ):
        value = request_parameters.get(key)
        if value:
            return as_string(value)

    return "unknown"


def _optional_string(value: Any) -> str | None:
    text = as_string(value, "")
    return text or None


def _is_admin_policy_request(
    request_parameters: Mapping[str, Any],
    policy_document_risks: list[str],
) -> bool:
    policy_arn = as_string(request_parameters.get("policyArn"), "")
    if "AdministratorAccess" in policy_arn:
        return True

    return bool(policy_document_risks)


def _policy_document_risks(policy_document: Any) -> list[str]:
    parsed_document = _parse_policy_document(policy_document)
    if parsed_document is None:
        return _raw_policy_document_risks(policy_document)

    risks: list[str] = []
    for statement in _policy_statements(parsed_document):
        risks.extend(_statement_risks(statement))

    return sorted(set(risks))


def _parse_policy_document(policy_document: Any) -> Mapping[str, Any] | None:
    if isinstance(policy_document, Mapping):
        return policy_document

    if not isinstance(policy_document, str):
        return None

    candidate = policy_document.strip()
    if not candidate:
        return None

    for _ in range(3):
        decoded = unquote(candidate)
        if decoded == candidate:
            break
        candidate = decoded

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None

    return parsed if isinstance(parsed, Mapping) else None


def _policy_statements(policy_document: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw_statements = policy_document.get("Statement") or policy_document.get("statement")
    if isinstance(raw_statements, Mapping):
        return [raw_statements]

    if isinstance(raw_statements, list):
        return [item for item in raw_statements if isinstance(item, Mapping)]

    return []


def _statement_risks(statement: Mapping[str, Any]) -> list[str]:
    if as_string(statement.get("Effect") or statement.get("effect"), "").lower() != "allow":
        return []

    actions = _lower_string_values(statement.get("Action") or statement.get("action"))
    not_actions = _lower_string_values(
        statement.get("NotAction") or statement.get("notAction")
    )
    resources = _lower_string_values(
        statement.get("Resource") or statement.get("resource")
    )
    has_broad_resource = "*" in resources
    risks: list[str] = []

    if "*" in actions and has_broad_resource:
        risks.append("allow_action_star_resource_star")

    if not_actions and has_broad_resource:
        risks.append("allow_notaction_with_broad_resource")

    for action in actions:
        risk = _high_risk_action(action, has_broad_resource)
        if risk:
            risks.append(risk)

    return risks


def _raw_policy_document_risks(policy_document: Any) -> list[str]:
    raw_text = as_string(policy_document, "").lower()
    if not raw_text:
        return []

    decoded = unquote(raw_text)
    compact = "".join(decoded.split())
    risks: list[str] = []

    if '"action":"*"' in compact and '"resource":"*"' in compact:
        risks.append("raw_allow_action_star_resource_star")

    for prefix in _HIGH_RISK_ACTION_PREFIXES:
        if prefix in decoded:
            risks.append(f"raw_high_risk_action_prefix:{prefix}*")

    for action in _HIGH_RISK_EXACT_ACTIONS:
        if action in decoded:
            risks.append(f"raw_high_risk_action:{action}")

    return sorted(set(risks))


def _high_risk_action(action: str, has_broad_resource: bool) -> str | None:
    if action == "*":
        return "high_risk_action:*"

    if action.endswith(":*") and action.split(":", 1)[0] in _HIGH_RISK_SERVICES:
        return f"high_risk_action_prefix:{action}"

    if has_broad_resource and action in _HIGH_RISK_EXACT_ACTIONS:
        return f"high_risk_action:{action}"

    return None


def _lower_string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.lower()]

    if isinstance(value, list):
        return [item.lower() for item in value if isinstance(item, str)]

    return []


def _disabled_cluster_log_types(request_parameters: Mapping[str, Any]) -> list[str]:
    logging_config = as_mapping(request_parameters.get("logging"))
    raw_cluster_logging = logging_config.get("clusterLogging")
    if not isinstance(raw_cluster_logging, list):
        return []

    disabled_log_types: list[str] = []
    for entry in raw_cluster_logging:
        cluster_logging = as_mapping(entry)
        if cluster_logging.get("enabled") is not False:
            continue

        raw_types = cluster_logging.get("types")
        if not isinstance(raw_types, list):
            continue

        for log_type in raw_types:
            text = as_string(log_type, "")
            if text in {"api", "audit", "authenticator"}:
                disabled_log_types.append(text)

    return sorted(set(disabled_log_types))


_HIGH_RISK_SERVICES = {
    "account",
    "cloudtrail",
    "ec2",
    "eks",
    "iam",
    "kms",
    "organizations",
    "secretsmanager",
}

_HIGH_RISK_ACTION_PREFIXES = tuple(f"{service}:" for service in _HIGH_RISK_SERVICES)

_HIGH_RISK_EXACT_ACTIONS = {
    "iam:attachgrouppolicy",
    "iam:attachrolepolicy",
    "iam:attachuserpolicy",
    "iam:createaccesskey",
    "iam:createpolicy",
    "iam:createpolicyversion",
    "iam:passrole",
    "iam:putgrouppolicy",
    "iam:putrolepolicy",
    "iam:putuserpolicy",
    "iam:setdefaultpolicyversion",
    "sts:assumerole",
}
