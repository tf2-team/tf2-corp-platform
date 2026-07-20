#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Allowlist-based noise reduction for Mandate 11.6.

The allowlist runs only after a dangerous rule matched. This keeps normal
events out of the suppression path and makes every suppressed event explainable
by rule ID, actor, action, resource, owner, ticket, and review date.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from .normalizer import NormalizedAuditEvent, as_string

DEFAULT_ALLOWLIST_PATH = Path(__file__).resolve().parents[1] / "config" / "allowlist.yaml"
DEFAULT_NEVER_SUPPRESS_RULE_IDS = (
    "aws.cloudtrail.logging_changed",
    "aws.eks.audit_logging_disabled",
)


@dataclass(frozen=True)
class AllowlistDecision:
    suppressed: bool
    allowlist_id: str | None = None
    reason: str | None = None
    owner: str | None = None
    ticket: str | None = None
    review_after: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, str | bool | None]:
        return asdict(self)


@dataclass(frozen=True)
class AllowlistEntry:
    id: str
    enabled: bool
    owner: str
    reason: str
    ticket: str
    review_after: str
    rule_ids: tuple[str, ...] = ()
    source_types: tuple[str, ...] = ()
    actor_patterns: tuple[str, ...] = ()
    k8s_user_patterns: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    resource_patterns: tuple[str, ...] = ()
    namespaces: tuple[str, ...] = ()
    user_agent_patterns: tuple[str, ...] = ()
    verbs: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()


@dataclass(frozen=True)
class AllowlistConfig:
    environment: str
    entries: tuple[AllowlistEntry, ...]
    never_suppress_rule_ids: tuple[str, ...] = DEFAULT_NEVER_SUPPRESS_RULE_IDS


def load_allowlist(path: Path = DEFAULT_ALLOWLIST_PATH) -> AllowlistConfig:
    """Load and validate allowlist.yaml.

    Validation intentionally rejects broad enabled entries. A broken allowlist is
    safer as an explicit error than as silent alert suppression.
    """

    with path.open("r", encoding="utf-8") as allowlist_file:
        payload = yaml.safe_load(allowlist_file)

    if not isinstance(payload, Mapping):
        raise ValueError("invalid_allowlist_config")

    raw_entries = payload.get("entries", [])
    if not isinstance(raw_entries, list):
        raise ValueError("invalid_allowlist_entries")

    never_suppress_rule_ids = tuple(
        _string_list(
            payload.get("never_suppress_rule_ids"),
            default=list(DEFAULT_NEVER_SUPPRESS_RULE_IDS),
        )
    )
    entries = tuple(_entry_from_mapping(raw_entry) for raw_entry in raw_entries)

    return AllowlistConfig(
        environment=as_string(payload.get("environment"), "unknown"),
        never_suppress_rule_ids=never_suppress_rule_ids,
        entries=entries,
    )


def apply_allowlist(
    normalized_event: NormalizedAuditEvent,
    config: AllowlistConfig | None = None,
) -> NormalizedAuditEvent:
    """Attach suppression metadata to a dangerous event when allowlisted.

    Fail-safe behavior: if config loading or matching raises an error, the event
    remains unsuppressed and carries `allowlist_error` for evidence/debugging.
    """

    if not normalized_event.matched:
        return normalized_event

    try:
        decision = evaluate_allowlist(normalized_event, config=config)
    except Exception as error:  # noqa: BLE001 - fail-safe must catch config mistakes.
        return replace(normalized_event, allowlist_error=str(error) or error.__class__.__name__)

    if not decision.suppressed:
        return normalized_event

    return replace(
        normalized_event,
        suppressed=True,
        allowlist_id=decision.allowlist_id,
        allowlist_reason=decision.reason,
        allowlist_owner=decision.owner,
        allowlist_ticket=decision.ticket,
        allowlist_review_after=decision.review_after,
    )


def evaluate_allowlist(
    normalized_event: NormalizedAuditEvent | Mapping[str, Any],
    config: AllowlistConfig | None = None,
    entries: Sequence[AllowlistEntry | Mapping[str, Any]] | None = None,
) -> AllowlistDecision:
    """Return the first matching allowlist decision for a dangerous event."""

    event = _event_mapping(normalized_event)
    if event.get("matched") is not True:
        return AllowlistDecision(suppressed=False)

    effective_config = config if config is not None else load_allowlist()
    if as_string(event.get("rule_id"), "") in effective_config.never_suppress_rule_ids:
        return AllowlistDecision(suppressed=False)

    effective_entries = (
        tuple(_entry_from_mapping(entry) if isinstance(entry, Mapping) else entry for entry in entries)
        if entries is not None
        else effective_config.entries
    )

    for entry in effective_entries:
        if entry.enabled and _entry_matches(entry, event):
            return AllowlistDecision(
                suppressed=True,
                allowlist_id=entry.id,
                reason=entry.reason,
                owner=entry.owner,
                ticket=entry.ticket,
                review_after=entry.review_after,
            )

    return AllowlistDecision(suppressed=False)


def _entry_from_mapping(raw_entry: Mapping[str, Any]) -> AllowlistEntry:
    if not isinstance(raw_entry, Mapping):
        raise ValueError("invalid_allowlist_entry")

    entry = AllowlistEntry(
        id=_required_string(raw_entry, "id"),
        enabled=bool(raw_entry.get("enabled", False)),
        owner=as_string(raw_entry.get("owner"), ""),
        reason=as_string(raw_entry.get("reason"), ""),
        ticket=as_string(raw_entry.get("ticket"), ""),
        review_after=as_string(raw_entry.get("review_after"), ""),
        rule_ids=tuple(_string_list(raw_entry.get("rule_ids"))),
        source_types=tuple(_string_list(raw_entry.get("source_types"))),
        actor_patterns=tuple(_string_list(raw_entry.get("actor_patterns"))),
        k8s_user_patterns=tuple(_string_list(raw_entry.get("k8s_user_patterns"))),
        actions=tuple(_string_list(raw_entry.get("actions"))),
        resource_patterns=tuple(_string_list(raw_entry.get("resource_patterns"))),
        namespaces=tuple(_string_list(raw_entry.get("namespaces"))),
        user_agent_patterns=tuple(_string_list(raw_entry.get("user_agent_patterns"))),
        verbs=tuple(_string_list(raw_entry.get("verbs"))),
        resources=tuple(_string_list(raw_entry.get("resources"))),
    )

    if entry.enabled:
        _validate_enabled_entry(entry)

    return entry


def _validate_enabled_entry(entry: AllowlistEntry) -> None:
    for field_name in ("owner", "reason", "ticket", "review_after"):
        if not getattr(entry, field_name):
            raise ValueError(f"allowlist_entry_missing_{field_name}:{entry.id}")

    try:
        date.fromisoformat(entry.review_after)
    except ValueError as error:
        raise ValueError(f"allowlist_entry_invalid_review_after:{entry.id}") from error

    identity_patterns = entry.actor_patterns + entry.k8s_user_patterns
    if not identity_patterns:
        raise ValueError(f"allowlist_entry_missing_identity_scope:{entry.id}")

    scope_fields = (
        entry.rule_ids
        + entry.source_types
        + entry.actions
        + entry.resource_patterns
        + entry.namespaces
        + entry.user_agent_patterns
        + entry.verbs
        + entry.resources
    )
    if not scope_fields:
        raise ValueError(f"allowlist_entry_missing_action_or_resource_scope:{entry.id}")

    for pattern in identity_patterns + entry.resource_patterns + entry.user_agent_patterns:
        _reject_broad_pattern(pattern, entry.id)


def _entry_matches(entry: AllowlistEntry, event: Mapping[str, Any]) -> bool:
    attributes = _mapping(event.get("attributes"))

    if entry.rule_ids and as_string(event.get("rule_id"), "") not in entry.rule_ids:
        return False

    if entry.source_types and as_string(event.get("source_type"), "") not in entry.source_types:
        return False

    if not _matches_any(as_string(event.get("actor"), ""), entry.actor_patterns + entry.k8s_user_patterns):
        return False

    if entry.actions and not _action_matches(entry.actions, event):
        return False

    if entry.resource_patterns and not _matches_any(
        as_string(event.get("resource"), ""),
        entry.resource_patterns,
    ):
        return False

    if entry.namespaces and as_string(event.get("namespace"), "") not in entry.namespaces:
        return False

    if entry.user_agent_patterns and not _matches_any(
        as_string(event.get("user_agent"), ""),
        entry.user_agent_patterns,
    ):
        return False

    if entry.verbs and as_string(attributes.get("verb"), "") not in entry.verbs:
        return False

    if entry.resources and as_string(attributes.get("k8s_resource"), "") not in entry.resources:
        return False

    return True


def _action_matches(actions: Sequence[str], event: Mapping[str, Any]) -> bool:
    service = as_string(event.get("service"), "")
    action = as_string(event.get("action"), "")
    qualified_action = f"{service}:{action}" if service and action else action

    return action in actions or qualified_action in actions


def _event_mapping(normalized_event: NormalizedAuditEvent | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(normalized_event, NormalizedAuditEvent):
        return normalized_event.to_dict()
    return normalized_event


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _matches_any(value: str, patterns: Sequence[str]) -> bool:
    if not patterns:
        return False
    return any(fnmatchcase(value, pattern) for pattern in patterns)


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = as_string(payload.get(key), "")
    if not value:
        raise ValueError(f"allowlist_entry_missing_{key}")
    return value


def _string_list(value: Any, default: Sequence[str] | None = None) -> list[str]:
    if value is None:
        return list(default or [])
    if not isinstance(value, list):
        raise ValueError("expected_allowlist_list_field")
    return [as_string(item) for item in value if as_string(item, "")]


def _reject_broad_pattern(pattern: str, entry_id: str) -> None:
    if pattern.strip() in {"", "*"}:
        raise ValueError(f"allowlist_entry_broad_wildcard:{entry_id}")
