import os
import pytest
from techx_ai_common.observability import (
    calculate_cost,
    get_hmac_key,
    get_model_pricing,
    pseudonymize_session,
    pseudonymize_user,
    record_chat_telemetry,
)


def test_hmac_key_length_validation(monkeypatch):
    monkeypatch.setenv("AI_OBSERVABILITY_HMAC_KEY", "short_key")
    with pytest.raises(ValueError, match="at least 32 bytes"):
        get_hmac_key()

    monkeypatch.setenv("AI_OBSERVABILITY_HMAC_KEY", "01234567890123456789012345678901")
    assert get_hmac_key() == b"01234567890123456789012345678901"


def test_pseudonymization_format_and_determinism(monkeypatch):
    monkeypatch.setenv("AI_OBSERVABILITY_HMAC_KEY", "01234567890123456789012345678901")

    u1 = pseudonymize_user("user-123")
    u2 = pseudonymize_user("user-123")
    assert u1 == u2
    assert len(u1) == 32
    assert all(c in "0123456789abcdef" for c in u1)

    s1 = pseudonymize_session("session-456")
    assert len(s1) == 32
    assert s1 != u1  # different prefix ("user:" vs "session:")

    assert pseudonymize_user("") == ""
    assert pseudonymize_session(None) == ""


def test_price_registry_and_cost_calculation():
    # gpt-oss-20b
    cost_gpt = calculate_cost("openai/gpt-oss-20b", 1_000_000, 1_000_000)
    assert pytest.approx(cost_gpt, 0.0001) == 0.375

    # Nova 2 Lite
    cost_nova = calculate_cost("global.amazon.nova-2-lite-v1:0", 1_000_000, 1_000_000)
    assert pytest.approx(cost_nova, 0.0001) == 3.08

    # techx-llm
    cost_local = calculate_cost("techx-llm", 1_000_000, 1_000_000)
    assert cost_local == 0.0

    with pytest.raises(ValueError, match="No price registry entry"):
        get_model_pricing("unknown-unsupported-model-id")


# Change trail: @hungxqt - 2026-07-29 - Unit tests for AI observability pseudonyms, pricing registry, and HMAC keys.
