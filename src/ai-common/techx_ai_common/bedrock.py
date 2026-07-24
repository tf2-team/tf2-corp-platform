#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Shared adapter for Amazon Bedrock Converse requests.

Adds, on top of the raw boto3 call:
  - bounded retries with capped exponential backoff for transient errors
  - a thread-safe circuit breaker, keyed per (model, region)
  - schema-validated structured output via Pydantic, with a bounded
    "repair" retry that never returns unvalidated text/objects

MANDATE #25 Task 1 — see MANDATE25-TASK-1-BEDROCK-RELIABILITY.md.
Public interface (converse_text, converse_json, get_breaker_state, and the
three exception classes) is stable for Task 2 / product_reviews_server.py.
"""

import logging
import os
import random
import threading
import time
from dataclasses import dataclass
from typing import TypeVar

from opentelemetry import metrics
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

_logger = logging.getLogger("techx_ai_common.bedrock")

# ---------------------------------------------------------------------------
# Metrics. Instruments are created against the global MeterProvider at import
# time; OTel's API returns proxy instruments that start emitting once the
# real SDK provider is registered (see product_reviews_server.py __main__),
# so import order relative to SDK setup doesn't matter.
# ---------------------------------------------------------------------------

_meter = metrics.get_meter_provider().get_meter("techx_ai_common.bedrock")

_provider_calls_counter = _meter.create_counter(
    "bedrock_provider_calls_total",
    description="Bedrock Converse calls attempted, one per provider-level attempt",
)
_provider_failures_counter = _meter.create_counter(
    "bedrock_provider_failures_total",
    description="Bedrock Converse call failures, labeled by error category",
)
_retries_counter = _meter.create_counter(
    "bedrock_retries_total",
    description="Bedrock provider retries scheduled after a retryable error",
)
_breaker_transitions_counter = _meter.create_counter(
    "bedrock_breaker_state_transitions_total",
    description="Circuit breaker state transitions, labeled by to_state",
)
_breaker_rejections_counter = _meter.create_counter(
    "bedrock_circuit_open_rejections_total",
    description="Requests rejected before calling the provider because the breaker was open",
)
_schema_failures_counter = _meter.create_counter(
    "bedrock_schema_validation_failures_total",
    description="Bedrock responses rejected by Pydantic schema validation",
)
_deadline_exceeded_counter = _meter.create_counter(
    "bedrock_deadline_exceeded_total",
    description="Calls abandoned because the overall request deadline elapsed",
)
_request_duration_histogram = _meter.create_histogram(
    "bedrock_request_duration_seconds",
    description="Latency of one converse_text call, including all provider attempts",
    unit="s",
)


def is_bedrock_provider() -> bool:
    return os.environ.get("LLM_PROVIDER", "groq").lower() == "bedrock"


# ---------------------------------------------------------------------------
# Public exceptions. Callers match on these, never on boto3/botocore internals.
# ---------------------------------------------------------------------------

class BedrockUnavailableError(RuntimeError):
    """Provider errored, or all retries were exhausted."""


class CircuitBreakerOpenError(BedrockUnavailableError):
    """Request rejected before calling the provider because the breaker is open."""


class BedrockDeadlineExceededError(BedrockUnavailableError):
    """The bounded end-to-end request budget elapsed before a safe result."""


class InvalidModelOutputError(RuntimeError):
    """Model output failed schema validation after all repair attempts."""


# ---------------------------------------------------------------------------
# Config — loaded once at import so bad config fails the process fast
# (per spec 5: "Cấu hình sai phải khiến service fail-fast khi khởi động").
# ---------------------------------------------------------------------------

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
    connect_timeout = _env_float("BEDROCK_CONNECT_TIMEOUT_SECONDS", 3)
    read_timeout = _env_float("BEDROCK_READ_TIMEOUT_SECONDS", 12)
    max_attempts = _env_int("BEDROCK_MAX_ATTEMPTS", 3)
    backoff_base = _env_float("BEDROCK_BACKOFF_BASE_SECONDS", 0.25)
    backoff_max = _env_float("BEDROCK_BACKOFF_MAX_SECONDS", 2)
    schema_max_attempts = _env_int("BEDROCK_SCHEMA_MAX_ATTEMPTS", 2)

    # Worst case without a shared deadline is
    # schema_max_attempts x max_attempts provider calls, each up to
    # (connect + read) seconds, plus backoff between provider retries.
    # BEDROCK_TOTAL_DEADLINE_SECONDS caps that whole chain (provider
    # retries *and* schema-repair retries together) so converse_json()
    # can never run longer than one designed request deadline, no matter
    # where in the chain the time gets spent. Default is derived so it
    # comfortably covers the worst case above without being unbounded.
    derived_default_deadline = schema_max_attempts * (
        max_attempts * (connect_timeout + read_timeout) + (max_attempts - 1) * backoff_max
    )
    total_deadline_seconds = _env_float(
        "BEDROCK_TOTAL_DEADLINE_SECONDS", round(derived_default_deadline, 3)
    )

    cfg = _Config(
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
        max_attempts=max_attempts,
        backoff_base=backoff_base,
        backoff_max=backoff_max,
        schema_max_attempts=schema_max_attempts,
        breaker_failure_threshold=_env_int("BEDROCK_BREAKER_FAILURE_THRESHOLD", 5),
        breaker_recovery_seconds=_env_float("BEDROCK_BREAKER_RECOVERY_SECONDS", 30),
        total_deadline_seconds=total_deadline_seconds,
    )
    if cfg.connect_timeout <= 0 or cfg.read_timeout <= 0:
        raise ValueError("BEDROCK_*_TIMEOUT_SECONDS must be > 0")
    if cfg.max_attempts < 1:
        raise ValueError("BEDROCK_MAX_ATTEMPTS must be >= 1")
    if cfg.schema_max_attempts < 1:
        raise ValueError("BEDROCK_SCHEMA_MAX_ATTEMPTS must be >= 1")
    if cfg.backoff_max < cfg.backoff_base:
        raise ValueError("BEDROCK_BACKOFF_MAX_SECONDS must be >= BEDROCK_BACKOFF_BASE_SECONDS")
    if cfg.breaker_failure_threshold < 1:
        raise ValueError("BEDROCK_BREAKER_FAILURE_THRESHOLD must be >= 1")
    if cfg.total_deadline_seconds <= 0:
        raise ValueError("BEDROCK_TOTAL_DEADLINE_SECONDS must be > 0")
    return cfg


_config = _load_config()


def reload_config() -> None:
    """Re-read env vars. Tests call this after monkeypatching os.environ;
    also safe to call at runtime. Raises ValueError on invalid config."""
    global _config
    _config = _load_config()


def _get_config() -> _Config:
    return _config


# ---------------------------------------------------------------------------
# Circuit breaker — CLOSED / OPEN / HALF_OPEN, thread-safe, one breaker per
# (model, region) since the gRPC server runs multiple worker threads.
# ---------------------------------------------------------------------------

class _CircuitBreaker:
    def __init__(self, failure_threshold: int, recovery_seconds: float):
        self._failure_threshold = failure_threshold
        self._recovery_seconds = recovery_seconds
        self._lock = threading.Lock()
        self._state = "CLOSED"
        self._failure_count = 0
        self._opened_at = 0.0
        self._probe_in_flight = False

    def state(self) -> str:
        with self._lock:
            return self._state

    def before_call(self) -> None:
        """Raise CircuitBreakerOpenError if this call should be rejected.
        Flips CLOSED->... never happens here; only OPEN->HALF_OPEN (single
        probe) and HALF_OPEN rejection of concurrent callers happen here."""
        with self._lock:
            if self._state == "OPEN":
                if time.monotonic() - self._opened_at < self._recovery_seconds:
                    _logger.info("bedrock_breaker_rejected", extra={"breaker_state": "OPEN"})
                    _breaker_rejections_counter.add(1, {"breaker_state": "OPEN"})
                    raise CircuitBreakerOpenError("Bedrock circuit breaker is open")
                # Recovery interval elapsed: exactly one caller gets to probe.
                self._state = "HALF_OPEN"
                self._probe_in_flight = True
                _logger.warning("bedrock_breaker_half_open")
                _breaker_transitions_counter.add(1, {"to_state": "HALF_OPEN"})
                return
            if self._state == "HALF_OPEN":
                _logger.info("bedrock_breaker_rejected", extra={"breaker_state": "HALF_OPEN"})
                _breaker_rejections_counter.add(1, {"breaker_state": "HALF_OPEN"})
                raise CircuitBreakerOpenError("Bedrock circuit breaker is open (probe in flight)")
            # CLOSED: proceed.

    def on_success(self) -> None:
        with self._lock:
            was_open = self._state != "CLOSED"
            self._state = "CLOSED"
            self._failure_count = 0
            self._probe_in_flight = False
            if was_open:
                _logger.warning("bedrock_breaker_recovered")
                _breaker_transitions_counter.add(1, {"to_state": "CLOSED"})

    def on_failure(self) -> None:
        with self._lock:
            if self._state == "HALF_OPEN":
                self._state = "OPEN"
                self._opened_at = time.monotonic()
                self._probe_in_flight = False
                _logger.warning("bedrock_breaker_opened", extra={"from": "half_open_probe"})
                _breaker_transitions_counter.add(1, {"to_state": "OPEN", "from": "half_open_probe"})
                return
            self._failure_count += 1
            if self._failure_count >= self._failure_threshold:
                self._state = "OPEN"
                self._opened_at = time.monotonic()
                _logger.warning("bedrock_breaker_opened", extra={"from": "closed"})
                _breaker_transitions_counter.add(1, {"to_state": "OPEN", "from": "closed"})


_breaker_registry: dict[str, _CircuitBreaker] = {}
_breaker_registry_lock = threading.Lock()


def _breaker_key() -> str:
    return f"{os.environ.get('BEDROCK_MODEL_ID', 'unknown')}:{os.environ.get('AWS_REGION', 'us-east-1')}"


def _get_breaker() -> _CircuitBreaker:
    key = _breaker_key()
    with _breaker_registry_lock:
        breaker = _breaker_registry.get(key)
        if breaker is None:
            cfg = _get_config()
            breaker = _CircuitBreaker(cfg.breaker_failure_threshold, cfg.breaker_recovery_seconds)
            _breaker_registry[key] = breaker
        return breaker


def get_breaker_state() -> str:
    """CLOSED, OPEN or HALF_OPEN for the current Bedrock model/region."""
    return _get_breaker().state()


def peek_breaker_state() -> str | None:
    """Return the existing breaker's state without creating one for logging."""
    with _breaker_registry_lock:
        breaker = _breaker_registry.get(_breaker_key())
        return breaker.state() if breaker is not None else None


def reset_breaker_state() -> None:
    """Test-only helper: drop all breaker state."""
    with _breaker_registry_lock:
        _breaker_registry.clear()


# ---------------------------------------------------------------------------
# Provider call — timeout config, no boto3-internal retries (we own retries),
# error classification, capped exponential backoff with jitter.
# ---------------------------------------------------------------------------

def _default_client_factory():
    import boto3
    from botocore.config import Config as BotoConfig

    cfg = _get_config()
    return boto3.client(
        "bedrock-runtime",
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        config=BotoConfig(
            connect_timeout=cfg.connect_timeout,
            read_timeout=cfg.read_timeout,
            # Single attempt inside botocore: the app-level loop below is the
            # only retry policy, so total call count stays == BEDROCK_MAX_ATTEMPTS.
            retries={"total_max_attempts": 1, "mode": "standard"},
        ),
    )


# Tests monkeypatch this to inject a fake client.
_client_factory = _default_client_factory


def _response_text(response: dict) -> str:
    for content in response["output"]["message"]["content"]:
        if "text" in content:
            return content["text"].strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    raise RuntimeError("Bedrock Converse response did not include text content")


def _invoke_once(system_prompt: str, user_prompt: str) -> str:
    cfg = _get_config()
    response = _client_factory().converse(
        modelId=os.environ["BEDROCK_MODEL_ID"],
        system=[{"text": system_prompt}],
        messages=[{"role": "user", "content": [{"text": user_prompt}]}],
        inferenceConfig={
            "maxTokens": int(os.environ.get("BEDROCK_MAX_TOKENS", "1024")),
            "temperature": 0.0,
        },
    )
    return _response_text(response)


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

    if isinstance(exc, (ConnectTimeoutError, ReadTimeoutError, EndpointConnectionError, ConnectionClosedError)):
        return True
    if isinstance(exc, ClientError):
        error = exc.response.get("Error", {})
        code = error.get("Code", "")
        if code in _RETRYABLE_ERROR_CODES:
            return True
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
        return status == 429 or status >= 500
    return False


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _backoff_seconds(cfg: _Config, attempt: int) -> float:
    raw = min(cfg.backoff_max, cfg.backoff_base * (2 ** (attempt - 1)))
    jitter = 0.5 + random.random() / 2  # keeps result in (0.5x, 1.0x] of raw, still <= backoff_max
    return raw * jitter


def converse_text(system_prompt: str, user_prompt: str, deadline: float | None = None) -> str:
    """Invoke Bedrock, retrying transient errors up to BEDROCK_MAX_ATTEMPTS.

    `deadline` is an absolute time.monotonic() value shared across the whole
    logical request (see converse_json). When called directly (deadline=None)
    a fresh per-call deadline is derived from config, so converse_text stays
    usable standalone. Once the deadline passes — whether time was spent on
    provider backoff or on schema-repair attempts in converse_json — the call
    is abandoned as BedrockUnavailableError instead of retrying further.
    """
    cfg = _get_config()
    breaker = _get_breaker()
    if deadline is None:
        deadline = time.monotonic() + cfg.total_deadline_seconds

    start = time.monotonic()
    try:
        breaker.before_call()  # raises CircuitBreakerOpenError without touching boto3
    except CircuitBreakerOpenError:
        _request_duration_histogram.record(time.monotonic() - start, {"outcome": "breaker_open"})
        raise

    for attempt in range(1, cfg.max_attempts + 1):
        if time.monotonic() >= deadline:
            _deadline_exceeded_counter.add(1)
            _logger.warning("bedrock_retry_exhausted", extra={"attempt": attempt, "error_category": "DeadlineExceeded"})
            _request_duration_histogram.record(time.monotonic() - start, {"outcome": "deadline_exceeded"})
            raise BedrockDeadlineExceededError("Bedrock call failed: overall request deadline exceeded")

        _logger.info("bedrock_call_started", extra={"attempt": attempt})
        _provider_calls_counter.add(1)
        try:
            text = _invoke_once(system_prompt, user_prompt)
        except Exception as exc:
            error_category = type(exc).__name__
            retryable = _is_retryable(exc)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            _provider_failures_counter.add(1, {"error_category": error_category})

            backoff = _backoff_seconds(cfg, attempt) if retryable else 0.0
            has_attempt_remaining = retryable and attempt < cfg.max_attempts
            if has_attempt_remaining and time.monotonic() + backoff >= deadline:
                _deadline_exceeded_counter.add(1)
                _logger.warning(
                    "bedrock_retry_exhausted",
                    extra={"attempt": attempt, "error_category": "DeadlineExceeded"},
                )
                _request_duration_histogram.record(time.monotonic() - start, {"outcome": "deadline_exceeded"})
                raise BedrockDeadlineExceededError(
                    "Bedrock call failed: overall request deadline exceeded"
                ) from exc
            can_retry = has_attempt_remaining
            if can_retry:
                _logger.info(
                    "bedrock_retry_scheduled",
                    extra={"attempt": attempt, "backoff_seconds": backoff, "error_category": error_category},
                )
                _retries_counter.add(1, {"error_category": error_category})
                _sleep(backoff)
                continue
            breaker.on_failure()
            _logger.warning(
                "bedrock_retry_exhausted",
                extra={"attempt": attempt, "error_category": error_category, "elapsed_ms": elapsed_ms},
            )
            _request_duration_histogram.record(time.monotonic() - start, {"outcome": "failure"})
            raise BedrockUnavailableError(f"Bedrock call failed: {error_category}") from exc
        else:
            breaker.on_success()
            _request_duration_histogram.record(time.monotonic() - start, {"outcome": "success"})
            return text

    # Unreachable (loop always returns or raises), kept for type-checkers.
    raise BedrockUnavailableError("Bedrock call failed")


def converse_json(response_model: type[T], system_prompt: str, user_prompt: str) -> T:
    """Invoke Bedrock and validate its JSON response.

    Provider errors (BedrockUnavailableError / CircuitBreakerOpenError) come
    from converse_text, which already owns the provider-level retry+breaker
    chain, and propagate immediately — they are not schema problems, so they
    are not retried again here. Only malformed/invalid JSON is retried, up
    to BEDROCK_SCHEMA_MAX_ATTEMPTS.

    Worst case this still issues up to SCHEMA_MAX_ATTEMPTS x MAX_ATTEMPTS
    provider calls, but a single deadline (BEDROCK_TOTAL_DEADLINE_SECONDS,
    computed from the other settings unless overridden) is created here once
    and passed into every converse_text() call below, so schema-repair
    attempts and provider retries draw from the same wall-clock budget.
    Whichever loop is running when the budget runs out abandons the call
    immediately instead of continuing to retry past the designed deadline.
    """
    cfg = _get_config()
    schema_prompt = f"{system_prompt}\nReturn valid JSON only; do not use Markdown fences."
    deadline = time.monotonic() + cfg.total_deadline_seconds
    last_error: Exception | None = None
    for schema_attempt in range(1, cfg.schema_max_attempts + 1):
        if time.monotonic() >= deadline:
            _deadline_exceeded_counter.add(1)
            _logger.warning("bedrock_retry_exhausted", extra={"attempt": schema_attempt, "error_category": "DeadlineExceeded"})
            raise BedrockDeadlineExceededError("Bedrock call failed: overall request deadline exceeded")

        text = converse_text(schema_prompt, user_prompt, deadline=deadline)
        try:
            return response_model.model_validate_json(text)
        except ValidationError as exc:
            last_error = exc
            _logger.warning("bedrock_schema_rejected", extra={"attempt": schema_attempt})
            _schema_failures_counter.add(1)
    raise InvalidModelOutputError("Bedrock returned invalid structured output after retries") from last_error
