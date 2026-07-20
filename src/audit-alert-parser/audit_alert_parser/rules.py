#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Rule matching based on the Mandate 11.1 dangerous-action baseline."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from .normalizer import NormalizedAuditEvent, as_string

DEFAULT_RULES_PATH = Path(__file__).resolve().parents[1] / "config" / "rules.yaml"


@dataclass(frozen=True)
class RuleDefinition:
    id: str
    source_type: str
    severity: str
    title_vi: str
    impact_vi: str
    first_action_vi: str
    event_source: str | None = None
    event_names: tuple[str, ...] = ()
    verbs: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()
    subresources: tuple[str, ...] = ()
    namespace_prefixes: tuple[str, ...] = ()
    attribute_equals: Mapping[str, Any] | None = None
    request_parameter_contains: Mapping[str, str] | None = None
    request_object_contains: Mapping[str, str] | None = None
    require_admin_policy: bool = False


def load_rules(path: Path = DEFAULT_RULES_PATH) -> tuple[RuleDefinition, ...]:
    """Load rule definitions from config/rules.yaml."""

    with path.open("r", encoding="utf-8") as rule_file:
        payload = yaml.safe_load(rule_file)

    if not isinstance(payload, Mapping):
        raise ValueError("invalid_rules_config")

    raw_rules = payload.get("rules")
    if not isinstance(raw_rules, list):
        raise ValueError("invalid_rules_config")

    rules: list[RuleDefinition] = []
    for raw_rule in raw_rules:
        if not isinstance(raw_rule, Mapping):
            raise ValueError("invalid_rule_definition")

        rules.append(
            RuleDefinition(
                id=_required_string(raw_rule, "id"),
                source_type=_required_string(raw_rule, "source_type"),
                severity=_required_string(raw_rule, "severity"),
                title_vi=_required_string(raw_rule, "title_vi"),
                impact_vi=_required_string(raw_rule, "impact_vi"),
                first_action_vi=_required_string(raw_rule, "first_action_vi"),
                event_source=_optional_string(raw_rule.get("event_source")),
                event_names=tuple(_string_list(raw_rule.get("event_names"))),
                verbs=tuple(_string_list(raw_rule.get("verbs"))),
                resources=tuple(_string_list(raw_rule.get("resources"))),
                subresources=tuple(_string_list(raw_rule.get("subresources"))),
                namespace_prefixes=tuple(_string_list(raw_rule.get("namespace_prefixes"))),
                attribute_equals=_plain_mapping(raw_rule.get("attribute_equals")),
                request_parameter_contains=_string_mapping(
                    raw_rule.get("request_parameter_contains")
                ),
                request_object_contains=_string_mapping(
                    raw_rule.get("request_object_contains")
                ),
                require_admin_policy=bool(raw_rule.get("require_admin_policy", False)),
            )
        )

    return tuple(rules)


def phase_1_rule_ids() -> tuple[str, ...]:
    """Return the initial rule IDs planned for implementation."""

    return tuple(rule.id for rule in load_rules())


def match_rule(
    normalized_event: NormalizedAuditEvent,
    rules: Sequence[RuleDefinition] | None = None,
) -> RuleDefinition | None:
    """Return the first rule that matches a normalized event."""

    effective_rules = tuple(rules) if rules is not None else load_rules()
    for rule in effective_rules:
        if _rule_matches(rule, normalized_event):
            return rule

    return None


def apply_rule_match(
    normalized_event: NormalizedAuditEvent,
    rules: Sequence[RuleDefinition] | None = None,
) -> NormalizedAuditEvent:
    """Attach rule metadata to a normalized event when it is dangerous."""

    matched_rule = match_rule(normalized_event, rules=rules)
    if matched_rule is None:
        return normalized_event

    return replace(
        normalized_event,
        matched=True,
        rule_id=matched_rule.id,
        severity=matched_rule.severity,
        title_vi=matched_rule.title_vi,
        impact_vi=matched_rule.impact_vi,
        first_action_vi=matched_rule.first_action_vi,
    )


def _rule_matches(rule: RuleDefinition, event: NormalizedAuditEvent) -> bool:
    if rule.source_type != event.source_type:
        return False

    if event.source_type == "cloudtrail":
        return _cloudtrail_rule_matches(rule, event)

    if event.source_type == "kubernetes_audit":
        return _kubernetes_rule_matches(rule, event)

    return False


def _cloudtrail_rule_matches(rule: RuleDefinition, event: NormalizedAuditEvent) -> bool:
    if rule.event_source and rule.event_source != event.service:
        return False

    if rule.event_names and event.action not in rule.event_names:
        return False

    if rule.require_admin_policy and event.attributes.get("admin_policy_requested") is not True:
        return False

    if not _attributes_match(rule.attribute_equals, event):
        return False

    if rule.request_parameter_contains:
        for key, expected in rule.request_parameter_contains.items():
            actual = as_string(event.attributes.get(key) or event.attributes.get(_snake_case(key)), "")
            if expected not in actual:
                return False

    return True


def _kubernetes_rule_matches(rule: RuleDefinition, event: NormalizedAuditEvent) -> bool:
    verb = as_string(event.attributes.get("verb"), "")
    resource = as_string(event.attributes.get("k8s_resource"), "")
    subresource = as_string(event.attributes.get("subresource"), "")
    namespace = as_string(event.namespace or event.attributes.get("namespace"), "")

    if rule.verbs and verb not in rule.verbs:
        return False

    if rule.resources and resource not in rule.resources:
        return False

    if rule.subresources and subresource not in rule.subresources:
        return False

    if rule.namespace_prefixes and not any(
        namespace.startswith(prefix) for prefix in rule.namespace_prefixes
    ):
        return False

    if not _attributes_match(rule.attribute_equals, event):
        return False

    if rule.request_object_contains:
        for key, expected in rule.request_object_contains.items():
            actual = as_string(event.attributes.get(_request_object_key_alias(key)), "")
            if actual != expected:
                return False

    return True


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = _optional_string(payload.get(key))
    if value is None:
        raise ValueError(f"missing_rule_field:{key}")
    return value


def _optional_string(value: Any) -> str | None:
    text = as_string(value, "")
    return text or None


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("expected_list_rule_field")
    return [as_string(item) for item in value]


def _string_mapping(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("expected_mapping_rule_field")
    return {as_string(key): as_string(nested_value) for key, nested_value in value.items()}


def _plain_mapping(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("expected_mapping_rule_field")
    return {as_string(key): nested_value for key, nested_value in value.items()}


def _attributes_match(
    expected_attributes: Mapping[str, Any] | None,
    event: NormalizedAuditEvent,
) -> bool:
    if not expected_attributes:
        return True

    for key, expected in expected_attributes.items():
        actual = event.attributes.get(key)
        if isinstance(expected, bool):
            if actual is not expected:
                return False
        elif isinstance(expected, list):
            if as_string(actual, "") not in {as_string(item, "") for item in expected}:
                return False
        elif as_string(actual, "") != as_string(expected, ""):
            return False

    return True


def _snake_case(value: str) -> str:
    result: list[str] = []
    for index, char in enumerate(value):
        if char.isupper() and index > 0:
            result.append("_")
        result.append(char.lower())
    return "".join(result)


def _request_object_key_alias(key: str) -> str:
    aliases = {
        "roleRef.name": "role_ref_name",
        "roleRef.kind": "role_ref_kind",
    }
    return aliases.get(key, key)
