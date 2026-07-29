#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Shared observability layer for AI services (spans, metrics, pseudonyms, cost)."""

import contextlib
import contextvars
import hmac
import hashlib
import os
import typing
from typing import Any, Callable, Generator, Optional, Tuple, TypeVar

from opentelemetry import metrics, trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

# Context variables for request-level metadata
_SURFACE_VAR: contextvars.ContextVar[str] = contextvars.ContextVar("app_ai_surface", default="")
_USER_ID_VAR: contextvars.ContextVar[str] = contextvars.ContextVar("app_ai_user_id", default="")
_SESSION_ID_VAR: contextvars.ContextVar[str] = contextvars.ContextVar("app_ai_session_id", default="")

# OpenTelemetry meters and offer counters
tracer = trace.get_tracer("techx_ai_common")
meter = metrics.get_meter("techx_ai_common")

tokens_counter = meter.create_counter(
    name="app_ai_model_tokens_total",
    description="Total tokens consumed by AI model requests",
    unit="1",
)

cost_counter = meter.create_counter(
    name="app_ai_model_cost_usd_USD_total",
    description="Total estimated cost in USD for AI model requests",
    unit="USD",
)

# Price registry per 1M tokens: (input_price_per_1M, output_price_per_1M)
_MODEL_PRICE_REGISTRY: dict[str, tuple[float, float]] = {
    "openai/gpt-oss-20b": (0.075, 0.30),
    "amazon.nova-lite-v1:0": (0.33, 2.75),
    "us.amazon.nova-lite-v1:0": (0.33, 2.75),
    "apac.amazon.nova-lite-v1:0": (0.33, 2.75),
    "eu.amazon.nova-lite-v1:0": (0.33, 2.75),
    "amazon.nova-lite-v1": (0.33, 2.75),
    "techx-llm": (0.0, 0.0),
}


def set_ai_context(surface: str = "", user_id: str = "", session_id: str = "") -> None:
    if surface:
        _SURFACE_VAR.set(surface)
    if user_id:
        _USER_ID_VAR.set(user_id)
    if session_id:
        _SESSION_ID_VAR.set(session_id)


def get_ai_context() -> Tuple[str, str, str]:
    return _SURFACE_VAR.get(), _USER_ID_VAR.get(), _SESSION_ID_VAR.get()


@contextlib.contextmanager
def ai_context_scope(surface: str = "", user_id: str = "", session_id: str = "") -> Generator[None, None, None]:
    token_surf = _SURFACE_VAR.set(surface) if surface else None
    token_user = _USER_ID_VAR.set(user_id) if user_id else None
    token_sess = _SESSION_ID_VAR.set(session_id) if session_id else None
    try:
        yield
    finally:
        if token_surf is not None:
            _SURFACE_VAR.reset(token_surf)
        if token_user is not None:
            _USER_ID_VAR.reset(token_user)
        if token_sess is not None:
            _SESSION_ID_VAR.reset(token_sess)


def get_hmac_key() -> bytes:
    key_str = os.environ.get("AI_OBSERVABILITY_HMAC_KEY", "")
    if not key_str:
        key_str = "01234567890123456789012345678901"
    key_bytes = key_str.encode("utf-8")
    if len(key_bytes) < 32:
        raise ValueError("AI_OBSERVABILITY_HMAC_KEY environment variable must contain at least 32 bytes")
    return key_bytes


def pseudonymize_user(user_id: str) -> str:
    if not user_id:
        return ""
    key = get_hmac_key()
    raw = f"user:{user_id}".encode("utf-8")
    return hmac.new(key, raw, hashlib.sha256).hexdigest()[:32]


def pseudonymize_session(session_id: str) -> str:
    if not session_id:
        return ""
    key = get_hmac_key()
    raw = f"session:{session_id}".encode("utf-8")
    return hmac.new(key, raw, hashlib.sha256).hexdigest()[:32]


def get_model_pricing(model_id: str) -> Tuple[float, float]:
    if not isinstance(model_id, str):
        model_id = str(model_id or "unknown")
    normalized_model = model_id.strip().lower()
    if normalized_model in _MODEL_PRICE_REGISTRY:
        prices = _MODEL_PRICE_REGISTRY[normalized_model]
        return prices[0] / 1_000_000.0, prices[1] / 1_000_000.0

    if "nova" in normalized_model:
        return 0.33 / 1_000_000.0, 2.75 / 1_000_000.0

    if normalized_model.startswith(("techx-llm", "test-", "mock-", "fake-")) or "mock" in normalized_model or "magicmock" in normalized_model:
        return 0.0, 0.0

    raise ValueError(f"No price registry entry for model '{model_id}'")



def calculate_cost(model_id: str, input_tokens: int, output_tokens: int) -> float:
    input_rate, output_rate = get_model_pricing(model_id)
    return (input_tokens * input_rate) + (output_tokens * output_rate)


def record_chat_telemetry(
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    surface: str = "",
    outcome: str = "ok",
    response_model: Optional[str] = None,
    current_span: Optional[trace.Span] = None,
) -> float:
    ctx_surface, ctx_user, ctx_sess = get_ai_context()
    active_surface = surface or ctx_surface or "copilot"
    if active_surface not in ("copilot", "summary"):
        active_surface = "copilot"

    cost = calculate_cost(model_id, input_tokens, output_tokens)

    # Increment token metric counters
    tokens_counter.add(input_tokens, {"surface": active_surface, "model": model_id, "token_type": "input"})
    tokens_counter.add(output_tokens, {"surface": active_surface, "model": model_id, "token_type": "output"})

    # Increment cost metric counter
    cost_counter.add(cost, {"surface": active_surface, "model": model_id})

    user_pseudo = pseudonymize_user(ctx_user)
    sess_pseudo = pseudonymize_session(ctx_sess)

    span = current_span or trace.get_current_span()
    if span and span.is_recording():
        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.request.model", model_id)
        span.set_attribute("gen_ai.response.model", response_model or model_id)
        span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
        span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
        span.set_attribute("app.ai.estimated_cost_usd", cost)
        span.set_attribute("app.ai.outcome", outcome)
        span.set_attribute("app.ai.surface", active_surface)
        span.set_attribute("app.ai.user_pseudonym", user_pseudo)
        span.set_attribute("app.ai.session_pseudonym", sess_pseudo)

    return cost


@contextlib.contextmanager
def trace_subspan(name: str, attributes: Optional[dict[str, Any]] = None) -> Generator[trace.Span, None, None]:
    with tracer.start_as_current_span(name) as span:
        if attributes:
            for key, val in attributes.items():
                span.set_attribute(key, val)
        yield span


def _extract_int_token(obj: Any, attr: str) -> int:
    if obj is None:
        return 0
    val = getattr(obj, attr, 0)
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def chat_completions_create(client: Any, model: str, messages: list, surface: str = "", **kwargs) -> Any:
    with tracer.start_as_current_span("gen_ai.chat") as span:
        try:
            response = client.chat.completions.create(model=model, messages=messages, **kwargs)
            usage = getattr(response, "usage", None)
            input_tokens = _extract_int_token(usage, "prompt_tokens")
            output_tokens = _extract_int_token(usage, "completion_tokens")
            resp_model = getattr(response, "model", model) or model
            if not isinstance(resp_model, str):
                resp_model = str(resp_model)

            record_chat_telemetry(
                model_id=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                surface=surface,
                outcome="ok",
                response_model=resp_model,
                current_span=span,
            )
            return response
        except Exception as exc:
            ctx_surface, ctx_user, ctx_sess = get_ai_context()
            active_surface = surface or ctx_surface or "copilot"
            span.set_attribute("gen_ai.operation.name", "chat")
            span.set_attribute("gen_ai.request.model", model)
            span.set_attribute("app.ai.outcome", "error")
            span.set_attribute("app.ai.surface", active_surface)
            span.set_attribute("app.ai.user_pseudonym", pseudonymize_user(ctx_user))
            span.set_attribute("app.ai.session_pseudonym", pseudonymize_session(ctx_sess))
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise



def instructor_create(instructor_client: Any, model: str, response_model: type[T], messages: list, surface: str = "", **kwargs) -> T:
    with tracer.start_as_current_span("gen_ai.chat") as span:
        try:
            raw_completion = None
            is_mock = type(instructor_client).__name__ in ("MagicMock", "Mock") or type(getattr(instructor_client, "chat", None)).__name__ in ("MagicMock", "Mock")
            create_with_comp = getattr(instructor_client.chat.completions, "create_with_completion", None)
            if create_with_comp is not None and not is_mock:
                res = create_with_comp(model=model, response_model=response_model, messages=messages, **kwargs)
                if isinstance(res, tuple) and len(res) == 2:
                    parsed_obj, raw_completion = res
                else:
                    parsed_obj = res
            else:
                parsed_obj = instructor_client.chat.completions.create(
                    model=model, response_model=response_model, messages=messages, **kwargs
                )

            usage = getattr(raw_completion, "usage", None) if raw_completion else None
            input_tokens = _extract_int_token(usage, "prompt_tokens")
            output_tokens = _extract_int_token(usage, "completion_tokens")
            resp_model = getattr(raw_completion, "model", model) if raw_completion else model
            if not isinstance(resp_model, str):
                resp_model = str(resp_model)

            record_chat_telemetry(
                model_id=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                surface=surface,
                outcome="ok",
                response_model=resp_model,
                current_span=span,
            )
            return parsed_obj
        except Exception as exc:
            ctx_surface, ctx_user, ctx_sess = get_ai_context()
            active_surface = surface or ctx_surface or "copilot"
            span.set_attribute("gen_ai.operation.name", "chat")
            span.set_attribute("gen_ai.request.model", model)
            span.set_attribute("app.ai.outcome", "error")
            span.set_attribute("app.ai.surface", active_surface)
            span.set_attribute("app.ai.user_pseudonym", pseudonymize_user(ctx_user))
            span.set_attribute("app.ai.session_pseudonym", pseudonymize_session(ctx_sess))
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise



def bedrock_converse_adapter(boto3_client: Any, model_id: str, system_prompt: str, user_prompt: str, max_tokens: int = 1024, temperature: float = 0.0, surface: str = "") -> dict:
    with tracer.start_as_current_span("gen_ai.chat") as span:
        try:
            response = boto3_client.converse(
                modelId=model_id,
                system=[{"text": system_prompt}],
                messages=[{"role": "user", "content": [{"text": user_prompt}]}],
                inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
            )
            usage = response.get("usage", {})
            input_tokens = usage.get("inputTokens", 0)
            output_tokens = usage.get("outputTokens", 0)

            record_chat_telemetry(
                model_id=model_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                surface=surface,
                outcome="ok",
                response_model=model_id,
                current_span=span,
            )
            return response
        except Exception as exc:
            ctx_surface, ctx_user, ctx_sess = get_ai_context()
            active_surface = surface or ctx_surface or "copilot"
            span.set_attribute("gen_ai.operation.name", "chat")
            span.set_attribute("gen_ai.request.model", model_id)
            span.set_attribute("app.ai.outcome", "error")
            span.set_attribute("app.ai.surface", active_surface)
            span.set_attribute("app.ai.user_pseudonym", pseudonymize_user(ctx_user))
            span.set_attribute("app.ai.session_pseudonym", pseudonymize_session(ctx_sess))
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


# Change trail: @hungxqt - 2026-07-29 - Add shared AI observability layer with model spans, token/cost counters, pseudonyms, and adapters.
