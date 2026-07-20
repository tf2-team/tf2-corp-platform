"""EKS audit event helpers for Mandate 11 audit detection."""

from __future__ import annotations

import base64
import gzip
import json
from typing import Any, Mapping

from .normalizer import (
    NormalizedAuditEvent,
    as_mapping,
    as_string,
    cluster_name_from_eks_log_group,
    first_string,
)


def is_cloudwatch_logs_event(event: Mapping[str, Any]) -> bool:
    """Return True when Lambda input is a CloudWatch Logs subscription event."""

    awslogs = event.get("awslogs")
    return (
        isinstance(awslogs, Mapping)
        and isinstance(awslogs.get("data"), str)
        and bool(awslogs.get("data"))
    )


def decode_cloudwatch_logs_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """Decode a CloudWatch Logs subscription payload.

    CloudWatch Logs sends Lambda payloads as base64-encoded gzip JSON. The JSON
    envelope contains either CONTROL_MESSAGE or DATA_MESSAGE.
    """

    if not is_cloudwatch_logs_event(event):
        raise ValueError("unsupported_cloudwatch_logs_event_shape")

    awslogs = as_mapping(event.get("awslogs"))
    encoded_data = as_string(awslogs.get("data"), "")
    if not encoded_data:
        raise ValueError("missing_awslogs_data")

    try:
        compressed = base64.b64decode(encoded_data, validate=True)
        decoded = gzip.decompress(compressed).decode("utf-8")
        payload = json.loads(decoded)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("invalid_cloudwatch_logs_payload") from error

    if not isinstance(payload, dict):
        raise ValueError("invalid_cloudwatch_logs_payload")

    return payload


def iter_kubernetes_audit_events(event: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return parsed Kubernetes audit events from a CloudWatch Logs payload."""

    payload = decode_cloudwatch_logs_event(event)
    message_type = payload.get("messageType")
    if message_type == "CONTROL_MESSAGE":
        return []

    if message_type != "DATA_MESSAGE":
        raise ValueError("unsupported_cloudwatch_logs_message_type")

    audit_events: list[dict[str, Any]] = []
    log_events = payload.get("logEvents", [])
    if not isinstance(log_events, list):
        raise ValueError("invalid_cloudwatch_logs_log_events")

    for log_event in log_events:
        log_event_mapping = as_mapping(log_event)
        message = log_event_mapping.get("message")
        if not isinstance(message, str):
            raise ValueError("invalid_kubernetes_audit_message")

        try:
            audit_event = json.loads(message)
        except json.JSONDecodeError as error:
            raise ValueError("invalid_kubernetes_audit_message") from error

        if not isinstance(audit_event, dict):
            raise ValueError("invalid_kubernetes_audit_message")

        audit_events.append(audit_event)

    return audit_events


def normalize_cloudwatch_logs_event(event: Mapping[str, Any]) -> list[NormalizedAuditEvent]:
    """Normalize all Kubernetes audit records in a CloudWatch Logs event."""

    payload = decode_cloudwatch_logs_event(event)
    if payload.get("messageType") == "CONTROL_MESSAGE":
        return []

    log_group = as_string(payload.get("logGroup"), "")
    owner = _optional_string(payload.get("owner"))
    cluster_name = cluster_name_from_eks_log_group(log_group)

    normalized_events: list[NormalizedAuditEvent] = []
    log_events = payload.get("logEvents", [])
    if not isinstance(log_events, list):
        raise ValueError("invalid_cloudwatch_logs_log_events")

    for log_event in log_events:
        log_event_mapping = as_mapping(log_event)
        message = log_event_mapping.get("message")
        if not isinstance(message, str):
            raise ValueError("invalid_kubernetes_audit_message")

        try:
            audit_event = json.loads(message)
        except json.JSONDecodeError as error:
            raise ValueError("invalid_kubernetes_audit_message") from error

        if not isinstance(audit_event, dict):
            raise ValueError("invalid_kubernetes_audit_message")

        normalized_events.append(
            normalize_kubernetes_audit_event(
                audit_event,
                account_id=owner,
                cluster_name=cluster_name,
            )
        )

    return normalized_events


def normalize_kubernetes_audit_event(
    audit_event: Mapping[str, Any],
    *,
    account_id: str | None = None,
    cluster_name: str | None = None,
) -> NormalizedAuditEvent:
    """Normalize one Kubernetes audit event into the shared schema."""

    user = as_mapping(audit_event.get("user"))
    object_ref = as_mapping(audit_event.get("objectRef"))
    request_object = as_mapping(audit_event.get("requestObject"))
    role_ref = as_mapping(request_object.get("roleRef"))
    privileged_reasons = _privileged_workload_reasons(request_object)
    verb = as_string(audit_event.get("verb"))
    resource = as_string(object_ref.get("resource"))
    subresource = as_string(object_ref.get("subresource"), "")
    action = f"{verb} {resource}/{subresource}" if subresource else f"{verb} {resource}"

    source_ips = audit_event.get("sourceIPs")
    if not isinstance(source_ips, list):
        source_ips = []

    return NormalizedAuditEvent(
        source_type="kubernetes_audit",
        actor=as_string(user.get("username")),
        action=action,
        event_time_utc=as_string(
            audit_event.get("stageTimestamp")
            or audit_event.get("requestReceivedTimestamp")
        ),
        source_ip=first_string(source_ips),
        service="kubernetes",
        resource=as_string(object_ref.get("name") or object_ref.get("resource")),
        namespace=_optional_string(object_ref.get("namespace")),
        user_agent=as_string(audit_event.get("userAgent")),
        audit_id=_optional_string(audit_event.get("auditID")),
        account_id=account_id,
        cluster_name=cluster_name,
        attributes={
            "verb": verb,
            "k8s_resource": resource,
            "subresource": subresource or None,
            "namespace": _optional_string(object_ref.get("namespace")),
            "object_name": _optional_string(object_ref.get("name")),
            "role_ref_name": _optional_string(role_ref.get("name")),
            "role_ref_kind": _optional_string(role_ref.get("kind")),
            "privileged_workload_requested": bool(privileged_reasons),
            "privileged_workload_reasons": privileged_reasons,
        },
    )


def _optional_string(value: Any) -> str | None:
    text = as_string(value, "")
    return text or None


def _privileged_workload_reasons(request_object: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    for pod_spec in _candidate_pod_specs(request_object):
        if pod_spec.get("hostNetwork") is True:
            reasons.append("hostNetwork=true")
        if pod_spec.get("hostPID") is True:
            reasons.append("hostPID=true")
        if pod_spec.get("hostIPC") is True:
            reasons.append("hostIPC=true")

        for volume in _mapping_list(pod_spec.get("volumes")):
            if isinstance(volume.get("hostPath"), Mapping):
                volume_name = as_string(volume.get("name"), "unknown")
                reasons.append(f"hostPath volume:{volume_name}")

        for container in _container_specs(pod_spec):
            security_context = as_mapping(container.get("securityContext"))
            if security_context.get("privileged") is True:
                container_name = as_string(container.get("name"), "unknown")
                reasons.append(f"privileged container:{container_name}")

    return sorted(set(reasons))


def _candidate_pod_specs(request_object: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    specs: list[Mapping[str, Any]] = []
    spec = as_mapping(request_object.get("spec"))
    if spec:
        specs.append(spec)

    template_spec = as_mapping(as_mapping(spec.get("template")).get("spec"))
    if template_spec:
        specs.append(template_spec)

    job_template = as_mapping(spec.get("jobTemplate"))
    job_template_spec = as_mapping(as_mapping(job_template.get("spec")).get("template"))
    cronjob_template_spec = as_mapping(job_template_spec.get("spec"))
    if cronjob_template_spec:
        specs.append(cronjob_template_spec)

    return specs


def _container_specs(pod_spec: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    containers: list[Mapping[str, Any]] = []
    for key in ("containers", "initContainers", "ephemeralContainers"):
        containers.extend(_mapping_list(pod_spec.get(key)))
    return containers


def _mapping_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]
