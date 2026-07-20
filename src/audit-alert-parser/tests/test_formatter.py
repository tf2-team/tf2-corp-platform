from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from audit_alert_parser.cloudtrail import normalize_cloudtrail_event
from audit_alert_parser.formatter import format_alert_messages, format_audit_message
from audit_alert_parser.rules import apply_rule_match

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_formatter_outputs_required_human_context_in_ict() -> None:
    normalized = apply_rule_match(
        normalize_cloudtrail_event(load_fixture("cloudtrail-create-access-key.json"))
    )

    message = format_audit_message(normalized.to_dict())

    assert "[HIGH] Tao IAM access key moi" in message
    assert "Moi truong: unknown" in message
    assert "Rule: aws.iam.create_access_key" in message
    assert "Ai: arn:aws:iam::493499579600:user/example" in message
    assert "Lam gi: CreateAccessKey tren iam.amazonaws.com" in message
    assert "Luc nao: 18/07/2026 15:10:12 ICT" in message
    assert "Tu dau: 203.0.113.10" in message
    assert "Tac dong:" in message
    assert "Buoc dau tien:" in message
    assert "{" not in message
    assert "}" not in message


def test_formatter_redacts_secret_values_before_message_output() -> None:
    normalized = apply_rule_match(
        normalize_cloudtrail_event(load_fixture("cloudtrail-create-access-key.json"))
    )
    normalized = replace(
        normalized,
        user_agent="aws-cli Bearer abc.def.ghi https://discord.com/api/webhooks/1/secret",
    )

    message = format_audit_message(normalized.to_dict())

    assert "Bearer abc.def.ghi" not in message
    assert "https://discord.com/api/webhooks" not in message
    assert "[REDACTED]" in message


def test_formatter_handles_missing_fields_as_unknown() -> None:
    message = format_audit_message({"matched": True, "suppressed": False})

    assert "[UNKNOWN]" in message
    assert "Ai: unknown" in message
    assert "Lam gi: unknown" in message
    assert "Luc nao: unknown" in message
    assert "Tu dau: unknown" in message


def test_format_alert_messages_filters_ignored_and_suppressed_events() -> None:
    normalized = apply_rule_match(
        normalize_cloudtrail_event(load_fixture("cloudtrail-create-access-key.json"))
    )
    alert_candidate = normalized.to_dict()
    suppressed = replace(normalized, suppressed=True).to_dict()
    ignored = replace(normalized, matched=False).to_dict()

    messages = format_alert_messages([alert_candidate, suppressed, ignored])

    assert len(messages) == 1
    assert "aws.iam.create_access_key" in messages[0]
