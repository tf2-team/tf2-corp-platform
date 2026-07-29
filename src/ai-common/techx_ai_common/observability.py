#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Minimal, content-free telemetry for runtime model calls."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal
from dataclasses import dataclass
from collections.abc import Iterator
from typing import Any, Callable, TypeVar

from opentelemetry import metrics, trace
from opentelemetry.trace import SpanKind, Status, StatusCode


T = TypeVar("T")

_TRACER = trace.get_tracer("techx-ai-common")
_METER = metrics.get_meter("techx-ai-common")
_TOKENS = _METER.create_counter("app_ai_model_tokens", unit="tokens")
_COST = _METER.create_counter("app_ai_model_cost_usd", unit="USD")


@dataclass(frozen=True)
class TelemetryContext:
    surface: str = "unknown"
    user_id: str | None = None
    session_id: str | None = None


_CONTEXT: ContextVar[TelemetryContext] = ContextVar(
    "ai_telemetry_context",
    default=TelemetryContext(),
)

# AWS Price List API, AmazonBedrock offer, effective 2026-07-01.
# Values are USD per 1M text tokens for standard on-demand inference.
_PRICING = {
    "global.amazon.nova-2-lite-v1:0": (
        Decimal("0.30"),
        Decimal("2.50"),
        "aws-2026-07-01-global-standard",
    ),
    "us.amazon.nova-2-lite-v1:0": (
        Decimal("0.33"),
        Decimal("2.75"),
        "aws-2026-07-01-us-standard",
    ),
}


def pseudonymize(raw_id: str | None, namespace: str) -> str | None:
    """Return a stable, domain-separated pseudonym without a default secret."""
    secret = os.environ.get("AI_TELEMETRY_HMAC_SECRET")
    if not secret or not raw_id:
        return None
    return hmac.new(
        secret.encode(),
        f"{namespace}:{raw_id}".encode(),
        hashlib.sha256,
    ).hexdigest()


@contextmanager
def telemetry_context(
    *,
    surface: str,
    user_id: str | None = None,
    session_id: str | None = None,
) -> Iterator[None]:
    token = _CONTEXT.set(TelemetryContext(surface, user_id, session_id))
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def _read(value: Any, *names: str) -> Any:
    for name in names:
        if isinstance(value, dict) and name in value:
            return value[name]
        item = getattr(value, name, None)
        if item is not None:
            return item
    return None


def usage_from(response: Any) -> tuple[int | None, int | None]:
    usage = _read(response, "usage")
    if usage is None:
        return None, None
    return (
        _read(usage, "inputTokens", "input_tokens", "prompt_tokens"),
        _read(usage, "outputTokens", "output_tokens", "completion_tokens"),
    )


def response_model_from(response: Any, requested_model: str) -> str:
    return str(_read(response, "model", "modelId", "model_id") or requested_model or "unknown")


def tool_names_from(response: Any) -> list[str]:
    names: list[str] = []
    output = _read(response, "output")
    message = _read(output, "message") if output is not None else None
    for item in _read(message, "content") or []:
        tool = _read(item, "toolUse", "tool_use")
        name = _read(tool, "name") if tool is not None else None
        if name:
            names.append(str(name))

    choices = _read(response, "choices") or []
    if choices:
        message = _read(choices[0], "message")
        for tool_call in _read(message, "tool_calls") or []:
            function = _read(tool_call, "function")
            name = _read(function, "name") if function is not None else None
            if name:
                names.append(str(name))
    return sorted(set(names))


def estimated_cost(
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
) -> tuple[Decimal, str] | None:
    pricing = _PRICING.get(model)
    raw_pricing = os.environ.get("AI_MODEL_PRICING_JSON")
    if pricing is None and raw_pricing:
        try:
            configured = json.loads(raw_pricing)[model]
            pricing = (
                Decimal(str(configured["input_per_million"])),
                Decimal(str(configured["output_per_million"])),
                str(configured["version"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            pricing = None
    if pricing is None or input_tokens is None or output_tokens is None:
        return None
    input_price, output_price, version = pricing
    cost = (
        Decimal(input_tokens) * input_price
        + Decimal(output_tokens) * output_price
    ) / Decimal(1_000_000)
    return cost, version


def call_model(
    invoke: Callable[[], T],
    *,
    model: str,
    provider: str,
    workflow_step: str,
    surface: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    fallback: bool = False,
) -> T:
    """Invoke one provider call and emit one safe GenAI span."""
    current = _CONTEXT.get()
    surface = surface or current.surface
    user_id = user_id or current.user_id
    session_id = session_id or current.session_id
    attributes: dict[str, Any] = {
        "gen_ai.operation.name": "chat",
        "gen_ai.provider.name": provider,
        "gen_ai.request.model": model or "unknown",
        "app.ai.surface": surface,
        "app.ai.workflow_step": workflow_step,
        "app.ai.outcome": "fallback" if fallback else "ok",
        "app.ai.telemetry_complete": bool(model),
    }
    user = pseudonymize(user_id, "user")
    session = pseudonymize(session_id, "session")
    if user:
        attributes["app.ai.user_pseudonym"] = user
    if session:
        attributes["app.ai.session_pseudonym"] = session
    if (user_id and not user) or (session_id and not session):
        attributes["app.ai.telemetry_complete"] = False

    metric_attributes = {
        "surface": surface,
        "provider": provider,
        "model": model or "unknown",
    }
    with _TRACER.start_as_current_span(
        f"chat {model or 'unknown'}",
        kind=SpanKind.CLIENT,
        attributes=attributes,
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            response = invoke()
        except Exception as exc:
            span.set_attribute("app.ai.outcome", "error")
            span.set_attribute("error.type", type(exc).__name__)
            span.set_status(Status(StatusCode.ERROR))
            raise

        response_model = response_model_from(response, model)
        span.set_attribute("gen_ai.response.model", response_model)
        if response_model == "unknown":
            span.set_attribute("app.ai.telemetry_complete", False)

        input_tokens, output_tokens = usage_from(response)
        if input_tokens is not None:
            span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
            _TOKENS.add(input_tokens, {**metric_attributes, "token_type": "input"})
        if output_tokens is not None:
            span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
            _TOKENS.add(output_tokens, {**metric_attributes, "token_type": "output"})

        tools = tool_names_from(response)
        span.set_attribute("app.ai.tool_call_count", len(tools))
        if tools:
            span.set_attribute("app.ai.tool_names", tools)

        cost = estimated_cost(model, input_tokens, output_tokens)
        if cost:
            amount, pricing_version = cost
            span.set_attribute("app.ai.estimated_cost_usd", float(amount))
            span.set_attribute("app.ai.pricing_version", pricing_version)
            _COST.add(
                float(amount),
                {**metric_attributes, "pricing_version": pricing_version},
            )
        return response


def call_tool(invoke: Callable[[], T], *, name: str, surface: str | None = None) -> T:
    current = _CONTEXT.get()
    surface = surface or current.surface
    with _TRACER.start_as_current_span(
        f"execute_tool {name}",
        attributes={
            "app.ai.surface": surface,
            "app.ai.tool.name": name,
            "app.ai.outcome": "ok",
        },
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            return invoke()
        except Exception as exc:
            span.set_attribute("app.ai.outcome", "error")
            span.set_attribute("error.type", type(exc).__name__)
            span.set_status(Status(StatusCode.ERROR))
            raise


def record_fallback(reason_class: str, *, surface: str | None = None) -> None:
    current = _CONTEXT.get()
    surface = surface or current.surface
    trace.get_current_span().set_attribute("app.ai.outcome", "fallback")
    with _TRACER.start_as_current_span(
        "app.ai.fallback",
        attributes={
            "app.ai.surface": surface,
            "app.ai.fallback.reason_class": reason_class or "UnknownError",
            "app.ai.outcome": "fallback",
        },
    ):
        pass
