"""Shared normalized event model and safe extraction helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

UNKNOWN = "unknown"


@dataclass(frozen=True)
class NormalizedAuditEvent:
    source_type: str
    actor: str = UNKNOWN
    action: str = UNKNOWN
    event_time_utc: str = UNKNOWN
    source_ip: str = UNKNOWN
    rule_id: str = "unmatched"
    severity: str = UNKNOWN
    environment: str = UNKNOWN
    service: str = UNKNOWN
    resource: str = UNKNOWN
    namespace: str | None = None
    user_agent: str = UNKNOWN
    request_id: str | None = None
    audit_id: str | None = None
    account_id: str | None = None
    region: str | None = None
    cluster_name: str | None = None
    event_id: str | None = None
    matched: bool = False
    suppressed: bool = False
    allowlist_id: str | None = None
    allowlist_reason: str | None = None
    allowlist_owner: str | None = None
    allowlist_ticket: str | None = None
    allowlist_review_after: str | None = None
    allowlist_error: str | None = None
    title_vi: str | None = None
    impact_vi: str | None = None
    first_action_vi: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def as_mapping(value: Any) -> Mapping[str, Any]:
    """Return a mapping or an empty mapping for unsafe nested values."""

    return value if isinstance(value, Mapping) else {}


def as_string(value: Any, default: str = UNKNOWN) -> str:
    """Return a non-empty string for alert fields."""

    if value is None:
        return default

    text = str(value).strip()
    return text if text else default


def first_string(values: list[Any] | tuple[Any, ...] | None, default: str = UNKNOWN) -> str:
    """Return the first non-empty string from a list-like value."""

    if not values:
        return default

    for value in values:
        text = as_string(value, "")
        if text:
            return text

    return default


def cluster_name_from_eks_log_group(log_group: str | None) -> str | None:
    """Extract cluster name from /aws/eks/<cluster-name>/cluster."""

    if not log_group:
        return None

    parts = log_group.strip("/").split("/")
    if len(parts) >= 3 and parts[0] == "aws" and parts[1] == "eks":
        return parts[2]

    return None
