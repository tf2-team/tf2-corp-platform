#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Reliable Amazon Bedrock Converse boundary used by the AI runtime.

The adapter owns provider timeouts, bounded retries, a process-local circuit
breaker, deterministic evidence fault injection, safe telemetry, and strict
structured-output validation. Callers must not invoke Bedrock directly.
"""

from __future__ import annotations

import logging
import os
import random
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from opentelemetry import metrics
from pydantic import BaseModel, ValidationError

from .observability import call_model


T = TypeVar("T", bound=BaseModel)
UsageCallback = Callable[[int, int], None]

_logger = logging.getLogger("techx_ai_common.bedrock")
_meter = metrics.get_meter_provider().get_meter("techx_ai_common.bedrock")

_provider_calls_counter = _meter.create_counter(
    "bedrock_provider_calls_total",
    description="Bedrock Converse provider attempts",
)
_provider_failures_counter = _meter.create_counter(
    "bedrock_provider_failures_total",
    description="Bedrock Converse provider attempt failures",
)
_retries_counter = _meter.create_counter(
    "bedrock_retries_total",
    description="Bedrock retries scheduled after transient failures",
)
_breaker_transitions_counter = _meter.create_counter(
    "bedrock_breaker_state_transitions_total",
    description="Bedrock circuit-breaker state transitions",
)
_breaker_rejections_counter = _meter.create_counter(
    "bedrock_circuit_open_rejections_total",
    description="Calls rejected before contacting Bedrock",
)
_schema_failures_counter = _meter.create_counter(
    "bedrock_schema_validation_failures_total",
    description="Bedrock outputs rejected at a schema boundary",
)
_deadline_exceeded_counter = _meter.create_counter(
    "bedrock_deadline_exceeded_total",
    description="Bedrock logical calls stopped by their total deadline",
)
_request_duration_histogram = _meter.create_histogram(
    "bedrock_request_duration_seconds",
    description="Bedrock logical-call latency, including retries",
    unit="s",
)
_fault_injections_counter = _meter.create_counter(
    "bedrock_fault_injections_total",
    description="Controlled Bedrock evidence faults consumed",
)


class BedrockUnavailableError(RuntimeError):
    """Bedrock could not return a usable response."""


class CircuitBreakerOpenError(BedrockUnavailableError):
    """The call was rejected without contacting Bedrock."""


class BedrockDeadlineExceededError(BedrockUnavailableError):
    """The logical request exhausted its wall-clock budget."""


class InvalidModelOutputError(RuntimeError):
    """Bedrock returned an envelope or structured value that was not usable."""


@dataclass(frozen=True)
class _Config:
    connect_timeout: float
    read_timeout: float
    max_attempts: int
    backoff_base: float
    backoff_max: float
    schema_max_attempts: int
    breaker_failure_threshold: int
    breaker_recovery_seconds: float
    total_deadline_seconds: float


def is_bedrock_provider() -> bool:
    return os.environ.get("LLM_PROVIDER", "groq").lower() == "bedrock"


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, str(default))
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number") from None


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer") from None


def _load_config() -> _Config:
    cfg = _Config(
        connect_timeout=_env_float("BEDROCK_CONNECT_TIMEOUT_SECONDS", 2),
        read_timeout=_env_float("BEDROCK_READ_TIMEOUT_SECONDS", 8),
        max_attempts=_env_int("BEDROCK_MAX_ATTEMPTS", 2),
        backoff_base=_env_float("BEDROCK_BACKOFF_BASE_SECONDS", 0.25),
        backoff_max=_env_float("BEDROCK_BACKOFF_MAX_SECONDS", 1),
        schema_max_attempts=_env_int("BEDROCK_SCHEMA_MAX_ATTEMPTS", 2),
        breaker_failure_threshold=_env_int(
            "BEDROCK_BREAKER_FAILURE_THRESHOLD", 3
        ),
        breaker_recovery_seconds=_env_float(
            "BEDROCK_BREAKER_RECOVERY_SECONDS", 30
        ),
        total_deadline_seconds=_env_float(
            "BEDROCK_TOTAL_DEADLINE_SECONDS", 12
        ),
    )
    if cfg.connect_timeout <= 0 or cfg.read_timeout <= 0:
        raise ValueError("BEDROCK_*_TIMEOUT_SECONDS must be > 0")
    if cfg.max_attempts < 1:
        raise ValueError("BEDROCK_MAX_ATTEMPTS must be >= 1")
    if cfg.schema_max_attempts < 1:
        raise ValueError("BEDROCK_SCHEMA_MAX_ATTEMPTS must be >= 1")
    if cfg.backoff_base < 0:
        raise ValueError("BEDROCK_BACKOFF_BASE_SECONDS must be >= 0")
    if cfg.backoff_max < cfg.backoff_base:
        raise ValueError(
            "BEDROCK_BACKOFF_MAX_SECONDS must be >= "
            "BEDROCK_BACKOFF_BASE_SECONDS"
        )
    if cfg.breaker_failure_threshold < 1:
        raise ValueError("BEDROCK_BREAKER_FAILURE_THRESHOLD must be >= 1")
    if cfg.breaker_recovery_seconds <= 0:
        raise ValueError("BEDROCK_BREAKER_RECOVERY_SECONDS must be > 0")
    if cfg.total_deadline_seconds <= 0:
        raise ValueError("BEDROCK_TOTAL_DEADLINE_SECONDS must be > 0")
    return cfg


_FAULT_OUTCOMES = {
    "timeout",
    "throttle",
    "server_error",
    "malformed_json",
    "malformed_tool_call",
    "pass",
}


class _FaultPlan:
    def __init__(self, enabled: bool, workflow_step: str, sequence: tuple[str, ...]):
        self.enabled = enabled
        self.workflow_step = workflow_step
        self.sequence = sequence
        self._index = 0
        self._lock = threading.Lock()

    def next(self, workflow_step: str) -> str:
        if (
            not self.enabled
            or workflow_step != self.workflow_step
        ):
            return "pass"
        with self._lock:
            if self._index >= len(self.sequence):
                return "pass"
            outcome = self.sequence[self._index]
            self._index += 1
            return outcome


def _load_fault_plan() -> _FaultPlan:
    enabled = os.environ.get(
        "BEDROCK_FAULT_INJECTION_ENABLED", "false"
    ).lower() in {"1", "true", "yes", "on"}
    workflow_step = os.environ.get("BEDROCK_FAULT_WORKFLOW_STEP", "").strip()
    sequence = tuple(
        item.strip().lower()
        for item in os.environ.get("BEDROCK_FAULT_SEQUENCE", "").split(",")
        if item.strip()
    )
    invalid = sorted(set(sequence) - _FAULT_OUTCOMES)
    if invalid:
        raise ValueError(
            "BEDROCK_FAULT_SEQUENCE contains unsupported outcomes: "
            + ", ".join(invalid)
        )
    if enabled and not is_bedrock_provider():
        raise ValueError(
            "BEDROCK_FAULT_INJECTION_ENABLED requires LLM_PROVIDER=bedrock"
        )
    if enabled and (not workflow_step or not sequence):
        raise ValueError(
            "Enabled Bedrock fault injection requires "
            "BEDROCK_FAULT_WORKFLOW_STEP and BEDROCK_FAULT_SEQUENCE"
        )
    return _FaultPlan(enabled, workflow_step, sequence)


_config = _load_config()
_fault_plan = _load_fault_plan()


def reload_config() -> None:
    """Reload environment configuration; intended for startup and tests."""

    global _config, _fault_plan
    _config = _load_config()
    _fault_plan = _load_fault_plan()


def _get_config() -> _Config:
    return _config


class _CircuitBreaker:
    def __init__(self, failure_threshold: int, recovery_seconds: float):
        self._failure_threshold = failure_threshold
        self._recovery_seconds = recovery_seconds
        self._lock = threading.Lock()
        self._state = "CLOSED"
        self._failure_count = 0
        self._opened_at = 0.0

    def state(self) -> str:
        with self._lock:
            return self._state

    def before_call(self, workflow_step: str) -> None:
        with self._lock:
            if self._state == "OPEN":
                if time.monotonic() - self._opened_at < self._recovery_seconds:
                    _breaker_rejections_counter.add(
                        1,
                        {
                            "workflow_step": workflow_step,
                            "breaker_state": "OPEN",
                        },
                    )
                    _logger.info(
                        "bedrock_breaker_rejected",
                        extra={
                            "workflow_step": workflow_step,
                            "breaker_state": "OPEN",
                        },
                    )
                    raise CircuitBreakerOpenError(
                        "Bedrock circuit breaker is open"
                    )
                self._state = "HALF_OPEN"
                _breaker_transitions_counter.add(
                    1,
                    {
                        "workflow_step": workflow_step,
                        "to_state": "HALF_OPEN",
                    },
                )
                _logger.warning(
                    "bedrock_breaker_half_open",
                    extra={"workflow_step": workflow_step},
                )
                return
            if self._state == "HALF_OPEN":
                _breaker_rejections_counter.add(
                    1,
                    {
                        "workflow_step": workflow_step,
                        "breaker_state": "HALF_OPEN",
                    },
                )
                raise CircuitBreakerOpenError(
                    "Bedrock circuit breaker probe is already in flight"
                )

    def on_success(self, workflow_step: str) -> None:
        with self._lock:
            transitioned = self._state != "CLOSED"
            self._state = "CLOSED"
            self._failure_count = 0
            if transitioned:
                _breaker_transitions_counter.add(
                    1,
                    {
                        "workflow_step": workflow_step,
                        "to_state": "CLOSED",
                    },
                )
                _logger.warning(
                    "bedrock_breaker_recovered",
                    extra={"workflow_step": workflow_step},
                )

    def on_failure(self, workflow_step: str) -> None:
        with self._lock:
            if self._state == "HALF_OPEN":
                self._state = "OPEN"
                self._opened_at = time.monotonic()
                _breaker_transitions_counter.add(
                    1,
                    {
                        "workflow_step": workflow_step,
                        "to_state": "OPEN",
                    },
                )
                return
            self._failure_count += 1
            if self._failure_count >= self._failure_threshold:
                self._state = "OPEN"
                self._opened_at = time.monotonic()
                _breaker_transitions_counter.add(
                    1,
                    {
                        "workflow_step": workflow_step,
                        "to_state": "OPEN",
                    },
                )
                _logger.warning(
                    "bedrock_breaker_opened",
                    extra={"workflow_step": workflow_step},
                )

    def on_nonretryable_failure(self, workflow_step: str) -> None:
        """Release a half-open probe without counting configuration errors."""

        with self._lock:
            if self._state == "HALF_OPEN":
                self._state = "CLOSED"
                self._failure_count = 0
                _breaker_transitions_counter.add(
                    1,
                    {
                        "workflow_step": workflow_step,
                        "to_state": "CLOSED",
                    },
                )


_breaker_registry: dict[str, _CircuitBreaker] = {}
_breaker_registry_lock = threading.Lock()


def _breaker_key() -> str:
    model = os.environ.get("BEDROCK_MODEL_ID", "unknown")
    region = os.environ.get("AWS_REGION", "us-east-1")
    return f"{model}:{region}"


def _get_breaker() -> _CircuitBreaker:
    key = _breaker_key()
    with _breaker_registry_lock:
        breaker = _breaker_registry.get(key)
        if breaker is None:
            cfg = _get_config()
            breaker = _CircuitBreaker(
                cfg.breaker_failure_threshold,
                cfg.breaker_recovery_seconds,
            )
            _breaker_registry[key] = breaker
        return breaker


def get_breaker_state() -> str:
    return _get_breaker().state()


def peek_breaker_state() -> str | None:
    with _breaker_registry_lock:
        breaker = _breaker_registry.get(_breaker_key())
        return breaker.state() if breaker is not None else None


def reset_breaker_state() -> None:
    """Drop process-local breaker state; intended for tests."""

    with _breaker_registry_lock:
        _breaker_registry.clear()


def _default_client_factory(remaining_seconds: float | None = None):
    import boto3
    from botocore.config import Config as BotoConfig

    cfg = _get_config()
    if remaining_seconds is None:
        connect_timeout = cfg.connect_timeout
        read_timeout = cfg.read_timeout
    else:
        budget = max(0.05, remaining_seconds)
        connect_timeout = min(cfg.connect_timeout, budget)
        read_timeout = min(cfg.read_timeout, budget)
    return boto3.client(
        "bedrock-runtime",
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        config=BotoConfig(
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            retries={"total_max_attempts": 1, "mode": "standard"},
        ),
    )


_client_factory: Callable[..., Any] = _default_client_factory


def _make_client(remaining_seconds: float):
    try:
        return _client_factory(remaining_seconds)
    except TypeError:
        # Backward-compatible test seam for existing zero-argument factories.
        return _client_factory()


def _usage(response: dict[str, Any]) -> tuple[int, int]:
    usage = response.get("usage") or {}
    return (
        int(usage.get("inputTokens") or usage.get("input_tokens") or 0),
        int(usage.get("outputTokens") or usage.get("output_tokens") or 0),
    )


def _response_text(response: dict[str, Any]) -> str:
    try:
        content = response["output"]["message"]["content"]
    except (KeyError, TypeError):
        raise InvalidModelOutputError(
            "Bedrock response did not include an assistant message"
        ) from None
    if not isinstance(content, list):
        raise InvalidModelOutputError(
            "Bedrock assistant content was not a list"
        )
    for item in content:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            text = item["text"].strip()
            if text.startswith("```") and text.endswith("```"):
                text = text[3:-3].strip()
                if text.lower().startswith("json"):
                    text = text[4:].strip()
            return text
    raise InvalidModelOutputError(
        "Bedrock response did not include text content"
    )


def _injected_response(outcome: str) -> dict[str, Any] | None:
    if outcome == "pass":
        return None
    if outcome == "timeout":
        from botocore.exceptions import ReadTimeoutError

        raise ReadTimeoutError(endpoint_url="https://bedrock-runtime")
    if outcome in {"throttle", "server_error"}:
        from botocore.exceptions import ClientError

        if outcome == "throttle":
            code, status = "ThrottlingException", 429
        else:
            code, status = "ServiceUnavailableException", 503
        raise ClientError(
            {
                "Error": {"Code": code, "Message": "Injected Bedrock fault"},
                "ResponseMetadata": {"HTTPStatusCode": status},
            },
            "Converse",
        )
    if outcome == "malformed_json":
        return {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [{"text": '{"wrong_schema":true}'}],
                }
            },
            "usage": {"inputTokens": 0, "outputTokens": 0},
        }
    if outcome == "malformed_tool_call":
        return {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "toolUse": {
                                "toolUseId": "mandate25-invalid",
                                "name": "prepare_cart_action",
                                "input": {"quantity": 0},
                            }
                        }
                    ],
                }
            },
            "stopReason": "tool_use",
            "usage": {"inputTokens": 0, "outputTokens": 0},
        }
    raise AssertionError(f"Unhandled Bedrock fault outcome: {outcome}")


def _invoke_once(
    request: dict[str, Any],
    workflow_step: str,
    remaining_seconds: float,
) -> dict[str, Any]:
    outcome = _fault_plan.next(workflow_step)
    if outcome != "pass":
        _fault_injections_counter.add(
            1,
            {"workflow_step": workflow_step, "outcome": outcome},
        )
        _logger.warning(
            "bedrock_fault_injected",
            extra={"workflow_step": workflow_step, "outcome": outcome},
        )
        injected = _injected_response(outcome)
        if injected is not None:
            return injected
    return _make_client(remaining_seconds).converse(**request)


_RETRYABLE_ERROR_CODES = {
    "ThrottlingException",
    "TooManyRequestsException",
    "ServiceUnavailableException",
    "InternalServerException",
    "ModelTimeoutException",
    "ModelErrorException",
}


def _is_retryable(exc: Exception) -> bool:
    from botocore.exceptions import (
        ClientError,
        ConnectionClosedError,
        ConnectTimeoutError,
        EndpointConnectionError,
        ReadTimeoutError,
    )

    if isinstance(
        exc,
        (
            ConnectTimeoutError,
            ReadTimeoutError,
            EndpointConnectionError,
            ConnectionClosedError,
        ),
    ):
        return True
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "")
        status = exc.response.get("ResponseMetadata", {}).get(
            "HTTPStatusCode", 0
        )
        return (
            code in _RETRYABLE_ERROR_CODES
            or status == 429
            or status >= 500
        )
    return False


def _backoff_seconds(cfg: _Config, attempt: int) -> float:
    raw = min(cfg.backoff_max, cfg.backoff_base * (2 ** (attempt - 1)))
    return raw * (0.5 + random.random() / 2)


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _deadline_or_default(deadline: float | None) -> float:
    if deadline is not None:
        return deadline
    return time.monotonic() + _get_config().total_deadline_seconds


def converse_raw(
    request: dict[str, Any],
    *,
    workflow_step: str,
    deadline: float | None = None,
    usage_callback: UsageCallback | None = None,
) -> dict[str, Any]:
    """Run one logical Bedrock call with bounded attempts and a breaker."""

    cfg = _get_config()
    logical_deadline = _deadline_or_default(deadline)
    breaker = _get_breaker()
    started = time.monotonic()
    try:
        breaker.before_call(workflow_step)
    except CircuitBreakerOpenError:
        _request_duration_histogram.record(
            time.monotonic() - started,
            {"workflow_step": workflow_step, "outcome": "breaker_open"},
        )
        raise

    model = str(
        request.get("modelId")
        or os.environ.get("BEDROCK_MODEL_ID", "unknown")
    )
    last_error: Exception | None = None
    for attempt in range(1, cfg.max_attempts + 1):
        remaining = logical_deadline - time.monotonic()
        if remaining <= 0:
            breaker.on_failure(workflow_step)
            _deadline_exceeded_counter.add(
                1, {"workflow_step": workflow_step}
            )
            _request_duration_histogram.record(
                time.monotonic() - started,
                {"workflow_step": workflow_step, "outcome": "deadline"},
            )
            raise BedrockDeadlineExceededError(
                "Bedrock logical request deadline exceeded"
            ) from last_error

        attributes = {
            "workflow_step": workflow_step,
            "attempt": attempt,
        }
        _provider_calls_counter.add(1, attributes)
        try:
            response = call_model(
                lambda: _invoke_once(request, workflow_step, remaining),
                model=model,
                provider="aws.bedrock",
                workflow_step=workflow_step,
            )
        except Exception as exc:
            last_error = exc
            retryable = _is_retryable(exc)
            reason_class = type(exc).__name__
            _provider_failures_counter.add(
                1,
                {
                    "workflow_step": workflow_step,
                    "reason_class": reason_class,
                    "retryable": retryable,
                },
            )
            if not retryable:
                breaker.on_nonretryable_failure(workflow_step)
                _request_duration_histogram.record(
                    time.monotonic() - started,
                    {
                        "workflow_step": workflow_step,
                        "outcome": "failure",
                    },
                )
                raise BedrockUnavailableError(
                    "Bedrock call failed with a non-retryable error"
                ) from exc

            if attempt >= cfg.max_attempts:
                breaker.on_failure(workflow_step)
                _request_duration_histogram.record(
                    time.monotonic() - started,
                    {
                        "workflow_step": workflow_step,
                        "outcome": "failure",
                    },
                )
                raise BedrockUnavailableError(
                    "Bedrock retries were exhausted"
                ) from exc

            backoff = _backoff_seconds(cfg, attempt)
            if time.monotonic() + backoff >= logical_deadline:
                breaker.on_failure(workflow_step)
                _deadline_exceeded_counter.add(
                    1, {"workflow_step": workflow_step}
                )
                raise BedrockDeadlineExceededError(
                    "Bedrock logical request deadline exceeded"
                ) from exc
            _retries_counter.add(
                1,
                {
                    "workflow_step": workflow_step,
                    "reason_class": reason_class,
                },
            )
            _logger.info(
                "bedrock_retry_scheduled",
                extra={
                    "workflow_step": workflow_step,
                    "attempt": attempt,
                    "backoff_seconds": backoff,
                    "reason_class": reason_class,
                },
            )
            _sleep(backoff)
            continue

        breaker.on_success(workflow_step)
        input_tokens, output_tokens = _usage(response)
        if usage_callback is not None:
            usage_callback(input_tokens, output_tokens)
        _request_duration_histogram.record(
            time.monotonic() - started,
            {"workflow_step": workflow_step, "outcome": "success"},
        )
        return response

    raise BedrockUnavailableError("Bedrock call failed") from last_error


def _text_request(system_prompt: str, user_prompt: str) -> dict[str, Any]:
    return {
        "modelId": os.environ["BEDROCK_MODEL_ID"],
        "system": [{"text": system_prompt}],
        "messages": [
            {"role": "user", "content": [{"text": user_prompt}]}
        ],
        "inferenceConfig": {
            "maxTokens": int(os.environ.get("BEDROCK_MAX_TOKENS", "1024")),
            "temperature": 0.0,
        },
    }


def converse_with_usage(
    system_prompt: str,
    user_prompt: str,
    *,
    workflow_step: str = "generation",
    deadline: float | None = None,
) -> tuple[str, int, int]:
    response = converse_raw(
        _text_request(system_prompt, user_prompt),
        workflow_step=workflow_step,
        deadline=deadline,
    )
    input_tokens, output_tokens = _usage(response)
    return _response_text(response), input_tokens, output_tokens


def converse_text(
    system_prompt: str,
    user_prompt: str,
    *,
    workflow_step: str = "generation",
    deadline: float | None = None,
) -> str:
    text, _, _ = converse_with_usage(
        system_prompt,
        user_prompt,
        workflow_step=workflow_step,
        deadline=deadline,
    )
    return text


def converse_json(
    response_model: type[T],
    system_prompt: str,
    user_prompt: str,
    usage_callback: UsageCallback | None = None,
    *,
    workflow_step: str = "structured_generation",
    deadline: float | None = None,
) -> T:
    """Return only a value that strictly validates against ``response_model``."""

    cfg = _get_config()
    logical_deadline = _deadline_or_default(deadline)
    schema_prompt = (
        f"{system_prompt}\n"
        "Return valid JSON only; do not use Markdown fences or commentary."
    )
    last_error: Exception | None = None
    for schema_attempt in range(1, cfg.schema_max_attempts + 1):
        if time.monotonic() >= logical_deadline:
            _deadline_exceeded_counter.add(
                1, {"workflow_step": workflow_step}
            )
            raise BedrockDeadlineExceededError(
                "Bedrock structured-output deadline exceeded"
            ) from last_error
        text, input_tokens, output_tokens = converse_with_usage(
            schema_prompt,
            user_prompt,
            workflow_step=workflow_step,
            deadline=logical_deadline,
        )
        if usage_callback is not None:
            usage_callback(input_tokens, output_tokens)
        try:
            return response_model.model_validate_json(text)
        except ValidationError as exc:
            last_error = exc
            _schema_failures_counter.add(
                1,
                {
                    "workflow_step": workflow_step,
                    "boundary": "structured_json",
                },
            )
            _logger.warning(
                "bedrock_schema_rejected",
                extra={
                    "workflow_step": workflow_step,
                    "attempt": schema_attempt,
                },
            )
    raise InvalidModelOutputError(
        "Bedrock returned invalid structured output"
    ) from last_error


__all__ = [
    "BedrockDeadlineExceededError",
    "BedrockUnavailableError",
    "CircuitBreakerOpenError",
    "InvalidModelOutputError",
    "converse_json",
    "converse_raw",
    "converse_text",
    "converse_with_usage",
    "get_breaker_state",
    "is_bedrock_provider",
    "peek_breaker_state",
    "reload_config",
    "reset_breaker_state",
]
